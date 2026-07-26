"""
Which browsing backend to use, and what to do when the chosen one cannot.

The user picks in Settings; `auto` picks for them. Unlike the STT registry
there is no always-available local fallback here — reading the web needs
someone's API key — so an unusable choice is reported honestly rather than
silently swapped, except in `auto`, which is the mode that exists precisely to
be swapped.
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

from rau.browse.base import BrowseError, BrowseProvider
from rau.browse import browserbase as browserbase_mod
from rau.browse import firecrawl as firecrawl_mod
from rau.env import has_secret
from rau.providers.registry import get_slot

#: provider id -> env var that must be present for it to work.
BROWSE_AUTH: Dict[str, str] = {
    "auto": "",
    "firecrawl": firecrawl_mod.ENV_KEY,
    "browserbase": browserbase_mod.ENV_KEY,
}

PROVIDER_IDS: Tuple[str, ...] = ("auto", "firecrawl", "browserbase")


def available_browse() -> Dict[str, bool]:
    """Which backends are usable right now, for the UI."""
    out = {
        pid: (True if not env else has_secret(env))
        for pid, env in BROWSE_AUTH.items()
        if pid != "auto"
    }
    # `auto` is only meaningful if it has something to choose between.
    out["auto"] = any(out.values())
    return out


def _best_available() -> str:
    # Firecrawl first: for the common case of "read me this page" it is faster
    # and cheaper, and Browserbase's advantage only shows on pages that need a
    # real browser.
    for provider in ("firecrawl", "browserbase"):
        if has_secret(BROWSE_AUTH[provider]):
            return provider
    return ""


def resolve_browse() -> Tuple[str, Dict[str, Any]]:
    """
    Resolve the configured slot to a provider id.

    Returns `("", slot)` when nothing is usable, so callers can say what is
    missing instead of raising from somewhere less informative.
    """
    slot = get_slot("browse")
    configured = str(slot.get("provider") or "auto").lower()
    provider = configured
    reason = ""

    if provider not in BROWSE_AUTH:
        reason = f"unknown backend {configured!r}"
        provider = "auto"
        configured = "auto"

    if provider == "auto":
        provider = _best_available()
        reason = reason or (
            f"automatic selection chose {provider}" if provider else "no key is configured"
        )
    else:
        env = BROWSE_AUTH.get(provider, "")
        if env and not has_secret(env):
            # A deliberate choice is not silently overridden: being told the
            # key is missing is more useful than quietly using the other one.
            reason = f"the {provider} key is not configured"
            provider = ""

    view = {
        **slot,
        "provider": provider,
        "configured": configured,
        "reason": reason,
        "can_search": provider == "firecrawl",
    }
    return provider, view


def build(provider: str) -> BrowseProvider:
    if provider == "firecrawl":
        return firecrawl_mod.FirecrawlBrowser()
    if provider == "browserbase":
        return browserbase_mod.BrowserbaseBrowser()
    raise BrowseError(
        "no web browsing backend is configured — add a Firecrawl or "
        "Browserbase key in Settings",
        code="no_provider",
    )


def get_browser() -> Tuple[str, BrowseProvider]:
    provider, view = resolve_browse()
    if not provider:
        raise BrowseError(
            view.get("reason")
            or "no web browsing backend is configured — add a Firecrawl or "
            "Browserbase key in Settings",
            code="no_provider",
        )
    return provider, build(provider)


def status() -> Dict[str, Any]:
    """What the Settings page shows."""
    provider, view = resolve_browse()
    return {
        "provider": provider,
        "configured": view.get("configured"),
        "reason": view.get("reason"),
        "can_search": bool(view.get("can_search")),
        "available": available_browse(),
        "ready": bool(provider),
    }
