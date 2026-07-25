"""Model config + provider registry with hot-swap."""
from __future__ import annotations

import json
import threading
from copy import deepcopy
from typing import Any, Dict, Optional

from rau.env import has_secret
from rau.paths import MODELS_CONFIG, SETTINGS_CONFIG, ensure_dirs
from rau.providers.base import ChatProvider
from rau.providers.openai_compat import PROVIDERS

_lock = threading.RLock()
_models: Dict[str, Any] = {}
_settings: Dict[str, Any] = {}


EFFORT_LEVELS = ("low", "medium", "high", "max")


def _default_models() -> Dict[str, Any]:
    return {
        "face": {
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "max_tokens": 512,
            "temperature": 0.9,
            "effort": "medium",
        },
        "subagent": {
            "provider": "openrouter",
            "model": "openai/gpt-5.6-sol",
            "max_tokens": 4096,
            "temperature": 0.3,
            "effort": "high",
        },
        "dream": {
            "provider": "openrouter",
            "model": "deepseek/deepseek-v4-flash",
            "max_tokens": 2048,
            "temperature": 0.5,
            "effort": "medium",
        },
        "tts": {
            "provider": "elevenlabs",
            "voice_id": "TX3LPaxmHKxFdv7VOQHJ",
            "model": "eleven_flash_v2_5",
        },
        # Speech-to-text for voice mode. Defaults to local whisper because it
        # needs no credential; the registry upgrades to whatever the user
        # configures and falls back here if that key goes missing.
        "stt": {
            "provider": "local",
            "model": "small",
            "language": "",
        },
    }


def load_models() -> Dict[str, Any]:
    global _models
    ensure_dirs()
    with _lock:
        if MODELS_CONFIG.exists():
            _models = json.loads(MODELS_CONFIG.read_text(encoding="utf-8"))
            # Backfill slots added after this config was written — an existing
            # install would otherwise never see a newly introduced slot (stt).
            defaults = _default_models()
            missing = {k: v for k, v in defaults.items() if k not in _models}
            if missing:
                _models.update(deepcopy(missing))
                save_models(_models)
        else:
            _models = _default_models()
            save_models(_models)
        return deepcopy(_models)


def save_models(cfg: Dict[str, Any]) -> Dict[str, Any]:
    global _models
    ensure_dirs()
    with _lock:
        _models = deepcopy(cfg)
        MODELS_CONFIG.write_text(
            json.dumps(_models, indent=2) + "\n", encoding="utf-8"
        )
        return deepcopy(_models)


def load_settings() -> Dict[str, Any]:
    global _settings
    ensure_dirs()
    with _lock:
        if SETTINGS_CONFIG.exists():
            _settings = json.loads(SETTINGS_CONFIG.read_text(encoding="utf-8"))
        else:
            _settings = {
                "hub_host": "127.0.0.1",
                "hub_port": 8765,
                "dream_window_start": "02:00",
                "dream_window_end": "05:00",
                "confirm_timeout_sec": 45,
                "presence_backoff_after_misses": 2,
                "hard_task_progress_interval_sec": 25,
                "trace_ttl_days": 7,
                "face_history_turns": 24,
            }
        return deepcopy(_settings)


def get_slot(slot: str) -> Dict[str, Any]:
    cfg = load_models()
    return dict(cfg.get(slot) or {})


def get_provider(name: str) -> ChatProvider:
    prov = PROVIDERS.get(name)
    if not prov:
        raise KeyError(f"Unknown provider: {name}")
    return prov


def provider_status() -> Dict[str, Any]:
    env_map = {
        "openrouter": "OPENROUTER_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "kimi": "KIMI_API_KEY",
        "moonshot": "KIMI_API_KEY",
        "kimi_code": "KIMI_CODING_API_KEY",
        "kimi-code": "KIMI_CODING_API_KEY",
        "kimi_coding": "KIMI_CODING_API_KEY",
        "codex": "OPENAI_API_KEY",
        "openai": "OPENAI_API_KEY",
        "elevenlabs": "ELEVENLABS_API_KEY",
        "composio": "COMPOSIO_API_KEY",
    }
    return {
        name: {"configured": has_secret(env), "env": env}
        for name, env in env_map.items()
    }


def chat_for_slot(slot: str):
    slot_cfg = get_slot(slot)
    provider_name = slot_cfg.get("provider") or "openrouter"
    provider = get_provider(provider_name)
    return provider, slot_cfg
