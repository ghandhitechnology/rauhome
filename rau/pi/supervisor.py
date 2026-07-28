"""Lazy lifecycle supervision for the optional Pi sidecar."""
from __future__ import annotations

import atexit
import os
import secrets
import shutil
import signal
import socket
import subprocess
import threading
import time
from typing import Any, Dict, Optional, Tuple

from rau.paths import ROOT
from rau.pi.client import DEFAULT_BASE_URL, PiSidecar
from rau.providers.registry import load_settings

#: Mirrors rau.agent.tools._shell_env: the sidecar runs model-authored tools, so
#: it must not inherit provider credentials beyond the one its own provider
#: needs. The sidecar additionally scrubs its tool shells itself (run.mjs).
_SENSITIVE_ENV_SUFFIXES = ("_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_CREDENTIAL")
_SENSITIVE_ENV_NAMES = {"AUTHORIZATION", "AWS_SESSION_TOKEN"}

#: Credential variables pi-ai 0.82.1 (pinned in pi-sidecar/package.json)
#: resolves from the environment per provider id — its env-api-keys.js. Only
#: the configured Pi provider's entries are handed to the sidecar; every other
#: provider key stays out of a process a prompt-injected command can inspect.
_PI_PROVIDER_ENV: Dict[str, Tuple[str, ...]] = {
    "anthropic": ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_OAUTH_TOKEN"),
    "github-copilot": ("COPILOT_GITHUB_TOKEN",),
    "ant-ling": ("ANT_LING_API_KEY",),
    "qwen-token-plan": ("QWEN_TOKEN_PLAN_API_KEY",),
    "qwen-token-plan-cn": ("QWEN_TOKEN_PLAN_CN_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "azure-openai-responses": ("AZURE_OPENAI_API_KEY",),
    "nvidia": ("NVIDIA_API_KEY",),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "google": ("GEMINI_API_KEY",),
    "google-vertex": ("GOOGLE_CLOUD_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS"),
    "groq": ("GROQ_API_KEY",),
    "cerebras": ("CEREBRAS_API_KEY",),
    "xai": ("XAI_API_KEY",),
    "radius": ("RADIUS_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
    "vercel-ai-gateway": ("AI_GATEWAY_API_KEY",),
    "zai": ("ZAI_API_KEY",),
    "zai-coding-cn": ("ZAI_CODING_CN_API_KEY",),
    "mistral": ("MISTRAL_API_KEY",),
    "minimax": ("MINIMAX_API_KEY",),
    "minimax-cn": ("MINIMAX_CN_API_KEY",),
    "moonshotai": ("MOONSHOT_API_KEY",),
    "moonshotai-cn": ("MOONSHOT_API_KEY",),
    "huggingface": ("HF_TOKEN",),
    "fireworks": ("FIREWORKS_API_KEY",),
    "together": ("TOGETHER_API_KEY",),
    "opencode": ("OPENCODE_API_KEY",),
    "opencode-go": ("OPENCODE_API_KEY",),
    "kimi-coding": ("KIMI_API_KEY",),
    "cloudflare-workers-ai": ("CLOUDFLARE_API_KEY",),
    "cloudflare-ai-gateway": ("CLOUDFLARE_API_KEY",),
    "xiaomi": ("XIAOMI_API_KEY",),
    "xiaomi-token-plan-cn": ("XIAOMI_TOKEN_PLAN_CN_API_KEY",),
    "xiaomi-token-plan-ams": ("XIAOMI_TOKEN_PLAN_AMS_API_KEY",),
    "xiaomi-token-plan-sgp": ("XIAOMI_TOKEN_PLAN_SGP_API_KEY",),
    "amazon-bedrock": (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_BEARER_TOKEN_BEDROCK",
        "AWS_PROFILE",
    ),
}


def _sidecar_env(provider_override: str = "") -> Dict[str, str]:
    """Environment for a spawned sidecar: no credentials it does not need."""
    env: Dict[str, str] = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().endswith(_SENSITIVE_ENV_SUFFIXES)
        and key.upper() not in _SENSITIVE_ENV_NAMES
    }
    # Sidecar configuration rides along even when it looks sensitive
    # (PI_SIDECAR_TOKEN); the sidecar keeps it out of tool shells itself.
    for key, value in os.environ.items():
        if key.startswith("PI_SIDECAR_"):
            env[key] = value
    provider = str(
        provider_override
        or os.environ.get("PI_PROVIDER")
        or load_settings().get("pi_provider")
        or ""
    ).strip()
    for key in _PI_PROVIDER_ENV.get(provider, ()):
        credential_value = os.environ.get(key)
        if credential_value is not None:
            env[key] = credential_value
    return env


class PiSupervisor:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._process: Optional[subprocess.Popen] = None
        self._base_url = DEFAULT_BASE_URL
        self._last_used = 0.0
        self._registered = False

    def enabled(self) -> bool:
        env = os.environ.get("PI_EXECUTOR_ENABLED")
        if env is not None:
            return env.strip().lower() in {"1", "true", "yes", "on"}
        return bool(load_settings().get("pi_executor_enabled", False))

    def installed(self) -> bool:
        """Whether this checkout can start the optional harness without setup."""
        return bool(
            shutil.which("node")
            and (ROOT / "pi-sidecar" / "src" / "server.mjs").is_file()
            and (ROOT / "pi-sidecar" / "node_modules").is_dir()
        )

    def health(self) -> Dict[str, Any]:
        client = PiSidecar(base_url=self._base_url)
        try:
            health = client.health()
            return {"ok": bool(health.get("ok")), **health}
        except Exception as exc:
            return {
                "ok": False,
                "enabled": self.enabled(),
                "error": str(exc)[:500],
            }

    def ensure_running(
        self, *, timeout: float = 8.0, provider: str = ""
    ) -> PiSidecar:
        if not self.enabled():
            raise RuntimeError("Pi executor is disabled")
        client = PiSidecar(base_url=self._base_url)
        if client.available():
            with self._lock:
                self._last_used = time.time()
            return client
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                node = shutil.which("node")
                entry = ROOT / "pi-sidecar" / "src" / "server.mjs"
                modules = ROOT / "pi-sidecar" / "node_modules"
                if not node or not entry.is_file() or not modules.is_dir():
                    raise RuntimeError(
                        "Pi sidecar is not installed; run setup for the optional Pi worker"
                    )
                child_env = _sidecar_env(provider)
                # A spawned sidecar gets a fresh bearer token so no other local
                # process can drive it or approve its own confirms — loopback
                # alone is not authentication. Publishing it in the hub env is
                # how default-constructed clients pick it up (PiSidecar reads
                # PI_SIDECAR_TOKEN); rau.agent.tools._shell_env strips it back
                # out of model-authored shells. A hand-started sidecar is
                # untouched, so the documented tokenless manual path still works.
                token = secrets.token_urlsafe(32)
                child_env["PI_SIDECAR_TOKEN"] = token
                os.environ["PI_SIDECAR_TOKEN"] = token
                configured_port = str(child_env.get("PI_SIDECAR_PORT") or "").strip()
                if configured_port:
                    port = int(configured_port)
                else:
                    # 8791 is intentionally only a default. Other companion
                    # apps commonly occupy nearby development ports; binding
                    # an ephemeral loopback port makes the supervised process
                    # private and removes a startup collision from every job.
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                        probe.bind(("127.0.0.1", 0))
                        port = int(probe.getsockname()[1])
                    child_env["PI_SIDECAR_PORT"] = str(port)
                self._base_url = f"http://127.0.0.1:{port}"
                self._process = subprocess.Popen(
                    [node, str(entry)],
                    cwd=str(ROOT / "pi-sidecar"),
                    env=child_env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                if not self._registered:
                    atexit.register(self.stop)
                    self._registered = True
        # Constructed after the spawn lock so the client picks up the token a
        # concurrent spawner may have just published in the environment.
        client = PiSidecar(base_url=self._base_url)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if client.available():
                with self._lock:
                    self._last_used = time.time()
                return client
            proc = self._process
            if proc is not None and proc.poll() is not None:
                break
            time.sleep(0.1)
        raise RuntimeError("Pi sidecar did not become healthy")

    def touch(self) -> None:
        with self._lock:
            self._last_used = time.time()

    def stop_if_idle(self, idle_sec: float = 300.0) -> bool:
        with self._lock:
            if not self._process or self._process.poll() is not None:
                return False
            if time.time() - self._last_used < idle_sec:
                return False
            # Decide and stop under the one lock (the RLock is reentrant here):
            # an ensure_running that lands between the check and the stop would
            # otherwise have its fresh sidecar killed from under it.
            self.stop()
            return True

    def stop(self) -> None:
        with self._lock:
            proc = self._process
            self._process = None
            self._base_url = DEFAULT_BASE_URL
        if proc is None or proc.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(proc.pid, signal.SIGTERM)
            else:
                proc.terminate()
            proc.wait(timeout=3.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


PI_SUPERVISOR = PiSupervisor()
