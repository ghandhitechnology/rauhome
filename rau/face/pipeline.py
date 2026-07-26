"""Voice face loop — VAD/STT/TTS + control consumption."""
from __future__ import annotations

import subprocess
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


def record_speech() -> Optional[np.ndarray]:
    model = get_vad()
    proc = _open_ffmpeg()
    frame_size = 512
    bytes_per_frame = frame_size * 2
    voiced = []
    started = False
    silence_frames = 0
    max_silence = int(SILENCE_SEC * SAMPLE_RATE / frame_size)
    max_frames = int(MAX_RECORD_SEC * SAMPLE_RATE / frame_size)
    frames = 0
    try:
        while frames < max_frames and not _stop.is_set():
            raw = proc.stdout.read(bytes_per_frame)
            if not raw or len(raw) < bytes_per_frame:
                break
            frame = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            frames += 1
            speech = False
            if model is not None:
                try:
                    from silero_vad import VADIterator

                    # energy fallback inside loop if iterator API awkward
                    speech = float(np.abs(frame).mean()) > 0.01
                    # Better: use model probability
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
    finally:
        proc.kill()
    if not voiced:
        return None
    return np.concatenate(voiced)


def stt(audio: np.ndarray) -> str:
    global _whisper_model
    from faster_whisper import WhisperModel

    if _whisper_model is None:
        _whisper_model = WhisperModel("small", device="cpu", compute_type="int8")
    segments, _ = _whisper_model.transcribe(
        audio, language=None, beam_size=5, vad_filter=False
    )
    return " ".join(s.text for s in segments).strip()


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
            audio = record_speech()
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
    _stop.set()
    state.set_voice_pipeline(False)
