"""Server-only Cartesia Sonic voice discovery and streaming helpers."""
from __future__ import annotations

import threading
from importlib.util import find_spec
from typing import Any, Dict, Iterator, List, Optional

import httpx

from rau.env import get_secret

API_BASE = "https://api.cartesia.ai"
API_VERSION = "2026-03-01"
DEFAULT_MODEL = "sonic-3.5"

_http_client: Optional[httpx.Client] = None
_http_client_key = ""
_http_lock = threading.Lock()


def _headers(key: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {key}",
        "Cartesia-Version": API_VERSION,
        "Accept": "application/json",
    }


def _client() -> httpx.Client:
    """Reuse HTTP/2 connections, replacing the client after a key change."""
    global _http_client, _http_client_key
    key = get_secret("CARTESIA_API_KEY")
    if not key:
        raise RuntimeError("Connect a Cartesia API key first.")
    with _http_lock:
        if _http_client is None or _http_client_key != key:
            if _http_client is not None:
                _http_client.close()
            # HTTP/2 reduces connection overhead when the optional `h2`
            # package is present. Existing Rau environments may have plain
            # httpx installed, though, and voice discovery must still work
            # over HTTP/1.1 instead of failing during client construction.
            _http_client = httpx.Client(
                base_url=API_BASE,
                headers=_headers(key),
                http2=find_spec("h2") is not None,
                timeout=httpx.Timeout(30.0, connect=6.0),
            )
            _http_client_key = key
        return _http_client


def list_voices() -> List[Dict[str, Any]]:
    """Return public and account voices in the UI's provider-neutral shape."""
    output: List[Dict[str, Any]] = []
    starting_after = ""
    # Two pages avoids an unbounded provider-controlled loop while still
    # covering substantially more voices than a normal picker needs.
    for _ in range(2):
        params: Dict[str, Any] = {"limit": 100}
        if starting_after:
            params["starting_after"] = starting_after
        response = _client().get("/voices", params=params)
        response.raise_for_status()
        body = response.json()
        rows = body.get("data") or []
        if not isinstance(rows, list):
            raise RuntimeError("Cartesia returned an invalid voice list.")
        for voice in rows:
            if not isinstance(voice, dict):
                continue
            voice_id = str(voice.get("id") or "")
            name = str(voice.get("name") or "")
            if not voice_id or not name:
                continue
            labels = {
                key: str(voice.get(key))
                for key in ("gender", "language", "country")
                if voice.get(key)
            }
            output.append(
                {
                    "id": voice_id,
                    "label": name,
                    "category": "owned" if voice.get("is_owner") else "public",
                    "description": str(voice.get("description") or "")[:500],
                    "labels": labels,
                }
            )
        if not body.get("has_more") or not rows:
            break
        # The API documents `starting_after` as the final voice ID from the
        # previous page; do not assume the separate `next_page` display value
        # is accepted as that query parameter.
        starting_after = str(rows[-1].get("id") or "")
        if not starting_after:
            break
    output.sort(
        key=lambda item: (
            item["category"] != "owned",
            str(item["label"]).casefold(),
        )
    )
    return output


def stream_audio(
    *,
    text: str,
    voice_id: str,
    model: str = DEFAULT_MODEL,
    speed: float = 1.0,
) -> Iterator[bytes]:
    """Yield raw PCM16 mono 24 kHz from Cartesia's streaming bytes endpoint."""
    payload = {
        "model_id": model or DEFAULT_MODEL,
        "transcript": text,
        "voice": {"id": voice_id},
        "output_format": {
            "container": "raw",
            "encoding": "pcm_s16le",
            "sample_rate": 24000,
        },
        "generation_config": {"speed": float(speed)},
    }
    with _client().stream("POST", "/tts/bytes", json=payload) as response:
        response.raise_for_status()
        pending = b""
        for chunk in response.iter_bytes():
            data = pending + chunk
            even = len(data) & ~1
            if even:
                yield data[:even]
            pending = data[even:]
        if pending:
            raise RuntimeError("Cartesia returned incomplete PCM16 audio.")


__all__ = [
    "API_VERSION",
    "DEFAULT_MODEL",
    "list_voices",
    "stream_audio",
]
