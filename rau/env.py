"""Load .env and environment secrets."""
from __future__ import annotations

import os
import re
import tempfile
import threading
from typing import Dict, List, Optional

from rau.paths import ENV_FILE, ensure_dirs

_env_lock = threading.RLock()

# Known auth slots shown in the UI
AUTH_SLOTS: List[Dict[str, str]] = [
    {
        "id": "openrouter",
        "label": "OpenRouter",
        "env": "OPENROUTER_API_KEY",
        "docs_url": "https://openrouter.ai/keys",
        "help": "Unified router for many models. Create a key, paste it here.",
    },
    {
        "id": "deepseek",
        "label": "DeepSeek",
        "env": "DEEPSEEK_API_KEY",
        "docs_url": "https://platform.deepseek.com/api_keys",
        "help": "DeepSeek chat API key.",
    },
    {
        "id": "kimi",
        "label": "Kimi / Moonshot",
        "env": "KIMI_API_KEY",
        "docs_url": "https://platform.moonshot.ai/console/api-keys",
        "help": "Moonshot Kimi Platform (pay-as-you-go). Base: api.moonshot.ai",
    },
    {
        "id": "kimi_code",
        "label": "Kimi Coding Plan",
        "env": "KIMI_CODING_API_KEY",
        "docs_url": "https://www.kimi.com/code/docs/en/",
        "connect_url": "https://www.kimi.com/code",
        "help": "Kimi Code membership key (separate from Moonshot). Models: kimi-for-coding, k3, k3-256k.",
    },
    {
        "id": "codex",
        "label": "OpenAI / Codex",
        "env": "OPENAI_API_KEY",
        "docs_url": "https://platform.openai.com/api-keys",
        "help": "OpenAI API key (Codex / GPT providers).",
    },
    {
        "id": "elevenlabs",
        "label": "ElevenLabs",
        "env": "ELEVENLABS_API_KEY",
        "docs_url": "https://elevenlabs.io/app/settings/api-keys",
        "help": "Text-to-speech and optional Scribe speech-to-text.",
    },
    {
        "id": "cartesia",
        "label": "Cartesia",
        "env": "CARTESIA_API_KEY",
        "docs_url": "https://play.cartesia.ai/keys",
        "help": "Low-latency Sonic 3.5 text-to-speech.",
    },
    {
        "id": "deepgram",
        "label": "Deepgram",
        "env": "DEEPGRAM_API_KEY",
        "docs_url": "https://console.deepgram.com/signup",
        "help": "Streaming speech-to-text for voice mode. The only backend with a live transcript.",
    },
    {
        "id": "firecrawl",
        "label": "Firecrawl",
        "env": "FIRECRAWL_API_KEY",
        "docs_url": "https://www.firecrawl.dev/app/api-keys",
        "help": "Reads a page and hands back clean markdown. Fast, cheap, and the only one that can search.",
    },
    {
        "id": "browserbase",
        "label": "Browserbase",
        "env": "BROWSERBASE_API_KEY",
        "docs_url": "https://www.browserbase.com/settings",
        "help": "A real browser in the cloud. Slower, but it runs the page's JavaScript — use it for apps that ship an empty page.",
    },
    {
        "id": "composio",
        "label": "Composio",
        "env": "COMPOSIO_API_KEY",
        "docs_url": "https://app.composio.dev",
        "connect_url": "https://connect.composio.dev",
        "help": "App actions via MCP. Save the API key, then open Connect to authorize apps.",
    },
]


def load_dotenv(*, override: bool = False) -> None:
    with _env_lock:
        if not ENV_FILE.exists():
            return
        for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if not key:
                continue
            if override or key not in os.environ:
                os.environ[key] = val


def get_secret(name: str, default: str = "") -> str:
    load_dotenv()
    return os.environ.get(name, default) or default


def has_secret(name: str) -> bool:
    return bool(get_secret(name))


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "••••"
    return f"{value[:3]}…{value[-4:]}"


def _read_env_map() -> Dict[str, str]:
    data: Dict[str, str] = {}
    if not ENV_FILE.exists():
        return data
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        data[key.strip()] = val.strip().strip('"').strip("'")
    return data


def _write_env_map(data: Dict[str, str], *, remove: Optional[set] = None) -> None:
    ensure_dirs()
    remove = remove or set()
    existing_lines: List[str] = []
    if ENV_FILE.exists():
        existing_lines = ENV_FILE.read_text(encoding="utf-8").splitlines()

    seen = set()
    out: List[str] = []
    for raw in existing_lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out.append(raw)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in remove:
            continue
        if key in data:
            out.append(f"{key}={data[key]}")
            seen.add(key)
        else:
            out.append(raw)
    for key, val in data.items():
        if key not in seen and key not in remove:
            out.append(f"{key}={val}")

    value = "\n".join(out).rstrip() + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=".env.", suffix=".tmp", dir=ENV_FILE.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, ENV_FILE)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def set_secret(name: str, value: str) -> Dict[str, object]:
    name = name.strip()
    value = value.strip()
    if not name or not re.match(r"^[A-Z][A-Z0-9_]*$", name):
        raise ValueError("invalid secret name")
    if not value:
        raise ValueError("empty secret")
    if len(value) > 20_000:
        raise ValueError("secret is too long")
    if re.search(r"[\x00-\x1f\x7f]", value):
        raise ValueError("secret contains control characters")
    with _env_lock:
        data = _read_env_map()
        data[name] = value
        _write_env_map(data)
        os.environ[name] = value
        return {"env": name, "configured": True, "masked": _mask(value)}


def clear_secret(name: str) -> Dict[str, object]:
    name = name.strip()
    with _env_lock:
        data = _read_env_map()
        data.pop(name, None)
        _write_env_map(data, remove={name})
        os.environ.pop(name, None)
        return {"env": name, "configured": False, "masked": ""}


def auth_status() -> List[Dict[str, object]]:
    load_dotenv()
    out: List[Dict[str, object]] = []
    for slot in AUTH_SLOTS:
        env = slot["env"]
        val = get_secret(env)
        item: Dict[str, object] = {
            **slot,
            "configured": bool(val),
            "masked": _mask(val),
        }
        out.append(item)
    return out


def slot_by_id(slot_id: str) -> Optional[Dict[str, str]]:
    for slot in AUTH_SLOTS:
        if slot["id"] == slot_id:
            return slot
    return None
