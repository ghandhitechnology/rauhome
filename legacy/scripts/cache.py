#!/usr/bin/env python3
"""WALL-E Response Cache — bypass LLM for 80% of interactions.
Uses keyword matching + pre-rendered audio for instant (<50ms) responses.
Only falls through to full LLM for truly novel inputs.
"""
import json
import re
import time
import wave
from pathlib import Path
from typing import Optional, Tuple
import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent
CACHE_FILE = PROJECT_ROOT / "response-cache.json"
CACHE_AUDIO_DIR = PROJECT_ROOT / "assets" / "cache"


# ===================== RESPONSE TEMPLATES =====================
# Pattern: (keywords, response_text, emotion, sfx_file)
# Keywords are simple substring matches (case-insensitive)
DEFAULT_TEMPLATES = [
    # Greetings
    (["hello", "hi wall", "hey wall", "안녕", "안뇽"],
     "*beep-beep!* WALL-E! *happy trill*",
     "HAPPY", "curious_beep.wav"),

    # Directive/trash
    (["directive", "what do you do", "your job", "trash", "garbage", "쓰레기", "임무"],
     "*compacting noise* Directive! *determined beep*",
     "COMPACT", "compacting.wav"),

    # EVA
    (["eva", "에바"],
     "*sad whir* EVA...? *holds out hand*",
     "LOVE", "eva_sigh.wav"),

    # Treasure show
    (["treasure", "favorite", "show me", "collection", "보물", "좋아하는"],
     "*whirrr* Ta-da! *shows bubble wrap* Pop-pop-pop!",
     "HAPPY", "curious_beep.wav"),

    # Plant
    (["plant", "green", "growing", "dirt", "seed", "식물", "꽃", "잎"],
     "*amazed whir* Whoa... *happy trill* Ta-da!",
     "AMAZED", "whoa.wav"),

    # Cockroach / Hal
    (["cockroach", "hal", "bug", "바퀴"],
     "*whirrr* Hal? *happy trill*",
     "LOVE", "curious_beep.wav"),

    # Rubik's cube
    (["rubik", "cube", "puzzle", "큐브"],
     "*click-click* *confused beep* *head tilt*",
     "CURIOUS", "curious_beep.wav"),

    # Bubble wrap
    (["bubble", "pop", "뽁뽁"],
     "Pop-pop-pop! *happy trill*",
     "HAPPY", "curious_beep.wav"),

    # Lighter / fire
    (["fire", "lighter", "flame", "불", "라이터"],
     "*flick* Whoa... *amazed whir* *scared beep*",
     "AMAZED", "whoa.wav"),

    # Hello Dolly / VHS / movie
    (["dolly", "movie", "vhs", "tape", "hello dolly", "영화"],
     "*holds up VHS tape* ...Hello, Dolly! *happy trill*",
     "LOVE", "curious_beep.wav"),

    # Spork
    (["spork", "utensil", "fork", "spoon", "스푼", "포크"],
     "Ta-da! *shows spork* Fork AND spoon! *happy trill*",
     "HAPPY", "curious_beep.wav"),

    # Thank you / praise
    (["thank", "good job", "cute", "love you", "고마워", "사랑해", "좋아", "멋져"],
     "*shy beep* *looks down* *happy trill*",
     "HAPPY", "happy_trill.wav" if (PROJECT_ROOT / "assets" / "sfx" / "happy_trill.wav").exists() else "curious_beep.wav"),

    # Goodbye
    (["bye", "goodbye", "see you", "잘가", "안녕"],
     "*sad whir* ...bye... *waves little claw*",
     "SAD", "sad_whir.wav"),

    # Question / curiosity
    (["what", "why", "how", "뭐", "왜", "어떻게"],
     "*head tilt* *curious beep*",
     "CURIOUS", "curious_beep.wav"),
]


class ResponseCache:
    """Lightning-fast response cache for WALL-E."""

    def __init__(self):
        self.templates = []
        self._load_or_build()

    def _load_or_build(self):
        """Load cache from disk or build from defaults."""
        if CACHE_FILE.exists():
            with open(CACHE_FILE) as f:
                data = json.load(f)
            self.templates = data.get("templates", [])
        else:
            self.templates = [
                {"keywords": kw, "response": resp, "emotion": em, "sfx": sfx}
                for kw, resp, em, sfx in DEFAULT_TEMPLATES
            ]
            self._save()
            self._pre_render_audio()

    def _save(self):
        CACHE_FILE.parent.mkdir(exist_ok=True)
        with open(CACHE_FILE, "w") as f:
            json.dump({"templates": self.templates, "version": 1}, f, indent=2)

    def _pre_render_audio(self):
        """Pre-render all cached responses to WAV files."""
        CACHE_AUDIO_DIR.mkdir(parents=True, exist_ok=True)

        import piper
        from pathlib import Path as P
        voice = piper.PiperVoice.load(
            str(PROJECT_ROOT / "models" / "piper" / "en_US-lessac-low.onnx"),
            config_path=str(PROJECT_ROOT / "models" / "piper" / "en_US-lessac-low.onnx.json"),
        )

        for i, t in enumerate(self.templates):
            # Strip SFX markup for TTS
            clean = re.sub(r'\*[^*]+\*', '', t["response"]).strip()
            if not clean:
                clean = "WALL-E!"

            wav_path = CACHE_AUDIO_DIR / f"resp_{i:02d}.wav"
            if wav_path.exists():
                continue  # Already rendered

            with wave.open(str(wav_path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                voice.synthesize_wav(clean, wf)

    def match(self, text: str) -> Optional[dict]:
        """Try to match input text to a cached response.
        Returns dict with response, emotion, sfx, wav_path or None if no match.
        """
        if not text:
            return None

        text_lower = text.lower()
        best = None
        best_score = 0

        for i, t in enumerate(self.templates):
            score = 0
            for kw in t["keywords"]:
                if kw in text_lower:
                    score += len(kw)  # Longer keyword match = better

            if score > best_score:
                best_score = score
                wav_path = CACHE_AUDIO_DIR / f"resp_{i:02d}.wav"
                best = {
                    "response": t["response"],
                    "emotion": t["emotion"],
                    "sfx": t["sfx"],
                    "wav_path": str(wav_path) if wav_path.exists() else None,
                    "score": score,
                }

        # Only use cache if confident (at least 4 chars matched)
        if best and best_score >= 4:
            return best
        return None

    def get_cached_audio(self, text: str) -> Optional[Tuple[np.ndarray, int, str, str]]:
        """Match → return (audio_array, sample_rate, emotion, sfx_file).
        Returns None if no cache hit.
        """
        match = self.match(text)
        if not match or not match["wav_path"]:
            return None

        wav_path = Path(match["wav_path"])
        if not wav_path.exists():
            return None

        with wave.open(str(wav_path), "rb") as wf:
            n_frames = wf.getnframes()
            audio = np.frombuffer(wf.readframes(n_frames), dtype=np.int16).astype(np.float32) / 32768.0
            rate = wf.getframerate()

        return audio, rate, match["emotion"], match["sfx"]


# ===================== CLI =====================
if __name__ == "__main__":
    import sys

    cache = ResponseCache()
    print(f"Loaded {len(cache.templates)} response templates")
    print(f"Audio cache: {len(list(CACHE_AUDIO_DIR.glob('*.wav'))) if CACHE_AUDIO_DIR.exists() else 0} pre-rendered\n")

    tests = [
        "Hello WALL-E!",
        "What is your directive?",
        "Have you seen EVA?",
        "Show me your favorite treasure!",
        "Look, a green plant!",
        "Where is Hal the cockroach?",
        "Thank you, you're so cute!",
        "What's that shiny thing?",
        "안녕 WALL-E!",
        "쓰레기 좀 치워줘!",
        "A random sentence about the weather today",
    ]

    for msg in tests:
        t0 = time.perf_counter()
        result = cache.match(msg)
        latency = (time.perf_counter() - t0) * 1000

        if result:
            print(f"✅ CACHE HIT  ({latency:.0f}ms) | '{msg}' → {result['response'][:50]}... [{result['emotion']}]")
        else:
            print(f"❌ CACHE MISS ({latency:.0f}ms) | '{msg}' → fall through to LLM")
