"""Live credential checks — used by the setup wizard to prove a key works.

Every check is a cheap, read-only call against the provider. Nothing here
generates tokens or costs money beyond a listing request.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from rau.env import get_secret, slot_by_id

TIMEOUT = 20

# provider/auth slot id -> how to check it
_OPENAI_COMPAT_LIST: Dict[str, str] = {
    "openrouter": "https://openrouter.ai/api/v1/models",
    "deepseek": "https://api.deepseek.com/v1/models",
    "kimi": "https://api.moonshot.ai/v1/models",
    "codex": "https://api.openai.com/v1/models",
    "openai": "https://api.openai.com/v1/models",
}


def _get_json(url: str, headers: Dict[str, str]) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_json(url: str, headers: Dict[str, str], payload: Dict[str, Any]) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_error(e: urllib.error.HTTPError) -> str:
    body = ""
    try:
        body = e.read().decode("utf-8", errors="replace")[:300]
    except Exception:
        pass
    if e.code in (401, 403):
        return "Key rejected — check that you pasted the whole key."
    if e.code == 429:
        return "Key works but the provider is rate-limiting right now."
    if e.code == 402:
        return "Key works but the account has no credit."
    return f"HTTP {e.code}: {body or e.reason}"


def _model_ids(body: Dict[str, Any], limit: int = 400) -> List[str]:
    out: List[str] = []
    for item in body.get("data") or []:
        if isinstance(item, dict) and item.get("id"):
            out.append(str(item["id"]))
        if len(out) >= limit:
            break
    return out


def _verify_openai_compat(slot_id: str, key: str) -> Dict[str, Any]:
    url = _OPENAI_COMPAT_LIST[slot_id]
    body = _get_json(url, {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    ids = _model_ids(body)
    return {
        "ok": True,
        "detail": f"{len(ids)} models reachable" if ids else "authenticated",
        "models": ids,
    }


def _verify_kimi_code(key: str) -> Dict[str, Any]:
    # Anthropic-compatible: no /models listing, so send the smallest possible turn.
    body = _post_json(
        "https://api.kimi.com/coding/v1/messages",
        {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        {
            "model": "kimi-for-coding",
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    return {"ok": True, "detail": f"responded as {body.get('model') or 'kimi-for-coding'}", "models": []}


def _verify_elevenlabs(key: str) -> Dict[str, Any]:
    body = _get_json("https://api.elevenlabs.io/v1/user", {"xi-api-key": key})
    voices = _get_json(
        "https://api.elevenlabs.io/v2/voices?page_size=1&include_total_count=true",
        {"xi-api-key": key},
    )
    sub = body.get("subscription") or {}
    used = sub.get("character_count")
    cap = sub.get("character_limit")
    tier = sub.get("tier") or "free"
    if isinstance(used, int) and isinstance(cap, int) and cap:
        detail = f"{tier} tier — {cap - used:,} characters left"
    else:
        detail = f"{tier} tier"
    total_voices = voices.get("total_count")
    if isinstance(total_voices, int):
        detail += f" · {total_voices} voices available"
    return {"ok": True, "detail": detail, "models": []}


def _verify_composio(key: str) -> Dict[str, Any]:
    # Composio's API surface moves around; treat a saved key as configured and
    # let the Connect flow report the real state.
    if len(key) < 8:
        return {"ok": False, "detail": "That looks too short to be a Composio key."}
    return {
        "ok": True,
        "detail": "Key saved. Finish app authorization in Composio Connect.",
        "models": [],
        "soft": True,
    }


def verify(slot_id: str, key: Optional[str] = None) -> Dict[str, Any]:
    """Check a credential. Uses the stored key when `key` is not supplied."""
    slot = slot_by_id(slot_id)
    if not slot:
        return {"ok": False, "provider": slot_id, "detail": "Unknown provider."}

    secret = (key or "").strip() or get_secret(slot["env"])
    if not secret:
        return {"ok": False, "provider": slot_id, "detail": "No key saved yet."}

    try:
        if slot_id in _OPENAI_COMPAT_LIST:
            result = _verify_openai_compat(slot_id, secret)
        elif slot_id == "kimi_code":
            result = _verify_kimi_code(secret)
        elif slot_id == "elevenlabs":
            result = _verify_elevenlabs(secret)
        elif slot_id == "deepgram":
            from rau.voice.stt.deepgram import probe_key

            result = probe_key(secret)
            if not result.get("ok"):
                return {"provider": slot_id, **result}
        elif slot_id == "composio":
            result = _verify_composio(secret)
        else:
            return {"ok": False, "provider": slot_id, "detail": "No check available for this provider."}
    except urllib.error.HTTPError as e:
        return {"ok": False, "provider": slot_id, "detail": _http_error(e)}
    except urllib.error.URLError as e:
        return {"ok": False, "provider": slot_id, "detail": f"Could not reach provider: {e.reason}"}
    except Exception as e:  # noqa: BLE001 — surface anything unexpected to the UI
        return {"ok": False, "provider": slot_id, "detail": str(e)}

    return {"provider": slot_id, **result}
