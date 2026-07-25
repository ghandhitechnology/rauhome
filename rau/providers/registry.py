"""Model config + provider registry with hot-swap."""
from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import threading
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional

from rau.env import has_secret
from rau.paths import MODELS_CONFIG, SETTINGS_CONFIG, ensure_dirs
from rau.providers.base import ChatProvider
from rau.providers.openai_compat import PROVIDERS

_lock = threading.RLock()
_models: Dict[str, Any] = {}
_settings: Dict[str, Any] = {}
log = logging.getLogger("rau.providers.registry")


EFFORT_LEVELS = ("low", "medium", "high", "max")
CHAT_SLOTS = ("face", "subagent", "dream")


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


def _default_settings() -> Dict[str, Any]:
    return {
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


class _InvalidConfig(ValueError):
    pass


def _read_object(path: Path) -> Dict[str, Any]:
    # OSError is deliberately allowed to escape: a transient permission, fd,
    # or disk failure must never be mistaken for corrupt data and overwritten.
    raw = path.read_text(encoding="utf-8")
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise _InvalidConfig(f"invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise _InvalidConfig("top-level value must be a JSON object")
    return value


def _quarantine(path: Path) -> Optional[Path]:
    if not path.exists():
        return None
    target = path.with_name(f"{path.name}.bad-{time.time_ns()}")
    try:
        os.replace(path, target)
    except OSError as exc:
        log.error("could not quarantine invalid %s: %s", path, exc)
        return None
    log.error("moved invalid config %s to %s", path, target)
    return target


def _atomic_json(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _validated_models(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Validate executable chat-slot selections before they reach a worker."""
    if not isinstance(cfg, dict):
        raise ValueError("model config must be an object")
    checked = deepcopy(cfg)
    for slot_name in CHAT_SLOTS:
        slot = checked.get(slot_name)
        if not isinstance(slot, dict):
            raise ValueError(f"{slot_name} model slot must be an object")
        provider = slot.get("provider")
        model = slot.get("model")
        if not isinstance(provider, str) or provider not in PROVIDERS:
            raise ValueError(f"{slot_name} has unknown provider: {provider!r}")
        if (
            not isinstance(model, str)
            or not model.strip()
            or len(model) > 300
            or any(char in model for char in "\0\r\n")
        ):
            raise ValueError(f"{slot_name} model id is invalid")

        max_tokens = slot.get("max_tokens")
        if (
            isinstance(max_tokens, bool)
            or not isinstance(max_tokens, int)
            or not 1 <= max_tokens <= 131_072
        ):
            raise ValueError(
                f"{slot_name}.max_tokens must be an integer between 1 and 131072"
            )
        temperature = slot.get("temperature")
        if (
            isinstance(temperature, bool)
            or not isinstance(temperature, (int, float))
            or not math.isfinite(float(temperature))
            or not 0 <= float(temperature) <= 2
        ):
            raise ValueError(f"{slot_name}.temperature must be between 0 and 2")
        effort = slot.get("effort")
        if effort not in EFFORT_LEVELS:
            raise ValueError(
                f"{slot_name}.effort must be one of {', '.join(EFFORT_LEVELS)}"
            )
    return checked


def load_models() -> Dict[str, Any]:
    global _models
    ensure_dirs()
    with _lock:
        loaded: Optional[Dict[str, Any]] = None
        invalid = False
        if MODELS_CONFIG.exists():
            try:
                loaded = _read_object(MODELS_CONFIG)
            except OSError as exc:
                log.error("cannot read %s; using in-memory defaults without overwriting: %s", MODELS_CONFIG, exc)
                _models = _default_models()
                return deepcopy(_models)
            except _InvalidConfig as exc:
                log.error("cannot parse %s; using safe defaults: %s", MODELS_CONFIG, exc)
                invalid = True
                _quarantine(MODELS_CONFIG)
        _models = loaded if loaded is not None else _default_models()
        # Backfill slots added after this config was written — an existing
        # install would otherwise never see a newly introduced slot (stt).
        defaults = _default_models()
        missing = {k: v for k, v in defaults.items() if k not in _models}
        _models.update(deepcopy(missing))
        repaired = loaded is None or bool(missing)
        for slot_name, slot_defaults in defaults.items():
            current = _models.get(slot_name)
            if not isinstance(current, dict):
                continue
            for key, default in slot_defaults.items():
                if key not in current:
                    current[key] = deepcopy(default)
                    repaired = True
        try:
            _models = _validated_models(_models)
        except ValueError as exc:
            log.error("invalid model selection; using safe defaults: %s", exc)
            if loaded is not None:
                invalid = True
                _quarantine(MODELS_CONFIG)
            _models = _default_models()
            repaired = True
        if repaired or invalid:
            save_models(_models)
        return deepcopy(_models)


def save_models(cfg: Dict[str, Any]) -> Dict[str, Any]:
    global _models
    checked = _validated_models(cfg)
    ensure_dirs()
    with _lock:
        _models = checked
        _atomic_json(MODELS_CONFIG, _models)
        return deepcopy(_models)


def load_settings() -> Dict[str, Any]:
    global _settings
    ensure_dirs()
    with _lock:
        defaults = _default_settings()
        loaded: Optional[Dict[str, Any]] = None
        if SETTINGS_CONFIG.exists():
            try:
                loaded = _read_object(SETTINGS_CONFIG)
            except (OSError, _InvalidConfig) as exc:
                log.error("cannot read %s; using safe defaults: %s", SETTINGS_CONFIG, exc)
        _settings = {**defaults, **(loaded or {})}
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
