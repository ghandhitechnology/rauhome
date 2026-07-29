"""Voice face loop — VAD/STT/TTS + control consumption."""
from __future__ import annotations

import subprocess
import queue
import time
from threading import Event, Thread
from typing import Optional

import numpy as np

from rau.agent import orchestrator
from rau.events import BUS
from rau.face import brain
from rau.face.tts import apply_robot_fx, tts, warmup as tts_warmup
from rau.heartbeat.presence import note_user_reply
from rau import state

SAMPLE_RATE = 16000
SILENCE_SEC = 1.2
MAX_RECORD_SEC = 10

_vad_model = None
_whisper_model = None
_stop = Event()
#: Id of the confirm the face last read aloud, so a spoken yes/no lands on it.
_spoken_confirm_id: Optional[str] = None
_threads: list = []
_audio_capture = None


def get_vad():
    global _vad_model
    if _vad_model is None:
        try:
            from silero_vad import load_silero_vad

            _vad_model = load_silero_vad(onnx=True)
        except Exception:
            return None
    return _vad_model


def _open_ffmpeg():
    return subprocess.Popen(
        [
            "ffmpeg",
            "-f",
            "avfoundation",
            "-i",
            ":0",
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            "1",
            "-af",
            "volume=16dB",
            "-f",
            "s16le",
            "-bufsize",
            "1024",
            "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )


class _AudioCapture:
    """One long-lived microphone process with a bounded latest-frame queue."""

    def __init__(self) -> None:
        self.frames: queue.Queue[bytes] = queue.Queue(maxsize=100)
        self.stop_event = Event()
        self.process: Optional[subprocess.Popen] = None
        self.thread: Optional[Thread] = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.process = _open_ffmpeg()
        self.thread = Thread(
            target=self._pump, daemon=True, name="rau-audio-capture"
        )
        self.thread.start()

    def _pump(self) -> None:
        frame_bytes = 512 * 2
        while not self.stop_event.is_set():
            process = self.process
            if process is None or process.stdout is None:
                return
            raw = process.stdout.read(frame_bytes)
            if not raw or len(raw) < frame_bytes:
                return
            try:
                self.frames.put_nowait(raw)
            except queue.Full:
                try:
                    self.frames.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self.frames.put_nowait(raw)
                except queue.Full:
                    pass

    def flush(self) -> None:
        while True:
            try:
                self.frames.get_nowait()
            except queue.Empty:
                return

    def read(self, timeout: float = 1.0) -> bytes:
        try:
            return self.frames.get(timeout=timeout)
        except queue.Empty:
            return b""

    def stop(self) -> None:
        self.stop_event.set()
        process = self.process
        self.process = None
        if process is not None and process.poll() is None:
            process.kill()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)


def record_speech(*, local_vad: bool = True) -> Optional[np.ndarray]:
    global _audio_capture

    model = get_vad() if local_vad else None
    if _audio_capture is None:
        _audio_capture = _AudioCapture()
        _audio_capture.start()
    elif not _audio_capture.thread or not _audio_capture.thread.is_alive():
        _audio_capture.stop()
        _audio_capture = _AudioCapture()
        _audio_capture.start()
    # Bind the capture once: stop_face() clears the global mid-record, and a
    # pump that dies mid-record must not park the loop below — read() only
    # ever times out from then on, so `frames` would never advance again.
    capture = _audio_capture
    capture.flush()
    frame_size = 512
    bytes_per_frame = frame_size * 2
    voiced = []
    started = False
    silence_frames = 0
    max_silence = int(SILENCE_SEC * SAMPLE_RATE / frame_size)
    max_frames = int(MAX_RECORD_SEC * SAMPLE_RATE / frame_size)
    frames = 0
    empty_reads = 0
    while frames < max_frames and not _stop.is_set():
        raw = capture.read()
        if not raw or len(raw) < bytes_per_frame:
            # A live pump delivers ~31 frames a second, so even one timed-out
            # read means the capture process is gone; a few in a row is
            # certain. Bail out — the next call restarts a dead capture.
            empty_reads += 1
            if empty_reads >= 3:
                break
            continue
        empty_reads = 0
        frame = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        frames += 1
        speech = False
        if model is not None:
            try:
                speech = float(np.abs(frame).mean()) > 0.01
                import torch

                t = torch.from_numpy(frame)
                if t.ndim == 1:
                    speech = bool(model(t, SAMPLE_RATE).item() > 0.5)
            except Exception:
                speech = float(np.abs(frame).mean()) > 0.012
        else:
            speech = float(np.abs(frame).mean()) > 0.012

        if speech:
            started = True
            silence_frames = 0
            voiced.append(frame)
        elif started:
            silence_frames += 1
            voiced.append(frame)
            if silence_frames >= max_silence:
                break
    if not voiced:
        return None
    return np.concatenate(voiced)


def stt(audio: np.ndarray) -> str:
    import asyncio

    from rau.voice.stt import get_stt_provider

    provider = get_stt_provider()
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes()

    async def transcribe() -> str:
        async def source():
            yield pcm

        final = ""
        try:
            async for transcript in provider.stream(source()):
                if transcript.final:
                    final = transcript.text
        finally:
            await provider.close()
        return final.strip()

    return asyncio.run(transcribe())


def play_audio(audio: np.ndarray, sr: int = 24000) -> None:
    try:
        import sounddevice as sd

        sd.play(audio, sr)
        sd.wait()
    except Exception as e:
        print(f"  play err: {e}")


def speak(text: str, emotion: str = "idle") -> None:
    from rau.heartbeat.presence import note_mood

    clean, tag = brain.extract_emotion(text)
    emo = (tag or emotion or "idle").lower()
    if tag:
        note_mood(emo, 0.7 if emo != "idle" else 0.0)
    state.set_emotion(emo, clean)
    state.set_face_busy(True)
    try:
        result = tts(clean)
        if result:
            audio, sr = result
            audio = apply_robot_fx(audio, sr)
            play_audio(audio, sr)
    finally:
        state.set_face_busy(False)


def _handle_control(cmd: dict) -> None:
    action = (cmd.get("action") or "").lower()
    if action == "start":
        state.set_listening(True)
    elif action == "stop":
        state.set_listening(False)
    elif action == "shutdown":
        _stop.set()
    elif action == "test":
        speak("Systems online. I am Rau.")
    elif action == "confirm":
        orchestrator.resolve_confirm(True, cmd.get("id"))
    elif action in ("deny", "cancel_confirm"):
        orchestrator.resolve_confirm(False, cmd.get("id"))
    elif action == "cancel_task":
        orchestrator.cancel_hard_task()
        speak("Okay — I stopped that deep work.")
    elif action == "speak":
        speak(str(cmd.get("text") or ""))
    elif action == "presence_speak":
        from rau.heartbeat.presence import presence_speech_is_current

        if presence_speech_is_current(
            cmd.get("last_user_ts"), cmd.get("locale")
        ):
            speak(str(cmd.get("text") or ""))
    elif action == "weave_result":
        line = brain.weave_result(str(cmd.get("goal") or ""), str(cmd.get("result") or ""))
        speak(line)
    elif action == "ask_confirm":
        summary = str(cmd.get("summary") or "a risky action")
        # Remember which confirm this was: with several jobs in flight, a bare
        # spoken "yes" would otherwise resolve the oldest pending one rather
        # than the one just read aloud.
        global _spoken_confirm_id
        _spoken_confirm_id = cmd.get("id")
        speak(f"I need your yes or no. {summary}. Say yes to allow, or no to cancel.")


def _control_thread() -> None:
    while not _stop.is_set():
        cmd = state.pop_control()
        if cmd:
            try:
                _handle_control(cmd)
            except Exception as e:
                print(f"  control err: {e}")
        else:
            time.sleep(0.1)


def _progress_listener(event: dict) -> None:
    if event.get("kind") != "hard_task_progress":
        return
    # Light B narration — only occasionally via control speak to avoid overlap
    progress = event.get("progress") or ""
    if progress and not state.status_snapshot().get("face_busy"):
        # don't speak every progress; heartbeat already emits — face may ignore floods
        pass


def start_face(*, with_audio: bool = True) -> None:
    global _threads
    _stop.clear()
    state.set_voice_pipeline(True)
    BUS.on("hard_task_progress", _progress_listener)
    ctrl = Thread(target=_control_thread, daemon=True, name="rau-control")
    ctrl.start()
    _threads = [ctrl]

    if not with_audio:
        return

    def loop():
        global _spoken_confirm_id
        print("Rau face listening...")
        tts_warmup()
        global _audio_capture
        _audio_capture = _AudioCapture()
        _audio_capture.start()
        last_progress_spoke = 0.0
        while not _stop.is_set():
            if not state.status_snapshot().get("listening"):
                time.sleep(0.2)
                continue
            # light progress talk
            ht = state.get_hard_task()
            if (
                ht.get("state") == "running"
                and time.time() - last_progress_spoke > 28
                and not state.status_snapshot().get("face_busy")
            ):
                speak("Still working on that — one moment.")
                last_progress_spoke = time.time()

            state.set_emotion("curious", "")
            from rau.voice.stt import resolve_stt

            selected_stt, _ = resolve_stt()
            audio = record_speech(local_vad=selected_stt == "local")
            if audio is None or len(audio) < 1000:
                continue
            state.set_emotion("determined", "")
            try:
                text = stt(audio)
            except Exception as e:
                print(f"  STT err: {e}")
                continue
            if not text:
                continue
            print(f"You: {text}")
            note_user_reply()
            state.add_log("user", text)

            # Voice confirm shortcuts, answered against the confirm we actually
            # read out — not merely the oldest one still pending.
            low = text.lower().strip()
            if state.get_confirm():
                cid = _spoken_confirm_id
                if low in ("yes", "yeah", "yep", "allow", "ok", "okay", "confirm"):
                    orchestrator.resolve_confirm(True, cid)
                    _spoken_confirm_id = None
                    speak("Okay — going ahead.")
                    continue
                if low in ("no", "nope", "deny", "cancel", "stop"):
                    orchestrator.resolve_confirm(False, cid)
                    _spoken_confirm_id = None
                    speak("Okay — cancelled.")
                    continue

            try:
                reply = brain.chat(text)
            except brain.Cancelled:
                # A newer typed/voice turn owns the foreground now. The stale
                # local turn must not enqueue speech or an error apology.
                continue
            except Exception as e:
                reply = f"I hit a snag thinking: {e}"
            print(f"Rau: {reply}")
            state.add_log("rau", reply)
            speak(reply)

            # if we initiated earlier and user replied, backoff clears via note_user_reply
            # if user goes silent after our speak, heartbeat tracks misses separately

    t = Thread(target=loop, daemon=True, name="rau-face")
    t.start()
    _threads.append(t)


def stop_face() -> None:
    global _audio_capture

    _stop.set()
    if _audio_capture is not None:
        _audio_capture.stop()
        _audio_capture = None
    state.set_voice_pipeline(False)
