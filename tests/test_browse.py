"""
Reading the web through Firecrawl or Browserbase.

Nothing here touches the network: both providers take their transport by
injection, so the contract — request shape, response parsing, error mapping,
session release — is tested against fakes.

Run: python -m unittest tests.test_browse -v
"""
from __future__ import annotations

import json
import sys
import unittest
import urllib.error
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau.browse import registry  # noqa: E402
from rau.browse.base import (  # noqa: E402
    MAX_TEXT_CHARS,
    BrowseError,
    Page,
    clamp_timeout,
    normalise_url,
    post_json,
)
from rau.browse.browserbase import BrowserbaseBrowser  # noqa: E402
from rau.browse.firecrawl import FirecrawlBrowser  # noqa: E402
from rau.events import BUS  # noqa: E402


class UrlTests(unittest.TestCase):
    def test_fills_in_what_a_model_is_likely_to_leave_off(self) -> None:
        self.assertEqual(normalise_url("example.com"), "https://example.com")
        self.assertEqual(normalise_url("//example.com"), "https://example.com")
        self.assertEqual(normalise_url(" https://x.dev/a "), "https://x.dev/a")

    def test_refuses_anything_that_is_not_a_web_page(self) -> None:
        for bad in ("file:///etc/passwd", "javascript:alert(1)", "data:text/html,x"):
            with self.assertRaises(BrowseError) as caught:
                normalise_url(bad)
            self.assertEqual(caught.exception.code, "bad_scheme", bad)
        with self.assertRaises(BrowseError):
            normalise_url("")

    def test_timeouts_are_bounded(self) -> None:
        self.assertEqual(clamp_timeout(10), 10)
        self.assertEqual(clamp_timeout(10_000), 120.0)
        self.assertEqual(clamp_timeout(-4), 45.0)
        self.assertEqual(clamp_timeout("nonsense"), 45.0)


class PageTests(unittest.TestCase):
    def test_a_huge_page_is_trimmed_before_it_reaches_a_context_window(self) -> None:
        page = Page(url="u", title="t", text="x" * (MAX_TEXT_CHARS + 5_000), links=["a"] * 500)
        trimmed = page.trimmed()
        self.assertLessEqual(len(trimmed.text), MAX_TEXT_CHARS + 40)
        self.assertIn("truncated", trimmed.text)
        self.assertEqual(len(trimmed.links), 60)


class HttpErrorMappingTests(unittest.TestCase):
    def _raise(self, code: int):
        def opener(*_args, **_kwargs):
            raise urllib.error.HTTPError("u", code, "boom", {}, None)

        return opener

    def test_a_rejected_key_is_named_as_such(self) -> None:
        for code, expected in ((401, "bad_key"), (403, "bad_key"), (429, "rate_limited"), (500, "http_error")):
            with mock.patch("urllib.request.urlopen", self._raise(code)):
                with self.assertRaises(BrowseError) as caught:
                    post_json("https://x", {}, {}, timeout=1)
            self.assertEqual(caught.exception.code, expected, code)

    def test_an_unreachable_provider_says_so(self) -> None:
        def opener(*_args, **_kwargs):
            raise urllib.error.URLError("no route")

        with mock.patch("urllib.request.urlopen", opener):
            with self.assertRaises(BrowseError) as caught:
                post_json("https://x", {}, {}, timeout=1)
        self.assertEqual(caught.exception.code, "unreachable")


class FirecrawlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def _post(self, response: Dict[str, Any]):
        def post(url, payload, headers, *, timeout):
            self.calls.append(
                {"url": url, "payload": payload, "headers": headers, "timeout": timeout}
            )
            return response

        return post

    def _browser(self, response: Dict[str, Any]) -> FirecrawlBrowser:
        return FirecrawlBrowser(post=self._post(response))

    def test_reads_a_page_into_markdown(self) -> None:
        browser = self._browser(
            {
                "success": True,
                "data": {
                    "markdown": "# Hello\n\nbody",
                    "metadata": {"title": "Hello", "url": "https://x.dev/a"},
                    "links": ["https://x.dev/b", "mailto:nope"],
                },
            }
        )
        with mock.patch("rau.browse.firecrawl.get_secret", return_value="key"):
            page = browser.fetch("x.dev/a")

        self.assertEqual(page.title, "Hello")
        self.assertEqual(page.url, "https://x.dev/a")
        self.assertIn("body", page.text)
        # Only real web links survive.
        self.assertEqual(page.links, ["https://x.dev/b"])
        self.assertEqual(page.provider, "firecrawl")

        sent = self.calls[0]
        self.assertTrue(sent["url"].endswith("/v2/scrape"))
        self.assertEqual(sent["payload"]["url"], "https://x.dev/a")
        self.assertEqual(sent["payload"]["formats"], ["markdown", "links"])
        self.assertTrue(sent["payload"]["onlyMainContent"])
        self.assertEqual(sent["headers"]["Authorization"], "Bearer key")
        # Firecrawl should give up before we do, not after.
        self.assertLess(sent["payload"]["timeout"] / 1000, sent["timeout"])

    def test_a_missing_key_is_refused_before_any_request(self) -> None:
        browser = self._browser({})
        with mock.patch("rau.browse.firecrawl.get_secret", return_value=""):
            with self.assertRaises(BrowseError) as caught:
                browser.fetch("x.dev")
        self.assertEqual(caught.exception.code, "no_key")
        self.assertEqual(self.calls, [])

    def test_an_empty_page_is_an_error_not_an_empty_answer(self) -> None:
        browser = self._browser({"success": True, "data": {"markdown": "  "}})
        with mock.patch("rau.browse.firecrawl.get_secret", return_value="key"):
            with self.assertRaises(BrowseError) as caught:
                browser.fetch("x.dev")
        self.assertEqual(caught.exception.code, "empty_page")

    def test_searches_and_reads_the_hits(self) -> None:
        browser = self._browser(
            {
                "success": True,
                "data": {
                    "web": [
                        {"title": "One", "url": "https://a.dev", "description": "first"},
                        {"url": "https://b.dev"},
                        {"title": "no url"},
                    ]
                },
            }
        )
        with mock.patch("rau.browse.firecrawl.get_secret", return_value="key"):
            hits = browser.search("something", limit=3)

        self.assertEqual([h.url for h in hits], ["https://a.dev", "https://b.dev"])
        self.assertEqual(hits[0].snippet, "first")
        # A hit with no url is unusable, not a blank row.
        self.assertEqual(self.calls[0]["payload"]["limit"], 3)
        self.assertTrue(self.calls[0]["url"].endswith("/v2/search"))

    def test_a_search_limit_cannot_be_pushed_past_the_ceiling(self) -> None:
        browser = self._browser({"success": True, "data": {"web": []}})
        with mock.patch("rau.browse.firecrawl.get_secret", return_value="key"):
            browser.search("q", limit=500)
        self.assertLessEqual(self.calls[0]["payload"]["limit"], 20)


class FakeSocket:
    """A CDP peer that answers whatever it is asked, plus unsolicited events."""

    def __init__(self, results: Dict[str, Any], *, noise: bool = True) -> None:
        self.results = results
        self.sent: List[Dict[str, Any]] = []
        self.closed = False
        self._outbox: List[str] = []
        self._noise = noise

    def send(self, raw: str) -> None:
        message = json.loads(raw)
        self.sent.append(message)
        if self._noise:
            # Events share the wire with replies; a correct client skips them.
            self._outbox.append(json.dumps({"method": "Page.frameNavigated", "params": {}}))
        result = self.results.get(message["method"], {})
        if callable(result):
            result = result(message)
        self._outbox.append(json.dumps({"id": message["id"], "result": result}))

    def recv(self, timeout: float = 0):  # noqa: ARG002
        if not self._outbox:
            raise TimeoutError("nothing queued")
        return self._outbox.pop(0)

    def close(self) -> None:
        self.closed = True


class BrowserbaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.posts: List[Dict[str, Any]] = []
        self.socket = FakeSocket(
            {
                "Target.createTarget": {"targetId": "T1"},
                "Target.attachToTarget": {"sessionId": "S1"},
                "Page.enable": {},
                "Page.navigate": {},
                "Runtime.evaluate": self._evaluate,
            }
        )

    def _evaluate(self, message: Dict[str, Any]) -> Dict[str, Any]:
        expression = message["params"]["expression"]
        if "readyState" in expression:
            return {"result": {"value": "complete"}}
        return {
            "result": {
                "value": json.dumps(
                    {
                        "title": "Real Page",
                        "url": "https://app.dev/dash",
                        "text": "rendered by javascript",
                        "links": ["https://app.dev/next"],
                    }
                )
            }
        }

    def _post(self, url, payload, headers, *, timeout):  # noqa: ARG002
        self.posts.append({"url": url, "payload": payload, "headers": headers})
        if url.endswith("/sessions"):
            return {"id": "sess-1", "connectUrl": "wss://cdp.example/sess-1"}
        return {}

    def _browser(self) -> BrowserbaseBrowser:
        return BrowserbaseBrowser(post=self._post, connect=lambda url, timeout: self.socket)

    def test_drives_a_real_browser_and_reads_the_rendered_page(self) -> None:
        with mock.patch("rau.browse.browserbase.get_secret", return_value="key"):
            page = self._browser().fetch("app.dev/dash")

        self.assertEqual(page.title, "Real Page")
        self.assertEqual(page.text, "rendered by javascript")
        self.assertEqual(page.links, ["https://app.dev/next"])
        self.assertEqual(page.provider, "browserbase")

        methods = [m["method"] for m in self.socket.sent]
        self.assertEqual(methods[:4], [
            "Target.createTarget",
            "Target.attachToTarget",
            "Page.enable",
            "Page.navigate",
        ])
        # Everything after attach is addressed to the page's own session.
        for message in self.socket.sent[2:]:
            self.assertEqual(message.get("sessionId"), "S1", message["method"])
        navigate = next(m for m in self.socket.sent if m["method"] == "Page.navigate")
        self.assertEqual(navigate["params"]["url"], "https://app.dev/dash")

    def test_the_session_is_always_released_even_when_the_page_fails(self) -> None:
        """Sessions bill by the minute; a failure must not leave one running."""
        self.socket.results["Target.createTarget"] = {}
        with mock.patch("rau.browse.browserbase.get_secret", return_value="key"):
            with self.assertRaises(BrowseError):
                self._browser().fetch("app.dev")

        release = [p for p in self.posts if p["payload"].get("status") == "REQUEST_RELEASE"]
        self.assertEqual(len(release), 1)
        self.assertTrue(release[0]["url"].endswith("/sessions/sess-1"))
        self.assertTrue(self.socket.closed)

    def test_the_session_is_released_on_the_happy_path_too(self) -> None:
        with mock.patch("rau.browse.browserbase.get_secret", return_value="key"):
            self._browser().fetch("app.dev")
        self.assertTrue(
            any(p["payload"].get("status") == "REQUEST_RELEASE" for p in self.posts)
        )

    def test_a_session_without_a_connect_url_is_released_before_failing(self) -> None:
        """The create call succeeded, so the session is billing; raising on
        the missing connectUrl must hand it back first, not leave it idling
        until the provider's timeout."""
        def no_connect_url(url, payload, headers, *, timeout):  # noqa: ARG002
            self.posts.append({"url": url, "payload": payload, "headers": headers})
            if url.endswith("/sessions"):
                return {"id": "sess-9"}  # no connectUrl
            return {}

        browser = BrowserbaseBrowser(
            post=no_connect_url, connect=lambda url, timeout: self.socket
        )
        with mock.patch("rau.browse.browserbase.get_secret", return_value="key"):
            with self.assertRaises(BrowseError) as caught:
                browser.fetch("app.dev")
        self.assertEqual(caught.exception.code, "bad_response")
        release = [p for p in self.posts if p["payload"].get("status") == "REQUEST_RELEASE"]
        self.assertEqual(len(release), 1)
        self.assertTrue(release[0]["url"].endswith("/sessions/sess-9"))

    def test_authenticates_with_the_header_browserbase_expects(self) -> None:
        with mock.patch("rau.browse.browserbase.get_secret", return_value="secret"):
            self._browser().fetch("app.dev")
        self.assertEqual(self.posts[0]["headers"]["X-BB-API-Key"], "secret")

    def test_a_page_with_no_text_is_an_error(self) -> None:
        self.socket.results["Runtime.evaluate"] = lambda m: (
            {"result": {"value": "complete"}}
            if "readyState" in m["params"]["expression"]
            else {"result": {"value": json.dumps({"text": "   "})}}
        )
        with mock.patch("rau.browse.browserbase.get_secret", return_value="key"):
            with self.assertRaises(BrowseError) as caught:
                self._browser().fetch("app.dev")
        self.assertEqual(caught.exception.code, "empty_page")

    def test_it_cannot_search_and_says_so_rather_than_pretending(self) -> None:
        browser = self._browser()
        self.assertFalse(browser.can_search)
        with self.assertRaises(BrowseError) as caught:
            browser.search("anything")
        self.assertEqual(caught.exception.code, "unsupported")


class ResolutionTests(unittest.TestCase):
    def _keys(self, **present: bool):
        def has(env: str) -> bool:
            return present.get(env, False)

        return mock.patch("rau.browse.registry.has_secret", side_effect=has)

    def _slot(self, provider: str):
        return mock.patch(
            "rau.browse.registry.get_slot", return_value={"provider": provider}
        )

    def test_auto_prefers_firecrawl_when_both_are_connected(self) -> None:
        with self._slot("auto"), self._keys(FIRECRAWL_API_KEY=True, BROWSERBASE_API_KEY=True):
            provider, _ = registry.resolve_browse()
        self.assertEqual(provider, "firecrawl")

    def test_auto_falls_through_to_the_one_that_is_connected(self) -> None:
        with self._slot("auto"), self._keys(BROWSERBASE_API_KEY=True):
            provider, view = registry.resolve_browse()
        self.assertEqual(provider, "browserbase")
        self.assertFalse(view["can_search"])

    def test_auto_with_nothing_connected_resolves_to_nothing(self) -> None:
        with self._slot("auto"), self._keys():
            provider, view = registry.resolve_browse()
        self.assertEqual(provider, "")
        self.assertIn("no key", view["reason"])

    def test_a_deliberate_choice_is_not_silently_swapped(self) -> None:
        """
        Being told the key is missing beats quietly using the other backend:
        the two behave differently and cost differently.
        """
        with self._slot("browserbase"), self._keys(FIRECRAWL_API_KEY=True):
            provider, view = registry.resolve_browse()
        self.assertEqual(provider, "")
        self.assertIn("browserbase", view["reason"])

    def test_a_nonsense_choice_degrades_to_automatic(self) -> None:
        with self._slot("wormhole"), self._keys(FIRECRAWL_API_KEY=True):
            provider, view = registry.resolve_browse()
        self.assertEqual(provider, "firecrawl")
        self.assertEqual(view["configured"], "auto")

    def test_get_browser_refuses_clearly_when_nothing_is_configured(self) -> None:
        with self._slot("auto"), self._keys():
            with self.assertRaises(BrowseError) as caught:
                registry.get_browser()
        self.assertEqual(caught.exception.code, "no_provider")

    def test_status_reports_what_the_settings_page_needs(self) -> None:
        with self._slot("firecrawl"), self._keys(FIRECRAWL_API_KEY=True):
            snapshot = registry.status()
        self.assertTrue(snapshot["ready"])
        self.assertEqual(snapshot["provider"], "firecrawl")
        self.assertTrue(snapshot["can_search"])
        self.assertIn("browserbase", snapshot["available"])


class Recorder:
    def __init__(self, *kinds: str) -> None:
        self.events: List[Dict[str, Any]] = []
        self._kinds = set(kinds)
        BUS.on("*", self._append)

    def _append(self, event: Dict[str, Any]) -> None:
        if not self._kinds or event.get("kind") in self._kinds:
            self.events.append(event)

    def kinds(self) -> List[str]:
        return [e["kind"] for e in self.events]

    def stop(self) -> None:
        with BUS._lock:  # noqa: SLF001
            BUS._subs["*"] = [fn for fn in BUS._subs["*"] if fn is not self._append]


class BrowseToolTests(unittest.TestCase):
    """The tool, and the body language that brackets it."""

    def test_he_walks_to_the_computer_and_comes_back(self) -> None:
        from rau.face import web

        page = Page(url="https://x.dev", title="X", text="hello", provider="firecrawl")
        fake = mock.Mock(can_search=True, label="Firecrawl")
        fake.fetch.return_value = page

        recorder = Recorder("browse_started", "browse_finished")
        try:
            with mock.patch.object(web, "get_browser", return_value=("firecrawl", fake)):
                result = web.browse_web({"url": "x.dev"})
        finally:
            recorder.stop()

        self.assertTrue(result["ok"])
        self.assertEqual(result["text"], "hello")
        self.assertEqual(recorder.kinds(), ["browse_started", "browse_finished"])
        started, finished = recorder.events
        self.assertEqual(started["mode"], "open")
        # The renderer needs a backstop in case the fetch never reports back.
        self.assertGreater(started["watchdog_ms"], 0)
        self.assertEqual(started["activity_id"], finished["activity_id"])
        self.assertTrue(finished["ok"])

    def test_a_failed_fetch_still_brings_him_back_from_the_desk(self) -> None:
        from rau.face import web

        fake = mock.Mock(can_search=True, label="Firecrawl")
        fake.fetch.side_effect = BrowseError("site is down", code="unreachable")

        recorder = Recorder("browse_started", "browse_finished")
        try:
            with mock.patch.object(web, "get_browser", return_value=("firecrawl", fake)):
                result = web.browse_web({"url": "x.dev"})
        finally:
            recorder.stop()

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "unreachable")
        self.assertEqual(recorder.kinds(), ["browse_started", "browse_finished"])
        self.assertFalse(recorder.events[-1]["ok"])

    def test_an_unexpected_crash_also_releases_him(self) -> None:
        from rau.face import web

        fake = mock.Mock(can_search=True, label="Firecrawl")
        fake.fetch.side_effect = ZeroDivisionError("boom")

        recorder = Recorder("browse_started", "browse_finished")
        try:
            with mock.patch.object(web, "get_browser", return_value=("firecrawl", fake)):
                result = web.browse_web({"url": "x.dev"})
        finally:
            recorder.stop()

        self.assertFalse(result["ok"])
        self.assertEqual(recorder.kinds(), ["browse_started", "browse_finished"])

    def test_a_missing_backend_answers_without_walking_anywhere(self) -> None:
        from rau.face import web

        recorder = Recorder("browse_started", "browse_finished")
        try:
            with mock.patch.object(
                web,
                "get_browser",
                side_effect=BrowseError("nothing configured", code="no_provider"),
            ):
                result = web.browse_web({"url": "x.dev"})
        finally:
            recorder.stop()

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "no_provider")
        # No trip across the room for an answer we already had.
        self.assertEqual(recorder.kinds(), [])

    def test_searching_on_a_backend_that_cannot_search_says_which_can(self) -> None:
        from rau.face import web

        fake = mock.Mock(can_search=False, label="Browserbase")
        recorder = Recorder("browse_started", "browse_finished")
        try:
            with mock.patch.object(web, "get_browser", return_value=("browserbase", fake)):
                result = web.browse_web({"query": "weather"})
        finally:
            recorder.stop()
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "unsupported")
        self.assertIn("Firecrawl", result["error"])
        # Unsupported still has to release the desk walk it started.
        self.assertEqual(recorder.kinds(), ["browse_started", "browse_finished"])
        self.assertFalse(recorder.events[-1]["ok"])

    def test_the_arguments_have_to_make_sense(self) -> None:
        from rau.face import web

        self.assertEqual(web.browse_web({})["code"], "nothing_to_do")
        self.assertEqual(
            web.browse_web({"url": "a", "query": "b"})["code"], "conflicting_input"
        )
        self.assertEqual(web.browse_web({"depth": 3})["code"], "unknown_field")
        self.assertEqual(web.browse_web("go")["code"], "malformed")

    def test_the_face_can_reach_the_tool(self) -> None:
        from rau.face import brain

        names = {t["function"]["name"] for t in brain.FACE_TOOLS}
        self.assertIn("browse_web", names)

    def test_the_prompt_says_what_the_web_situation_actually_is(self) -> None:
        """
        With a backend it explains the tool; without one it says plainly that
        there is no web access, rather than offering a tool that cannot run.
        """
        from rau.face import brain, web

        with mock.patch.object(
            web, "resolve_browse", return_value=("firecrawl", {"can_search": True})
        ):
            self.assertIn("browse_web", brain._system_prompt())  # noqa: SLF001

        with mock.patch.object(web, "resolve_browse", return_value=("", {})):
            prompt = brain._system_prompt()  # noqa: SLF001
        self.assertIn("no web access", prompt)
        self.assertNotIn("`browse_web` reads pages", prompt)

    def test_a_backend_that_cannot_search_says_so_in_the_prompt(self) -> None:
        from rau.face import web

        with mock.patch.object(
            web, "resolve_browse", return_value=("browserbase", {"can_search": False})
        ):
            fragment = web.prompt_fragment()
        self.assertIn("cannot search", fragment)

    def test_reading_a_page_is_allowed_when_the_room_is_read_only(self) -> None:
        from rau.permissions import is_readonly_allowed

        self.assertTrue(is_readonly_allowed("browse_web"))


class SlotPersistenceTests(unittest.TestCase):
    """The picker is worthless if the choice does not survive the save."""

    def test_the_api_accepts_and_stores_a_browse_choice(self) -> None:
        import tempfile

        from rau.hub import server
        from rau.providers import registry as models_registry

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.json"
            with mock.patch.object(models_registry, "MODELS_CONFIG", path):
                with mock.patch.object(models_registry, "_models", {}):
                    saved = server.api_models_put(
                        server.ModelsIn(browse={"provider": "browserbase"})
                    )
                    # `ModelsIn` had no `browse` field at first, so the whole
                    # request was silently dropped and the picker did nothing.
                    self.assertEqual(saved["browse"]["provider"], "browserbase")
                    self.assertEqual(
                        models_registry.get_slot("browse")["provider"], "browserbase"
                    )

    def test_the_api_refuses_a_backend_that_does_not_exist(self) -> None:
        import tempfile

        from rau.hub import server
        from rau.providers import registry as models_registry

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.json"
            with mock.patch.object(models_registry, "MODELS_CONFIG", path):
                with mock.patch.object(models_registry, "_models", {}):
                    response = server.api_models_put(
                        server.ModelsIn(browse={"provider": "wormhole"})
                    )
        self.assertEqual(getattr(response, "status_code", 200), 400)


if __name__ == "__main__":
    unittest.main()
