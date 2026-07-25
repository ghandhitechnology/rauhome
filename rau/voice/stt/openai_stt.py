"""
OpenAI speech-to-text.

Reuses the OPENAI_API_KEY already wired as the 'codex' auth slot, so there is
nothing new to configure if that provider is set up.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from rau.env import get_secret
from rau.voice.stt.buffered import BufferedStt, pcm_to_wav
from rau.voice.stt.elevenlabs_scribe import _multipart

URL = "https://api.openai.com/v1/audio/transcriptions"


class OpenAiStt(BufferedStt):
    name = "openai"

    def __init__(self, model: str = "gpt-4o-transcribe", language: str = ""):
        self.model = model or "gpt-4o-transcribe"
        self.language = language or ""

    def transcribe(self, pcm: bytes) -> str:
        key = get_secret("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY not set")

        body, content_type = _multipart(
            {
                "model": self.model,
                "language": self.language or None,
                "response_format": "json",
            },
            "speech.wav",
            pcm_to_wav(pcm),
        )
        req = urllib.request.Request(
            URL,
            data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": content_type},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:200]
            raise RuntimeError(f"OpenAI STT HTTP {e.code}: {detail}") from e
        return data.get("text") or ""
