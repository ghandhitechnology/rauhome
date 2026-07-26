"""
ElevenLabs Scribe STT.

Worth having as the default: if the user set up voice at all they already have
an ELEVENLABS_API_KEY for TTS, so this gives working speech-to-text with no
additional signup. Accurate, but request/response — no live partials.
"""
from __future__ import annotations

import json
import mimetypes
import urllib.error
import urllib.request
import uuid

from rau.env import get_secret
from rau.voice.stt.buffered import BufferedStt, pcm_to_wav

URL = "https://api.elevenlabs.io/v1/speech-to-text"


def _multipart(fields: dict, filename: str, payload: bytes) -> tuple[bytes, str]:
    """Build a multipart/form-data body — Scribe does not accept raw JSON."""
    boundary = f"----rau{uuid.uuid4().hex}"
    out = bytearray()
    for key, value in fields.items():
        if value is None:
            continue
        out += f"--{boundary}\r\n".encode()
        out += f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode()
        out += f"{value}\r\n".encode()
    ctype = mimetypes.guess_type(filename)[0] or "audio/wav"
    out += f"--{boundary}\r\n".encode()
    out += (
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {ctype}\r\n\r\n"
    ).encode()
    out += payload
    out += f"\r\n--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


_LANGUAGE_ALIASES = {
    "en": "eng",
    "ko": "kor",
    "ja": "jpn",
    "zh": "zho",
    "es": "spa",
    "fr": "fra",
    "de": "deu",
    "it": "ita",
    "pt": "por",
    "ru": "rus",
    "hi": "hin",
}


class ScribeStt(BufferedStt):
    name = "elevenlabs"

    def __init__(self, model: str = "scribe_v2", language: str = ""):
        self.model = model or "scribe_v2"
        raw_language = (language or "").strip().lower()
        # Scribe uses ISO-639-3 while the rest of Rau's settings use the more
        # familiar two-letter code. Unknown two-letter values are omitted so
        # Scribe can detect the language instead of rejecting the request.
        self.language = _LANGUAGE_ALIASES.get(
            raw_language, raw_language if len(raw_language) == 3 else ""
        )

    def transcribe(self, pcm: bytes) -> str:
        key = get_secret("ELEVENLABS_API_KEY")
        if not key:
            raise RuntimeError("ELEVENLABS_API_KEY not set")

        body, content_type = _multipart(
            {
                "model_id": self.model,
                "language_code": self.language or None,
            },
            "speech.wav",
            pcm_to_wav(pcm),
        )
        req = urllib.request.Request(
            URL,
            data=body,
            headers={"xi-api-key": key, "Content-Type": content_type},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:200]
            raise RuntimeError(f"Scribe HTTP {e.code}: {detail}") from e
        return data.get("text") or ""
