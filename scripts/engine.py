#!/usr/bin/env python3
"""WALL-E Response Engine — DeepSeek v4 Flash only.
All local Ollama tiers (1B, 4B) removed. Every request goes to DeepSeek cloud.
Keyword cache (Tier 1) retained for instant responses.
"""
import json, re, time, subprocess, wave, io, tempfile, os
from pathlib import Path
from typing import Optional, Tuple
import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent

# ===================== TIER 1: KEYWORD CACHE =====================
TRIGGERS = {
    "trash": ("*compacting noise* Directive! *determined beep*", "COMPACT", "compacting.wav"),
    "garbage": ("*compacting noise* Directive! *determined beep*", "COMPACT", "compacting.wav"),
    "쓰레기": ("*compacting noise* Directive! *determined beep*", "COMPACT", "compacting.wav"),
    "eva": ("*sad whir* EVA...? *holds out hand*", "LOVE", "eva_sigh.wav"),
    "에바": ("*sad whir* EVA...? *holds out hand*", "LOVE", "eva_sigh.wav"),
    "plant": ("*amazed whir* Whoa... *happy trill* Ta-da!", "AMAZED", "whoa.wav"),
    "식물": ("*amazed whir* Whoa... *happy trill* Ta-da!", "AMAZED", "whoa.wav"),
    "treasure": ("*whirrr* Ta-da! *shows bubble wrap* Pop-pop-pop!", "HAPPY", "curious_beep.wav"),
    "보물": ("*whirrr* Ta-da! *shows bubble wrap* Pop-pop-pop!", "HAPPY", "curious_beep.wav"),
    "hal": ("*whirrr* Hal? *happy trill*", "LOVE", "curious_beep.wav"),
    "cockroach": ("*whirrr* Hal? *happy trill*", "LOVE", "curious_beep.wav"),
    "fire": ("*flick* Whoa... *amazed whir*", "AMAZED", "whoa.wav"),
    "lighter": ("*flick* Whoa... *amazed whir*", "AMAZED", "whoa.wav"),
    "bubble": ("Pop-pop-pop! *happy trill*", "HAPPY", "curious_beep.wav"),
    "dolly": ("*holds up VHS tape* ...Hello, Dolly! *happy trill*", "LOVE", "curious_beep.wav"),
    "spork": ("Ta-da! *shows spork* Fork AND spoon!", "HAPPY", "curious_beep.wav"),
    "rubik": ("*click-click* *confused beep* *head tilt*", "CURIOUS", "curious_beep.wav"),
    "directive": ("*compacting noise* Directive! *determined beep*", "COMPACT", "compacting.wav"),
    "thank": ("*shy beep* *looks down* *happy trill*", "HAPPY", "curious_beep.wav"),
    "고마워": ("*shy beep* *looks down* *happy trill*", "HAPPY", "curious_beep.wav"),
}


def tier1_keyword(text: str) -> Optional[dict]:
    """Instant keyword match → pre-rendered response. <1ms."""
    lower = text.lower()
    for kw, (response, emotion, sfx) in TRIGGERS.items():
        if kw in lower:
            return {"tier": 1, "response": response, "emotion": emotion, "sfx": sfx, "latency_ms": 0}
    return None


# ===================== TIER 2: DEEPSEEK CLOUD (v4 Flash) =====================
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1/chat/completions"
SYSTEM_PROMPT = PROJECT_ROOT / "prompts" / "system-prompt-short.md"


def _get_api_key():
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        env_file = PROJECT_ROOT / ".env"
        if env_file.exists():
            for line in open(env_file):
                if line.startswith("DEEPSEEK_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip("'").strip("'")
                    break
    return key


def tier2_deepseek(text: str) -> Optional[dict]:
    """DeepSeek v4 Flash — for all WALL-E responses."""
    import urllib.request
    key = _get_api_key()
    if not key:
        return None

    t0 = time.perf_counter()
    try:
        with open(SYSTEM_PROMPT) as f:
            system = f.read()

        payload = json.dumps({
            "model": DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
            "max_tokens": 60, "temperature": 0.9,
        }).encode()

        req = urllib.request.Request(
            DEEPSEEK_BASE_URL, data=payload,
            headers={
                "Authorization": "Bearer " + key,
                "Content-Type": "application/json",
            },
        )
        resp = urllib.request.urlopen(req, timeout=15)
        result = json.loads(resp.read())
        response = result["choices"][0]["message"]["content"]
        elapsed = (time.perf_counter() - t0) * 1000
        emotion = _extract_emotion(response)
        return {"tier": 2, "response": response, "emotion": emotion or "CURIOUS",
                "sfx": _emotion_to_sfx(emotion), "latency_ms": elapsed}
    except Exception:
        return None


# ===================== HELPERS =====================
def _extract_emotion(text: str) -> Optional[str]:
    match = re.search(r"\[(HAPPY|CURIOUS|EXCITED|SAD|COMPACT|SCARED|AMAZED|LOVE|DETERMINED)\]", text)
    return match.group(1) if match else None


def _emotion_to_sfx(emotion: Optional[str]) -> str:
    sfx_map = {
        "HAPPY": "curious_beep.wav", "CURIOUS": "curious_beep.wav",
        "EXCITED": "excited_trill.wav", "SAD": "sad_whir.wav",
        "COMPACT": "compacting.wav", "SCARED": "scared_beep.wav",
        "AMAZED": "whoa.wav", "LOVE": "eva_sigh.wav",
        "DETERMINED": "determined_whir.wav",
    }
    return sfx_map.get(emotion or "", "curious_beep.wav")


# ===================== ORCHESTRATOR =====================
class WalleEngine:
    """2-tier routing: keyword cache → DeepSeek v4 Flash."""

    def __init__(self):
        self.stats = {"tier1": 0, "tier2": 0, "miss": 0}

    def respond(self, text: str) -> dict:
        """Route through tiers, return best response."""
        if not text:
            return {"tier": 0, "response": "*confused beep*", "emotion": "CURIOUS",
                    "sfx": "curious_beep.wav", "latency_ms": 0}

        # Tier 1: Keyword cache (<1ms)
        result = tier1_keyword(text)
        if result:
            self.stats["tier1"] += 1
            return result

        # Tier 2: DeepSeek v4 Flash
        result = tier2_deepseek(text)
        if result:
            self.stats["tier2"] += 1
            return result

        # Fallback
        self.stats["miss"] += 1
        return {"tier": 3, "response": "*confused beep* *head tilt*",
                "emotion": "CURIOUS", "sfx": "curious_beep.wav", "latency_ms": 0}


# ===================== BENCHMARK =====================
if __name__ == "__main__":
    engine = WalleEngine()

    tests = [
        "Hello WALL-E!",
        "What is your directive?",
        "Have you seen EVA?",
        "Show me a treasure!",
        "Look, a green plant!",
        "Where is Hal?",
        "Thank you, you're cute!",
        "안녕 WALL-E! 뭐 찾았어?",
        "What do you think about the meaning of life?",
    ]

    print("=" * 65)
    print("  WALL-E RESPONSE ENGINE (DeepSeek v4 Flash)")
    print("  Tier 1: Keyword (<1ms) → Tier 2: DeepSeek (~1.5s)")
    print("=" * 65)

    total = 0
    for msg in tests:
        t0 = time.perf_counter()
        result = engine.respond(msg)
        wall = (time.perf_counter() - t0) * 1000
        total += wall

        emoji = {1: "⚡", 2: "🤖", 3: "❓"}.get(result["tier"], "?")
        print(f"\n🧑 {msg}")
        print(f"  {emoji} Tier {result['tier']} | {result['latency_ms']:.0f}ms LLM | {wall:.0f}ms wall")
        print(f"  🤖 {result['response'][:70]}...")
        print(f"  🎭 [{result['emotion']}] 🔊 {result['sfx']}")

    print(f"\n{'='*65}")
    print(f"  Stats: T1={engine.stats['tier1']} T2={engine.stats['tier2']} miss={engine.stats['miss']}")
    print(f"  Avg wall time: {total/len(tests):.0f}ms")