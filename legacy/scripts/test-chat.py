#!/usr/bin/env python3
"""Test WALL-E character chat via Ollama."""
import subprocess
import json
import sys
from pathlib import Path

SYSTEM_PROMPT_FILE = Path(__file__).parent.parent / "prompts" / "system-prompt.md"
MODEL = "gemma3:4b"  # 3.3GB — 5GB saved vs 12b


def load_system_prompt() -> str:
    with open(SYSTEM_PROMPT_FILE) as f:
        return f.read()


def chat(message: str) -> str:
    system = load_system_prompt()
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": message},
        ],
        "stream": False,
        "options": {"temperature": 0.9, "top_p": 0.95},
    }
    result = subprocess.run(
        ["curl", "-s", "http://127.0.0.1:11434/api/chat", "-d", json.dumps(payload)],
        capture_output=True,
        text=True,
    )
    data = json.loads(result.stdout)
    return data.get("message", {}).get("content", "[no response]")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        msg = " ".join(sys.argv[1:])
    else:
        msg = "Hello WALL-E!"
    print(f"\n🧑 You: {msg}\n")
    response = chat(msg)
    print(f"🤖 WALL-E: {response}\n")
