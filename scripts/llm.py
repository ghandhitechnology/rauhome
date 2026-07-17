#!/usr/bin/env python3
"""WALL-E LLM Backend — DeepSeek v4 Flash API.
All local Ollama tiers removed. Every request goes to DeepSeek cloud.
"""
import json
import os
import re
import time
import urllib.request
from pathlib import Path
from typing import Tuple, Optional

PROJECT_ROOT = Path(__file__).parent.parent
SYSTEM_PROMPT = PROJECT_ROOT / "prompts" / "system-prompt.md"

DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1/chat/completions"


def _clean_rocky(text: str) -> str:
    """Strip asterisk-wrapped spans (e.g. *Blip-A* -> Blip-A) and stray pairs."""
    cleaned = re.sub(r'\*([^\*\n]{1,80}?)\*', r'\1', text)
    cleaned = re.sub(r'\*+', '', cleaned)
    return cleaned


def _load_api_key():
    """Load DeepSeek API key from .env or DEEPSEEK_API_KEY env var."""
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        env_file = PROJECT_ROOT / ".env"
        if env_file.exists():
            for line in open(env_file):
                line = line.strip()
                if line.startswith("DEEPSEEK_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip("'").strip("'")
                    break
    return key

DEEPSEEK_API_KEY = _load_api_key()

if not DEEPSEEK_API_KEY:
    print("⚠️  DEEPSEEK_API_KEY not found — WALL-E cannot speak!")


class WalleLLM:
    """DeepSeek v4 Flash backend for WALL-E."""

    def __init__(self, backend: str = "deepseek"):
        self.backend = backend
        with open(SYSTEM_PROMPT) as f:
            self.system = f.read()

    def chat(self, text: str) -> str:
        """Non-streaming chat."""
        return self._deepseek(text)

    def chat_stream(self, text: str):
        """Streaming chat — yields (token, is_done)."""
        yield from self._deepseek_stream(text)

    def _deepseek(self, text: str) -> str:
        """DeepSeek v4 Flash non-streaming."""
        if not DEEPSEEK_API_KEY:
            raise RuntimeError("DEEPSEEK_API_KEY not set")

        payload = {
            "model": DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": self.system},
                {"role": "user", "content": text},
            ],
            "max_tokens": 60,
            "temperature": 0.9,
        }
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            DEEPSEEK_BASE_URL,
            data=data,
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
        )
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read())
        return _clean_rocky(result["choices"][0]["message"]["content"])

    def _deepseek_stream(self, text: str):
        """DeepSeek v4 Flash streaming."""
        if not DEEPSEEK_API_KEY:
            raise RuntimeError("DEEPSEEK_API_KEY not set")

        payload = {
            "model": DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": self.system},
                {"role": "user", "content": text},
            ],
            "stream": True,
            "max_tokens": 60,
            "temperature": 0.9,
        }
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            DEEPSEEK_BASE_URL,
            data=data,
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
        )
        resp = urllib.request.urlopen(req, timeout=30)

        buffer = b""
        while True:
            chunk = resp.read(4096)
            if not chunk:
                break
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                line = line.decode().strip()
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    yield "", True
                    return
                try:
                    c = json.loads(data_str)
                    token = c["choices"][0].get("delta", {}).get("content", "")
                    if token:
                        yield token, False
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue


def extract_emotion(response: str) -> Tuple[str, Optional[str]]:
    match = re.search(
        r"\[(HAPPY|CURIOUS|EXCITED|SAD|COMPACT|SCARED|AMAZED|LOVE|DETERMINED)\]",
        response
    )
    if match:
        tag = f"[{match.group(1)}]"
        clean = response.replace(tag, "").strip()
        return clean, tag
    return response, None


# ===================== BENCHMARK =====================
if __name__ == "__main__":
    import sys

    llm = WalleLLM()
    test_messages = [
        "Hello WALL-E!",
        "What's your directive?",
    ]

    print(f"=== WALL-E LLM BENCHMARK: DeepSeek v4 Flash ===\n")

    for msg in test_messages:
        t0 = time.perf_counter()
        first = None
        full = ""
        tokens = 0

        for token, done in llm.chat_stream(msg):
            if token and first is None:
                first = (time.perf_counter() - t0) * 1000
            if token:
                tokens += 1
                full += token

        total = (time.perf_counter() - t0) * 1000
        clean, emotion = extract_emotion(full)
        gen = total - (first or 0)

        print(f"🧑 {msg}")
        print(f"🤖 {clean[:70]}... {emotion or ''}")
        print(f"   TTFT:{first:.0f}ms Gen:{gen:.0f}ms Total:{total:.0f}ms ({tokens}tok)")
        print()