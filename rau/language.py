"""One persisted response language across Rau's conversational surfaces."""
from __future__ import annotations

from typing import Any, Dict

from rau.providers.registry import load_settings, save_settings

DEFAULT_LOCALE = "en"
SUPPORTED_LOCALES = {"en", "ko"}


def normalize_locale(value: object) -> str:
    locale = str(value or "").strip().lower()
    return locale if locale in SUPPORTED_LOCALES else DEFAULT_LOCALE


def get_locale() -> str:
    return normalize_locale(load_settings().get("language"))


def set_locale(locale: object) -> Dict[str, Any]:
    normalized = normalize_locale(locale)
    settings = load_settings()
    settings["language"] = normalized
    save_settings(settings)
    return {"language": normalized}


def response_language_instruction() -> str:
    """Hard steering for anything Rau says directly to the user."""
    if get_locale() == "ko":
        return (
            "## Response language\n"
            "Always speak and reply in natural Korean. Keep names, code, commands, "
            "file paths, and literal quotations unchanged when accuracy requires it. "
            "Do not switch to English unless the user changes the language setting."
        )
    return (
        "## Response language\n"
        "Always speak and reply in natural English. Keep names, code, commands, "
        "file paths, and literal quotations unchanged when accuracy requires it. "
        "Do not switch to Korean unless the user changes the language setting."
    )
