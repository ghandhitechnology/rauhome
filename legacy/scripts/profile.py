#!/usr/bin/env python3
"""WALL-E Timing/Profiling System
Instruments every stage of the voice pipeline with wall-clock timestamps.
Stores per-stage latency history, prints breakdown, exports JSON.
Usage:
  python3 scripts/profile.py              # Full instrumentation benchmark
  python3 scripts/profile.py --history    # View accumulated timing history
  python3 scripts/profile.py --json       # Export last run as JSON
"""
import time
import json
import statistics
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

PROJECT_ROOT = Path(__file__).parent.parent
HISTORY_FILE = PROJECT_ROOT / "timing-history.jsonl"
MAX_HISTORY = 200  # keep last 200 runs


# ===================== TIMING INFRA =====================
@dataclass
class Stage:
    """A single pipeline stage with timing stats."""
    name: str
    times_ms: list = field(default_factory=list)
    last: float = 0.0

    def record(self, elapsed_ms: float):
        self.times_ms.append(elapsed_ms)
        self.last = elapsed_ms

    @property
    def avg(self) -> float:
        return statistics.mean(self.times_ms) if self.times_ms else 0

    @property
    def p50(self) -> float:
        if not self.times_ms: return 0
        return statistics.median(self.times_ms)

    @property
    def p95(self) -> float:
        if len(self.times_ms) < 20: return max(self.times_ms, default=0)
        return sorted(self.times_ms)[int(len(self.times_ms) * 0.95)]

    @property
    def min(self) -> float:
        return min(self.times_ms) if self.times_ms else 0

    @property
    def max(self) -> float:
        return max(self.times_ms) if self.times_ms else 0


class Timer:
    """High-precision wall-clock timer."""
    def __init__(self):
        self._start = time.perf_counter_ns()

    def elapsed_ms(self) -> float:
        return (time.perf_counter_ns() - self._start) / 1_000_000

    def lap(self) -> float:
        """Return elapsed and reset."""
        now = time.perf_counter_ns()
        elapsed = (now - self._start) / 1_000_000
        self._start = now
        return elapsed


class PipelineProfiler:
    """Instruments the full pipeline: VAD→Record→STT→LLM→TTS→FX→Play."""

    def __init__(self):
        self.stages = {
            "vad_detect": Stage("VAD (detect speech)"),
            "record": Stage("Record (capture)"),
            "stt": Stage("STT (faster-whisper)"),
            "llm_ttft": Stage("LLM (first token)"),
            "llm_gen": Stage("LLM (generation)"),
            "tts": Stage("TTS (piper synthesize)"),
            "fx": Stage("FX (pedalboard)"),
            "play": Stage("Play (speaker output)"),
            "total": Stage("TOTAL (end-to-end)"),
            "overhead": Stage("Overhead (queue/thread)"),
        }
        self.run_count = 0

    def record_run(self, stage_times: dict):
        """Record one full pipeline run."""
        self.run_count += 1
        for name, ms in stage_times.items():
            if name in self.stages:
                self.stages[name].record(ms)
        self._append_history(stage_times)

    def _append_history(self, stage_times: dict):
        entry = {"run": self.run_count, "timestamp": time.time(), **stage_times}
        with open(HISTORY_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def load_history(self):
        """Load all historical runs."""
        if not HISTORY_FILE.exists():
            return []
        runs = []
        with open(HISTORY_FILE) as f:
            for line in f:
                try:
                    runs.append(json.loads(line.strip()))
                except json.JSONDecodeError:
                    continue
        return runs[-MAX_HISTORY:]

    def print_breakdown(self):
        """Pretty-print timing breakdown."""
        if self.run_count == 0:
            print("No runs recorded yet.")
            return

        print()
        print("=" * 74)
        print(f"  WALL-E PIPELINE TIMING — {self.run_count} runs")
        print("=" * 74)
        print(f"  {'STAGE':<28} {'LAST':>7} {'AVG':>7} {'P50':>7} {'P95':>7} {'MIN':>7} {'MAX':>7}")
        print(f"  {'─'*28} {'─'*7} {'─'*7} {'─'*7} {'─'*7} {'─'*7} {'─'*7}")

        for s in self.stages.values():
            if s.times_ms:
                print(f"  {s.name:<28} {s.last:>6.0f}ms {s.avg:>6.0f}ms {s.p50:>6.0f}ms {s.p95:>6.0f}ms {s.min:>6.0f}ms {s.max:>6.0f}ms")

        # Waterfall
        total = self.stages["total"]
        print()
        print("  WATERFALL (last run):")
        waterfall = [
            ("VAD→Record", self.stages["vad_detect"].last + self.stages["record"].last),
            ("STT", self.stages["stt"].last),
            ("LLM TTFT", self.stages["llm_ttft"].last),
            ("LLM Gen", self.stages["llm_gen"].last),
            ("TTS", self.stages["tts"].last),
            ("FX", self.stages["fx"].last),
            ("Play", self.stages["play"].last),
        ]
        max_name = max(len(n) for n, _ in waterfall)
        bar_width = 50
        max_ms = max(ms for _, ms in waterfall)

        for name, ms in waterfall:
            pct = ms / total.last * 100 if total.last > 0 else 0
            bar = "█" * int(ms / max_ms * bar_width) if max_ms > 0 else ""
            print(f"  {name:<{max_name}} {bar} {ms:>6.0f}ms ({pct:>4.1f}%)")

        print(f"  {'─'*(max_name+bar_width+14)}")
        print(f"  {'TOTAL':<{max_name}} {'█'*bar_width} {total.last:>6.0f}ms")

    def export_json(self) -> str:
        """Export latest run as JSON."""
        runs = self.load_history()
        if not runs:
            return json.dumps({"error": "no data"})

        latest = runs[-1]
        summary = {
            "run": latest["run"],
            "timestamp": latest["timestamp"],
            "stages": {k: v for k, v in latest.items() if k not in ("run", "timestamp")},
            "totals": {
                "runs_recorded": len(runs),
                "avg_total_ms": self.stages["total"].avg,
                "p50_total_ms": self.stages["total"].p50,
                "best_total_ms": self.stages["total"].min,
                "worst_total_ms": self.stages["total"].max,
                "avg_ttft_ms": self.stages["llm_ttft"].avg,
                "avg_stt_ms": self.stages["stt"].avg,
                "avg_tts_ms": self.stages["tts"].avg,
            },
        }
        return json.dumps(summary, indent=2)


# ===================== INSTRUMENTED PIPELINE =====================
def instrumented_pipeline_run(profiler: PipelineProfiler, test_text: str = "Hello WALL-E!"):
    """Run one pipeline cycle with full instrumentation."""
    import subprocess, json, tempfile, os, wave
    import numpy as np
    from faster_whisper import WhisperModel
    import piper

    timer = Timer()
    stage_times = {}

    # === LOAD MODELS (once) ===
    print("🔥 Loading models...")
    whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")

    from pathlib import Path as P
    piper_voice = piper.PiperVoice.load(
        str(PROJECT_ROOT / "models" / "piper" / "en_US-lessac-low.onnx"),
        config_path=str(PROJECT_ROOT / "models" / "piper" / "en_US-lessac-low.onnx.json"),
    )

    from pedalboard import Pedalboard, PitchShift, Bitcrush, Distortion, Reverb
    board = Pedalboard([
        PitchShift(semitones=4), Bitcrush(bit_depth=8),
        Distortion(drive_db=4), Reverb(room_size=0.2, wet_level=0.1, dry_level=0.9),
    ])

    system_prompt = open(PROJECT_ROOT / "prompts" / "system-prompt.md").read()
    print("  ✅ Models loaded\n")

    # === RUN 5 INSTRUMENTED CYCLES ===
    import webrtcvad
    vad = webrtcvad.Vad(2)
    import sounddevice as sd

    RUNS = 5
    test_messages = [
        "Hello WALL-E!",
        "What is your directive?",
        "Show me a treasure!",
        "EVA left... are you okay?",
        "Look, a green plant!",
    ]

    for i, msg in enumerate(test_messages[:RUNS]):
        print(f"─── Run {i+1}/{RUNS} ───")
        cycle_timer = Timer()
        cycle_times = {}

        # 1. VAD + Record (simulate with real capture)
        print(f"  🎤 Say: '{msg}' (or we simulate)...")
        t_vad = timer.elapsed_ms()
        # Use webrtcvad to detect silence → simulate
        import numpy as np
        test_audio = (np.random.randn(16000 * 2) * 0.05).astype(np.float32)
        audio_16 = (test_audio * 32767).astype(np.int16)
        is_speech = vad.is_speech(audio_16[:480].tobytes(), 16000)
        cycle_times["vad_detect"] = timer.lap()

        # 2. Record (already have audio)
        cycle_times["record"] = timer.lap()

        # 3. STT
        segments, _ = whisper_model.transcribe(test_audio, language="en", beam_size=5, vad_filter=False)
        text = " ".join(s.text for s in segments).strip()
        cycle_times["stt"] = timer.lap()
        print(f"  📝 STT: '{text[:60]}' — {cycle_times['stt']:.0f}ms")

        # 4. LLM TTFT + Generation
        payload = {
            "model": "gemma3:4b",
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": msg}],
            "stream": True,
            "options": {"temperature": 0.9, "top_p": 0.95, "num_predict": 40},
        }
        proc = subprocess.Popen(
            ["curl", "-s", "-N", "http://127.0.0.1:11434/api/chat", "-d", json.dumps(payload)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        t_llm_start = timer.elapsed_ms()
        first_token = None
        full_response = ""
        tokens = 0
        for line in proc.stdout:
            try:
                c = json.loads(line.decode().strip())
                t = c.get("message", {}).get("content", "")
                if t and first_token is None:
                    first_token = timer.elapsed_ms() - t_llm_start
                if t: tokens += 1; full_response += t
                if c.get("done"): break
            except: continue
        proc.wait()
        gen_done = timer.elapsed_ms() - t_llm_start
        cycle_times["llm_ttft"] = first_token or 0
        cycle_times["llm_gen"] = gen_done - (first_token or 0)
        _ = timer.lap()  # Sync timer: consume LLM time so TTS measurement is clean

        # Extract emotion
        import re
        match = re.search(r"\[(HAPPY|CURIOUS|EXCITED|SAD|COMPACT|SCARED|AMAZED|LOVE|DETERMINED)\]", full_response)
        emotion = f"[{match.group(1)}]" if match else None
        clean = full_response.replace(emotion, "").strip() if emotion else full_response
        print(f"  🤖 WALL-E: {clean[:60]}... {emotion or ''} | TTFT:{cycle_times['llm_ttft']:.0f}ms Gen:{cycle_times['llm_gen']:.0f}ms ({tokens} tok)")

        # 5. TTS (with SFX stripping + proper synthesize_wav)
        import re as re_mod
        clean_tts = re_mod.sub(r'\*[^*]+\*', '', clean or "WALL-E!").strip() or "WALL-E!"
        import tempfile as tmpf, wave as wav_mod
        f = tmpf.NamedTemporaryFile(suffix='.wav', delete=False)
        tname = f.name; f.close()
        with wav_mod.open(tname, 'wb') as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000)
            piper_voice.synthesize_wav(clean_tts, wf)
        with wav_mod.open(tname, 'rb') as wf:
            pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
        os.unlink(tname)
        cycle_times["tts"] = timer.lap()
        print(f"  🔊 TTS: {cycle_times['tts']:.0f}ms ({len(pcm)/16000*1000:.0f}ms audio)")

        # 6. FX
        board(pcm, 16000)
        cycle_times["fx"] = timer.lap()

        # 7. Play (simulated — don't actually play)
        cycle_times["play"] = timer.lap()

        # Total
        cycle_times["total"] = cycle_timer.elapsed_ms()
        cycle_times["overhead"] = cycle_times["total"] - sum(
            v for k, v in cycle_times.items() if k != "total" and k != "overhead"
        )
        print(f"  ⏱️  TOTAL: {cycle_times['total']:.0f}ms\n")

        profiler.record_run(cycle_times)

    return profiler


# ===================== MAIN =====================
if __name__ == "__main__":
    profiler = PipelineProfiler()

    if "--history" in sys.argv:
        runs = profiler.load_history()
        if runs:
            for r in runs:
                profiler.record_run({k: v for k, v in r.items() if k not in ("run", "timestamp")})
        profiler.print_breakdown()

    elif "--json" in sys.argv:
        runs = profiler.load_history()
        if runs:
            for r in runs:
                profiler.record_run({k: v for k, v in r.items() if k not in ("run", "timestamp")})
        print(profiler.export_json())

    else:
        profiler = instrumented_pipeline_run(profiler)
        profiler.print_breakdown()
