"""Edge-case tests for the current backend hardening pass.

Covers: rau.hub.security (+ middleware), rau.env atomic secret writes,
rau.providers.registry atomic/recovery paths, rau.identity.store soul
validation + backup fallback, rau.dream.dreamer window parsing, and
rau.providers.openai_compat stream error handling.

The suite encodes adversarial regressions discovered during the final red-team
pass; every case is expected to pass before release.

Run: python -m unittest tests.test_backend_hardening -v
"""
from __future__ import annotations

import asyncio
import contextlib
import errno
import io
import json
import os
import shutil
import stat
import sys
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau.hub import security  # noqa: E402
from rau.hub.security import (  # noqa: E402
    LocalAccessMiddleware,
    allowed_hostnames,
    host_allowed,
    origin_allowed,
)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

class _TempTree(unittest.TestCase):
    """Give each test its own directory and restore patched module globals."""

    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="rau-hardening-"))
        self.addCleanup(shutil.rmtree, self.dir, True)

    def tmp_leftovers(self, directory: Path) -> list:
        return sorted(p.name for p in directory.iterdir() if p.name.endswith(".tmp"))


def _run_asgi(app, scope, messages=None):
    """Drive an ASGI app once and collect everything it sends."""
    sent = []
    incoming = list(messages or [])

    async def receive():
        return incoming.pop(0) if incoming else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    return sent


def _headers(**kw):
    return [(k.replace("_", "-").encode("latin-1"), v.encode("latin-1")) for k, v in kw.items()]


class _OkApp:
    def __init__(self):
        self.calls = 0

    async def __call__(self, scope, receive, send):
        self.calls += 1
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


class _FakeHTTPResponse(io.BytesIO):
    """Minimal stand-in for the object urlopen returns."""

    def __init__(self, payload: bytes):
        super().__init__(payload)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _sse(*events: str) -> bytes:
    return ("".join(f"data: {e}\n\n" for e in events) + "data: [DONE]\n\n").encode("utf-8")


# ==========================================================================
# rau/hub/security.py
# ==========================================================================

class HostnameTests(unittest.TestCase):
    def test_wildcard_binds_are_never_allowlisted(self):
        for bind in ("0.0.0.0", "::", "[::]", "", "   "):
            allowed = allowed_hostnames(bind)
            self.assertEqual(
                allowed,
                {"localhost", "127.0.0.1", "::1"},
                f"wildcard bind {bind!r} must not widen the allowlist",
            )

    def test_configured_and_extra_hosts_are_added(self):
        allowed = allowed_hostnames("rau.lan", ["192.168.1.9", "Rau.Local:8765"])
        self.assertIn("rau.lan", allowed)
        self.assertIn("192.168.1.9", allowed)
        self.assertIn("rau.local", allowed)  # lowercased, port stripped

    def test_loopback_hosts_pass(self):
        allowed = allowed_hostnames("127.0.0.1")
        for host in ("localhost", "localhost:8765", "LOCALHOST", "localhost.",
                     "127.0.0.1:8765", "[::1]:8765", "[::1]"):
            self.assertTrue(host_allowed(host, allowed), host)

    def test_dns_rebinding_and_spoofed_authorities_are_rejected(self):
        allowed = allowed_hostnames("127.0.0.1")
        for host in (
            "",                       # missing Host header
            "evil.com",
            "evil.com:8765",
            "127.0.0.1.evil.com",     # rebinding suffix
            "localhost.evil.com",
            "localhost@evil.com",     # userinfo trick: real host is evil.com
            "127.1",                  # alternate loopback spelling, not allowlisted
            "2130706433",             # decimal 127.0.0.1
            "0.0.0.0",
            "[::]",
        ):
            self.assertFalse(host_allowed(host, allowed), host)


class OriginTests(unittest.TestCase):
    def test_exact_same_origin_allowed(self):
        self.assertTrue(origin_allowed("http://localhost:8765", "localhost:8765"))
        self.assertTrue(origin_allowed("http://localhost:5173", "localhost:5173"))
        self.assertTrue(origin_allowed("HTTP://LocalHost:5173", "localhost:5173"))

    def test_cross_origin_and_opaque_origins_rejected(self):
        for origin, host in (
            ("http://evil.com", "localhost:8765"),
            ("http://localhost:1337", "localhost:8765"),   # another local server
            ("http://localhost", "localhost:8765"),        # port must match
            ("http://127.0.0.1:8765", "localhost:8765"),   # different authority
            ("null", "localhost:8765"),                    # sandboxed iframe
            ("file://", "localhost:8765"),
            ("chrome-extension://abc", "localhost:8765"),
        ):
            self.assertFalse(origin_allowed(origin, host), f"{origin} -> {host}")

    def test_missing_origin_is_currently_trusted(self):
        # Documents the deliberate non-browser escape hatch.
        self.assertTrue(origin_allowed("", "localhost:8765"))
        self.assertTrue(origin_allowed(None, "localhost:8765"))

    def test_scheme_should_be_part_of_the_origin_comparison(self):
        # BUG: only the authority is compared, so an https origin matches an
        # http hub (and vice versa). Same-origin means scheme+host+port.
        self.assertFalse(origin_allowed("https://localhost:8765", "localhost:8765"))

    def test_websocket_schemes_map_onto_the_http_origin_scheme(self):
        # REGRESSION: ASGI reports scope["scheme"] as "ws"/"wss" for websocket
        # connections, but a browser always sends an http(s) Origin for the
        # handshake. Comparing them verbatim rejects every browser socket.
        self.assertTrue(origin_allowed("http://localhost:8765", "localhost:8765", "ws"))
        self.assertTrue(origin_allowed("https://localhost:8765", "localhost:8765", "wss"))
        self.assertFalse(origin_allowed("http://localhost:8765", "localhost:8765", "wss"))
        self.assertFalse(origin_allowed("http://evil.com", "localhost:8765", "ws"))


class MiddlewareTests(unittest.TestCase):
    def setUp(self):
        self.inner = _OkApp()
        self.app = LocalAccessMiddleware(
            self.inner, allowed_hosts=allowed_hostnames("127.0.0.1")
        )

    def _http(self, **hdrs):
        return _run_asgi(
            self.app,
            {"type": "http", "method": "POST", "path": "/api/chat", "headers": _headers(**hdrs)},
        )

    def test_same_origin_request_reaches_the_app(self):
        sent = self._http(host="localhost:8765", origin="http://localhost:8765",
                          sec_fetch_site="same-origin")
        self.assertEqual(self.inner.calls, 1)
        self.assertEqual(sent[0]["status"], 200)

    def test_untrusted_host_gets_403_and_never_reaches_the_app(self):
        sent = self._http(host="evil.com", origin="http://evil.com")
        self.assertEqual(self.inner.calls, 0)
        self.assertEqual(sent[0]["status"], 403)
        body = sent[-1]["body"]
        self.assertEqual(json.loads(body)["ok"], False)
        hdrs = dict(sent[0]["headers"])
        self.assertEqual(hdrs[b"content-length"], str(len(body)).encode())
        self.assertEqual(hdrs[b"cache-control"], b"no-store")

    def test_cross_site_fetch_metadata_is_rejected_even_on_a_good_host(self):
        sent = self._http(host="localhost:8765", sec_fetch_site="cross-site")
        self.assertEqual(self.inner.calls, 0)
        self.assertEqual(sent[0]["status"], 403)

    def test_same_origin_websocket_handshake_is_accepted(self):
        # The voice socket and the event socket both depend on this path.
        sent = _run_asgi(
            self.app,
            {"type": "websocket", "scheme": "ws", "path": "/ws/voice",
             "headers": _headers(host="localhost:8765", origin="http://localhost:8765")},
        )
        self.assertEqual(self.inner.calls, 1, f"browser websocket rejected: {sent}")

    def test_cross_origin_websocket_is_closed_with_1008(self):
        sent = _run_asgi(
            self.app,
            {"type": "websocket", "path": "/ws/voice",
             "headers": _headers(host="localhost:8765", origin="http://evil.com")},
        )
        self.assertEqual(self.inner.calls, 0)
        self.assertEqual(sent, [{"type": "websocket.close", "code": 1008,
                                 "reason": "untrusted origin"}])

    def test_lifespan_scope_passes_through_untouched(self):
        seen = {}

        async def app(scope, receive, send):
            seen["type"] = scope["type"]

        asyncio.run(LocalAccessMiddleware(app, allowed_hosts=set())(
            {"type": "lifespan"}, None, None))
        self.assertEqual(seen["type"], "lifespan")

    def test_headers_with_non_latin1_bytes_do_not_crash_the_middleware(self):
        scope = {"type": "http", "method": "GET", "path": "/",
                 "headers": [(b"host", b"localhost:8765"), (b"x-junk", b"\xff\xfe")]}
        sent = _run_asgi(self.app, scope)
        self.assertEqual(sent[0]["status"], 200)


# ==========================================================================
# rau/env.py — atomic secret writes
# ==========================================================================

class EnvSecretTests(_TempTree):
    def setUp(self):
        super().setUp()
        import rau.env as env

        self.env = env
        self.env_file = self.dir / ".env"
        self._patches = [
            patch.object(env, "ENV_FILE", self.env_file),
            patch.object(env, "ensure_dirs", lambda: None),
            patch.dict(os.environ, {}, clear=False),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(os.environ.pop, "RAU_TEST_KEY", None)

    def test_write_is_atomic_and_leaves_no_temp_files(self):
        self.env_file.write_text("# keep me\nOTHER=1\n", encoding="utf-8")
        self.env.set_secret("RAU_TEST_KEY", "abc123")
        text = self.env_file.read_text(encoding="utf-8")
        self.assertIn("# keep me", text)
        self.assertIn("OTHER=1", text)
        self.assertIn("RAU_TEST_KEY=abc123", text)
        self.assertEqual(self.tmp_leftovers(self.dir), [])

    def test_env_file_is_written_owner_only(self):
        self.env.set_secret("RAU_TEST_KEY", "abc123")
        mode = stat.S_IMODE(self.env_file.stat().st_mode)
        self.assertEqual(mode, 0o600, oct(mode))

    def test_failed_replace_preserves_the_original_and_cleans_up(self):
        self.env_file.write_text("RAU_TEST_KEY=original\n", encoding="utf-8")
        boom = OSError(errno.EIO, "disk gone")
        with patch.object(self.env.os, "replace", side_effect=boom):
            with self.assertRaises(OSError):
                self.env.set_secret("RAU_TEST_KEY", "replacement")
        self.assertEqual(self.env_file.read_text(encoding="utf-8"), "RAU_TEST_KEY=original\n")
        self.assertEqual(self.tmp_leftovers(self.dir), [])

    def test_clear_secret_removes_the_line_and_the_process_env(self):
        self.env.set_secret("RAU_TEST_KEY", "abc123")
        self.env.clear_secret("RAU_TEST_KEY")
        self.assertNotIn("RAU_TEST_KEY", self.env_file.read_text(encoding="utf-8"))
        self.assertNotIn("RAU_TEST_KEY", os.environ)

    def test_concurrent_writers_do_not_lose_keys(self):
        names = [f"RAU_CONC_{i}" for i in range(12)]
        for n in names:
            self.addCleanup(os.environ.pop, n, None)
        start = threading.Barrier(len(names))
        errors = []

        def worker(name):
            try:
                start.wait(timeout=5)
                self.env.set_secret(name, f"v-{name}")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(n,)) for n in names]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(errors, [])
        data = self.env._read_env_map()
        for n in names:
            self.assertEqual(data.get(n), f"v-{n}", f"{n} lost by a concurrent write")
        self.assertEqual(self.tmp_leftovers(self.dir), [])

    def test_secret_name_is_validated(self):
        for bad in ("", "lower", "1BAD", "HAS SPACE", "A-B", "A\nB"):
            with self.assertRaises(ValueError, msg=bad):
                self.env.set_secret(bad, "x")

    def test_newline_in_a_secret_value_must_be_rejected(self):
        # BUG (exploitable): only the *name* is validated. A value containing a
        # newline injects extra KEY=VALUE lines into .env, which load_dotenv
        # then exports into the process and every subprocess it spawns.
        # Reachable from PUT /api/auth/{provider_id} with body.key.
        with self.assertRaises(ValueError):
            self.env.set_secret("RAU_TEST_KEY", "sk-real\nPATH=/tmp/evil")

    def test_newline_injection_cannot_create_extra_env_entries(self):
        with self.assertRaises(ValueError):
            self.env.set_secret("RAU_TEST_KEY", "sk-real\nRAU_INJECTED=pwned")
        self.assertNotIn("RAU_INJECTED", self.env._read_env_map())


# ==========================================================================
# rau/providers/registry.py — atomic write + corrupt-config recovery
# ==========================================================================

def _slot(provider="kimi", model="k3", effort="high"):
    return {"provider": provider, "model": model, "max_tokens": 512,
            "temperature": 0.7, "effort": effort}


class RegistryTests(_TempTree):
    # A fully valid user config: every CHAT_SLOT populated, kimi-selected face.
    REAL = {"face": _slot(), "subagent": _slot(), "dream": _slot()}

    def setUp(self):
        super().setUp()
        import rau.providers.registry as registry

        self.registry = registry
        self.models = self.dir / "models.json"
        self.settings = self.dir / "settings.json"
        for p in (
            patch.object(registry, "MODELS_CONFIG", self.models),
            patch.object(registry, "SETTINGS_CONFIG", self.settings),
            patch.object(registry, "ensure_dirs", lambda: None),
        ):
            p.start()
            self.addCleanup(p.stop)

    def test_missing_config_is_seeded_with_defaults(self):
        cfg = self.registry.load_models()
        self.assertTrue(self.models.exists())
        self.assertEqual(json.loads(self.models.read_text()), cfg)
        self.assertEqual(self.tmp_leftovers(self.dir), [])

    def test_new_slots_are_backfilled_without_clobbering_user_choices(self):
        self.models.write_text(json.dumps(self.REAL), encoding="utf-8")
        cfg = self.registry.load_models()
        self.assertEqual(cfg["face"]["provider"], "kimi")
        self.assertIn("subagent", cfg)  # backfilled default slot
        self.assertEqual(json.loads(self.models.read_text())["face"]["provider"], "kimi")

    def test_corrupt_json_falls_back_to_defaults_instead_of_raising(self):
        self.models.write_text("{ truncated", encoding="utf-8")
        cfg = self.registry.load_models()
        self.assertIn("face", cfg)

    def test_non_object_json_falls_back_to_defaults(self):
        self.models.write_text("[1, 2, 3]", encoding="utf-8")
        self.assertIn("face", self.registry.load_models())

    def test_save_models_rejects_non_objects(self):
        for bad in ([], "x", None, 7):
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.registry.save_models(bad)

    def test_save_models_leaves_no_temp_files(self):
        self.registry.save_models(dict(self.REAL))
        self.assertEqual(self.tmp_leftovers(self.dir), [])

    def test_save_models_rejects_out_of_range_slot_values(self):
        for bad in (
            {"max_tokens": 0}, {"max_tokens": 10**9}, {"max_tokens": True},
            {"temperature": -1}, {"temperature": 5}, {"temperature": float("nan")},
            {"effort": "turbo"}, {"provider": "no-such-provider"},
            {"model": ""}, {"model": "a\nb"}, {"model": "x" * 400},
        ):
            cfg = {k: dict(v) for k, v in self.REAL.items()}
            cfg["face"].update(bad)
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.registry.save_models(cfg)

    def test_load_settings_merges_defaults_over_a_partial_file(self):
        self.settings.write_text(json.dumps({"hub_port": 9999}), encoding="utf-8")
        s = self.registry.load_settings()
        self.assertEqual(s["hub_port"], 9999)
        self.assertEqual(s["dream_window_start"], "02:00")  # default filled in

    def test_load_settings_does_not_create_the_file(self):
        self.registry.load_settings()
        self.assertFalse(self.settings.exists())

    def test_corrupt_settings_do_not_kill_startup(self):
        self.settings.write_text("nope", encoding="utf-8")
        self.assertEqual(self.registry.load_settings()["hub_port"], 8765)

    def test_unreadable_models_config_must_not_be_overwritten(self):
        # BUG (data loss): _read_object() maps *any* OSError to "use defaults",
        # and load_models() then persists those defaults over the file. A
        # transient permission/EMFILE/IO error silently destroys the user's
        # entire model configuration with no backup.
        self.models.write_text(json.dumps(self.REAL), encoding="utf-8")
        with patch.object(
            Path, "read_text", side_effect=OSError(errno.EACCES, "denied")
        ):
            self.registry.load_models()
        self.assertEqual(json.loads(self.models.read_text())["face"]["provider"], "kimi")

    def test_corrupt_models_config_should_be_quarantined_before_overwrite(self):
        # BUG (data loss): the corrupt bytes are destroyed by the very recovery
        # meant to protect them. Copy to models.json.bad-<stamp> first so the
        # user (or a support session) can still recover their slots.
        self.models.write_text("{ truncated", encoding="utf-8")
        self.registry.load_models()
        self.assertTrue(
            any(p.name.startswith("models.json.bad") for p in self.dir.iterdir()),
            "no quarantine copy of the corrupt config was kept",
        )


# ==========================================================================
# rau/identity/store.py — soul validation, atomic write, backup fallback
# ==========================================================================

GOOD_SOUL = (
    "# Soul — operating self for Rau\n\n"
    "You are Rau. You are one continuous being and only you ever speak aloud.\n"
    "You remember the person you live with and you grow from diary and dreams.\n"
)
GOOD_BACKUP = GOOD_SOUL.replace("dreams", "dreams and quiet mornings")


class IdentityStoreTests(_TempTree):
    def setUp(self):
        super().setUp()
        import rau.identity.store as store

        self.store = store
        self.soul = self.dir / "soul.md"
        self.bak = self.dir / "soul.bak.md"
        for p in (
            patch.object(store, "SOUL_MD", self.soul),
            patch.object(store, "SOUL_BAK", self.bak),
            patch.object(store, "IDENTITY_DIR", self.dir),
            patch.object(store, "ensure_dirs", lambda: None),
        ):
            p.start()
            self.addCleanup(p.stop)

    # --- validation -------------------------------------------------------
    def test_valid_soul_rejects_empty_short_and_off_format(self):
        self.assertFalse(self.store.valid_soul(""))
        self.assertFalse(self.store.valid_soul(None))
        self.assertFalse(self.store.valid_soul("   \n  "))
        self.assertFalse(self.store.valid_soul("Rau."))                    # too short
        self.assertFalse(self.store.valid_soul("x" * 500))                 # no marker
        self.assertTrue(self.store.valid_soul(GOOD_SOUL))

    def test_write_soul_refuses_to_destroy_a_good_soul(self):
        self.soul.write_text(GOOD_SOUL, encoding="utf-8")
        for junk in ("", "   ", "```\n```", "I cannot help with that.", "null"):
            with self.assertRaises(ValueError, msg=repr(junk)):
                self.store.write_soul(junk)
        self.assertEqual(self.soul.read_text(encoding="utf-8"), GOOD_SOUL)

    def test_write_soul_strips_code_fences(self):
        self.store.write_soul("```markdown\n" + GOOD_SOUL + "\n```")
        self.assertTrue(self.soul.read_text(encoding="utf-8").startswith("# Soul"))
        self.assertNotIn("```", self.soul.read_text(encoding="utf-8"))

    # --- atomic write -----------------------------------------------------
    def test_write_text_is_atomic_and_leaves_no_temp_files(self):
        self.store.write_text(self.soul, GOOD_SOUL)
        self.assertTrue(self.soul.read_text(encoding="utf-8").endswith("\n"))
        self.assertEqual(self.tmp_leftovers(self.dir), [])

    def test_failed_replace_leaves_the_previous_soul_intact(self):
        self.soul.write_text(GOOD_SOUL, encoding="utf-8")
        with patch.object(self.store.os, "replace", side_effect=OSError(errno.EIO, "io")):
            with self.assertRaises(OSError):
                self.store.write_text(self.soul, "brand new soul for Rau " * 20)
        self.assertEqual(self.soul.read_text(encoding="utf-8"), GOOD_SOUL)
        self.assertEqual(self.tmp_leftovers(self.dir), [])

    # --- reads / fallback -------------------------------------------------
    def test_read_text_survives_a_missing_or_undecodable_file(self):
        self.assertEqual(self.store.read_text(self.dir / "nope.md"), "")
        binary = self.dir / "binary.md"
        binary.write_bytes(b"\xff\xfe\x00\x01")
        self.assertEqual(self.store.read_text(binary), "")

    def test_load_soul_uses_the_backup_when_soul_md_is_truncated(self):
        self.soul.write_text("# Soul\n", encoding="utf-8")  # truncated by a crash
        self.bak.write_text(GOOD_BACKUP, encoding="utf-8")
        self.assertEqual(self.store.load_soul(), GOOD_BACKUP)

    def test_load_soul_falls_back_to_the_seed_when_both_are_unusable(self):
        self.soul.write_text("", encoding="utf-8")
        self.bak.write_text("junk", encoding="utf-8")
        seed = self.store.load_soul()
        self.assertTrue(self.store.valid_soul(seed))
        self.assertIn("Rau", seed)

    def test_has_soul_tracks_validity_not_mere_existence(self):
        self.soul.write_text("# Soul\n", encoding="utf-8")
        self.assertFalse(self.store.has_soul())
        self.soul.write_text(GOOD_SOUL, encoding="utf-8")
        self.assertTrue(self.store.has_soul())

    def test_backup_soul_will_not_clobber_a_good_backup_with_a_broken_soul(self):
        self.bak.write_text(GOOD_BACKUP, encoding="utf-8")
        self.soul.write_text("# Soul\n", encoding="utf-8")  # corrupt current
        self.assertIsNone(self.store.backup_soul())
        self.assertEqual(self.bak.read_text(encoding="utf-8"), GOOD_BACKUP)

    def test_backup_soul_should_write_soul_bak_atomically(self):
        self.soul.write_text(GOOD_SOUL, encoding="utf-8")
        self.bak.write_text(GOOD_BACKUP, encoding="utf-8")
        real_replace = os.replace

        def crashing_replace(src, dst):
            if Path(dst) == self.bak:
                raise OSError(errno.EIO, "power lost before replace")
            return real_replace(src, dst)

        with patch.object(self.store.os, "replace", crashing_replace):
            with self.assertRaises(OSError):
                self.store.backup_soul()
        self.assertEqual(self.bak.read_text(encoding="utf-8"), GOOD_BACKUP)
        self.assertEqual(self.tmp_leftovers(self.dir), [])

    def test_a_non_english_soul_must_not_be_discarded(self):
        # BUG (identity loss): valid_soul() requires the literal ASCII
        # substring "rau". A Korean-language soul is silently rejected, so
        # write_soul() raises every night and load_soul() throws the user's
        # real identity away in favour of the English seed.
        korean = (
            "# 소울 — 라우의 운영 자아\n\n"
            "너는 라우다. 너는 하나의 이어지는 존재이고 오직 너만 말한다.\n"
            "너는 함께 사는 사람을 기억하고 일기와 꿈에서 자라난다.\n"
            "도구와 서브에이전트는 조용한 내면의 일이며 결코 다른 사람이 아니다.\n"
        )
        self.assertTrue(self.store.valid_soul(korean))


# ==========================================================================
# rau/dream/dreamer.py — window parsing + loop resilience
# ==========================================================================

class DreamWindowTests(unittest.TestCase):
    def setUp(self):
        from rau.dream import dreamer

        self.dreamer = dreamer

    def at(self, hh, mm):
        return datetime(2026, 7, 26, hh, mm)

    @contextlib.contextmanager
    def _bounded_loop(self, d, iterations):
        """Let dream_loop() spin exactly `iterations` times, then exit.

        NOTE: dream_loop ignores the return value of _stop.wait(), so the exit
        condition has to come from is_set() — patching wait() alone hangs.
        """
        ticks = {"n": 0}

        def is_set():
            return ticks["n"] >= iterations

        def wait(_timeout):
            ticks["n"] += 1
            return False

        d._stop.clear()
        with patch.object(d._stop, "is_set", is_set), \
             patch.object(d._stop, "wait", wait):
            yield

    def test_normal_window(self):
        f = self.dreamer._in_window
        self.assertTrue(f(self.at(3, 0), "02:00", "05:00"))
        self.assertTrue(f(self.at(2, 0), "02:00", "05:00"))   # inclusive start
        self.assertTrue(f(self.at(5, 0), "02:00", "05:00"))   # inclusive end
        self.assertFalse(f(self.at(1, 59), "02:00", "05:00"))
        self.assertFalse(f(self.at(5, 1), "02:00", "05:00"))

    def test_window_wrapping_past_midnight(self):
        f = self.dreamer._in_window
        self.assertTrue(f(self.at(23, 30), "23:00", "05:00"))
        self.assertTrue(f(self.at(0, 1), "23:00", "05:00"))
        self.assertTrue(f(self.at(4, 59), "23:00", "05:00"))
        self.assertFalse(f(self.at(12, 0), "23:00", "05:00"))

    def test_degenerate_and_boundary_windows(self):
        f = self.dreamer._in_window
        self.assertTrue(f(self.at(2, 0), "02:00", "02:00"))
        self.assertFalse(f(self.at(2, 1), "02:00", "02:00"))
        self.assertTrue(f(self.at(0, 0), "00:00", "23:59"))
        self.assertTrue(f(self.at(23, 59), "00:00", "23:59"))
        self.assertTrue(f(self.at(9, 5), "9:5", "9:5"))  # unpadded is accepted

    def test_malformed_window_settings_raise_valueerror(self):
        f = self.dreamer._in_window
        for bad in ("", None, "2", "02", "02:00:00", "aa:bb", "02:", ":00",
                    "24:00", "02:60", "-1:00", "02:-5", "  ", "02;00"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                f(self.at(3, 0), bad, "05:00")
            with self.assertRaises(ValueError, msg=repr(bad)):
                f(self.at(3, 0), "02:00", bad)

    def test_dream_loop_survives_a_malformed_window_setting(self):
        d = self.dreamer
        emitted = []
        with self._bounded_loop(d, 3), \
             patch.object(d, "load_settings",
                          return_value={"dream_window_start": "oops",
                                        "dream_window_end": "05:00"}), \
             patch.object(d.BUS, "emit", lambda name, **kw: emitted.append((name, kw))), \
             patch.object(d, "run_dream", side_effect=AssertionError("must not run")):
            d.dream_loop()

        self.assertEqual(len(emitted), 1, "malformed settings should be rate-limited")
        self.assertTrue(all(name == "dream_error" for name, _ in emitted))

    def test_a_failing_dream_should_not_be_retried_every_60_seconds(self):
        # BUG (cost/log flood): run_dream() failures never advance `last_day`,
        # so a persistent failure (no API key, provider 500, malformed window)
        # retries every 60s for the whole 3h window — ~180 provider calls and
        # ~180 dream_error events per night. Needs a per-day failure latch or
        # exponential backoff.
        d = self.dreamer
        calls = {"n": 0}

        def boom(_day):
            calls["n"] += 1
            raise RuntimeError("provider down")

        with self._bounded_loop(d, 10), \
             patch.object(d, "load_settings",
                          return_value={"dream_window_start": "00:00",
                                        "dream_window_end": "23:59"}), \
             patch.object(d.BUS, "emit", lambda name, **kw: None), \
             patch.object(d, "should_defer", return_value=False), \
             patch.object(d, "run_dream", side_effect=boom):
            d.dream_loop()

        self.assertLessEqual(calls["n"], 3, f"retried {calls['n']} times in one window")


# ==========================================================================
# rau/providers/openai_compat.py — stream error handling
# ==========================================================================

class ChoiceDeltaTests(unittest.TestCase):
    def setUp(self):
        from rau.providers import openai_compat

        self.oc = openai_compat

    def test_provider_error_events_are_raised(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.oc._choice_delta({"error": {"message": "rate limited"}})
        self.assertIn("rate limited", str(ctx.exception))
        with self.assertRaises(RuntimeError):
            self.oc._choice_delta({"error": "upstream exploded"})

    def test_benign_shapes_yield_an_empty_delta(self):
        for chunk in (
            {},
            {"error": None},
            {"choices": None},
            {"choices": []},
            {"choices": "nope"},
            {"choices": [None]},
            {"choices": [{"delta": None}]},
            {"choices": [{"delta": "text"}]},
            {"choices": [{}]},
            "not a dict",
            None,
            [],
        ):
            self.assertEqual(self.oc._choice_delta(chunk), {}, repr(chunk))

    def test_tool_index_bounds(self):
        f = self.oc._tool_index
        self.assertEqual(f(None), 0)
        self.assertEqual(f(0), 0)
        self.assertEqual(f("3"), 3)
        self.assertEqual(f(1024), 1024)
        self.assertIsNone(f(1025))
        self.assertIsNone(f(-1))
        self.assertIsNone(f("nope"))
        self.assertIsNone(f({}))
        self.assertIsNone(f(float("nan")))
        self.assertIsNone(f(float("inf")))


class StreamHandlingTests(unittest.TestCase):
    def setUp(self):
        from rau.providers import openai_compat

        self.oc = openai_compat
        self.p = openai_compat.OpenAICompatProvider("fake", "http://x/v1", "FAKE_KEY")
        p = patch.object(openai_compat, "get_secret", lambda *a, **k: "key")
        p.start()
        self.addCleanup(p.stop)

    def _stream(self, payload: bytes = b"", *, raises=None):
        kw = {"side_effect": raises} if raises else {"return_value": _FakeHTTPResponse(payload)}
        with patch.object(self.oc.urllib.request, "urlopen", **kw):
            return list(self.p.chat_stream(
                [self.oc.Message(role="user", content="hi")], model="m"))

    def test_tokens_are_yielded_and_done_terminates(self):
        payload = _sse(
            json.dumps({"choices": [{"delta": {"content": "he"}}]}),
            json.dumps({"choices": [{"delta": {"content": "llo"}}]}),
        )
        self.assertEqual(self._stream(payload), ["he", "llo"])

    def test_non_string_and_empty_tokens_are_skipped_not_crashed(self):
        payload = _sse(
            json.dumps({"choices": [{"delta": {"content": 42}}]}),
            json.dumps({"choices": [{"delta": {"content": None}}]}),
            json.dumps({"choices": [{"delta": {"content": {"a": 1}}}]}),
            json.dumps({"choices": [{"delta": {"content": "ok"}}]}),
        )
        self.assertEqual(self._stream(payload), ["ok"])

    def test_mid_stream_error_event_raises(self):
        payload = _sse(
            json.dumps({"choices": [{"delta": {"content": "partial"}}]}),
            json.dumps({"error": {"message": "context length exceeded"}}),
        )
        with self.assertRaises(RuntimeError) as ctx:
            self._stream(payload)
        self.assertIn("context length exceeded", str(ctx.exception))

    def test_a_few_malformed_events_are_tolerated(self):
        events = ["{oops"] * self.oc.MAX_MALFORMED_STREAM_EVENTS
        events.append(json.dumps({"choices": [{"delta": {"content": "ok"}}]}))
        self.assertEqual(self._stream(_sse(*events)), ["ok"])

    def test_a_flood_of_malformed_events_aborts_the_stream(self):
        events = ["{oops"] * (self.oc.MAX_MALFORMED_STREAM_EVENTS + 1)
        with self.assertRaises(RuntimeError) as ctx:
            self._stream(_sse(*events))
        self.assertIn("malformed", str(ctx.exception))

    def test_keepalive_comments_and_blank_lines_are_ignored(self):
        payload = (b": ping\n\n\n"
                   + _sse(json.dumps({"choices": [{"delta": {"content": "x"}}]})))
        self.assertEqual(self._stream(payload), ["x"])

    def test_http_error_is_wrapped_with_the_provider_name(self):
        err = self.oc.urllib.error.HTTPError(
            "http://x/v1", 429, "Too Many Requests", {},
            io.BytesIO(b'{"error":"slow down"}'))
        with self.assertRaises(RuntimeError) as ctx:
            self._stream(raises=err)
        self.assertIn("fake HTTP 429", str(ctx.exception))
        self.assertIn("slow down", str(ctx.exception))

    def test_url_error_is_wrapped_not_leaked(self):
        err = self.oc.urllib.error.URLError("no route to host")
        with self.assertRaises(RuntimeError) as ctx:
            self._stream(raises=err)
        self.assertIn("unreachable", str(ctx.exception))

    def test_oversized_non_stream_response_is_rejected(self):
        big = b'{"choices":[{"message":{"content":"' + b"a" * (
            self.oc.MAX_RESPONSE_BYTES + 10) + b'"}}]}'
        with patch.object(self.oc.urllib.request, "urlopen",
                          return_value=_FakeHTTPResponse(big)):
            with self.assertRaises(RuntimeError) as ctx:
                self.p.chat([self.oc.Message(role="user", content="hi")], model="m")
        self.assertIn("exceeded", str(ctx.exception))

    def test_invalid_json_body_is_rejected(self):
        with patch.object(self.oc.urllib.request, "urlopen",
                          return_value=_FakeHTTPResponse(b"<html>502</html>")):
            with self.assertRaises(RuntimeError) as ctx:
                self.p.chat([self.oc.Message(role="user", content="hi")], model="m")
        self.assertIn("invalid JSON", str(ctx.exception))

    def test_streamed_text_must_be_size_capped(self):
        # BUG (DoS / OOM): MAX_RESPONSE_BYTES only guards the non-streaming
        # path. stream()/stream_turn() accumulate tokens and tool-call argument
        # fragments with no ceiling, so a hostile or looping upstream (base_url
        # is user-configurable) can drive the hub out of memory.
        chunk = json.dumps({"choices": [{"delta": {"content": "a" * 4096}}]})
        events = [chunk] * 4096  # ~16 MB of text
        with self.assertRaises(RuntimeError):
            self._stream(_sse(*events))

    def test_a_stream_without_newlines_must_not_be_buffered_unbounded(self):
        # BUG (DoS / OOM): `for raw in resp` reads a *line*. An upstream that
        # never emits "\n" makes the first read buffer the whole response into
        # memory before any of the guards above can run.
        payload = b"data: " + b"a" * (self.oc.MAX_RESPONSE_BYTES + 1)
        with self.assertRaises(RuntimeError):
            self._stream(payload)


if __name__ == "__main__":
    unittest.main(verbosity=2)
