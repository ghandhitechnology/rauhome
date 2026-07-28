"""Rau local hub — HTTP + WebSocket API, serves web/dist."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from rau.agent import orchestrator
from rau.dream.dreamer import run_dream, start_dreamer
from rau.env import (
    auth_status,
    clear_secret,
    has_secret,
    load_dotenv,
    set_secret,
    slot_by_id,
)
from rau.events import BUS
from rau.heartbeat.presence import start_heartbeat
from rau.hub.security import LocalAccessMiddleware, allowed_hostnames
from rau.identity import store as identity_store
from rau.mcp.client import MCP
from rau.memory import store as memory_store
from rau.paths import WEB_DIST, ensure_dirs
from rau.providers.catalog import PROVIDER_AUTH, catalog
from rau.permissions import get_permissions, global_mode, set_permissions
from rau.providers.registry import (
    EFFORT_LEVELS,
    load_models,
    load_settings,
    provider_status,
    save_models,
    save_settings,
)
from rau.providers import verify as provider_verify
from rau.skills import goals as goal_store
from rau.skills.loader import load_skill, skills_public
from rau.scheduler import SCHEDULER
from rau import state

load_dotenv(override=False)
ensure_dirs()

log = logging.getLogger("rau.hub")

app = FastAPI(title="Rau Hub", version="1.0.0")
_security_settings = load_settings()
_extra_hosts = _security_settings.get("hub_allowed_hosts") or []
if isinstance(_extra_hosts, str):
    _extra_hosts = [_extra_hosts]
app.add_middleware(
    LocalAccessMiddleware,
    allowed_hosts=allowed_hostnames(
        str(_security_settings.get("hub_host") or "127.0.0.1"),
        (str(host) for host in _extra_hosts),
    ),
)


class EmotionIn(BaseModel):
    emotion: str = "idle"
    text: str = Field(default="", max_length=1_000)


class LogIn(BaseModel):
    role: str = "user"
    text: str = Field(default="", max_length=16_000)


class ControlIn(BaseModel):
    action: str
    id: Optional[str] = None
    text: Optional[str] = None
    goal: Optional[str] = None
    summary: Optional[str] = None


class HardTaskIn(BaseModel):
    goal: str


class JobIn(BaseModel):
    goal: str


class JobSteerIn(BaseModel):
    instruction: str = Field(min_length=1, max_length=4_000)


class IdentityApplyFresh(BaseModel):
    mode: str = "fresh"


class IdentityApplyHard(BaseModel):
    identity: str = Field(max_length=100_000)
    backstory: str = Field(max_length=100_000)


class IdentitySteer(BaseModel):
    identity: Optional[str] = Field(default=None, max_length=100_000)
    backstory: Optional[str] = Field(default=None, max_length=100_000)


class ModelsIn(BaseModel):
    face: Optional[Dict[str, Any]] = None
    subagent: Optional[Dict[str, Any]] = None
    dream: Optional[Dict[str, Any]] = None
    tts: Optional[Dict[str, Any]] = None
    stt: Optional[Dict[str, Any]] = None
    browse: Optional[Dict[str, Any]] = None


class ConfirmIn(BaseModel):
    approved: bool
    id: Optional[str] = None


class PermissionsIn(BaseModel):
    mode: Optional[str] = None
    subagents: Optional[str] = None
    room: Optional[str] = None
    heartbeats: Optional[str] = None


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=16_000)


class AuthKeyIn(BaseModel):
    key: str = Field(min_length=1, max_length=20_000)


class AuthVerifyIn(BaseModel):
    key: Optional[str] = None


class EffortIn(BaseModel):
    face: Optional[str] = None
    subagent: Optional[str] = None
    dream: Optional[str] = None
    player: Optional[str] = None
    all: Optional[str] = None


# Slots the effort API manages; kept in one place so the "all" loop and the
# per-slot loop can never disagree.
_EFFORT_SLOTS = ("face", "subagent", "dream", "player")


class ResourceProfileIn(BaseModel):
    profile: str = Field(pattern="^(eco|balanced|performance)$")


class GoalIn(BaseModel):
    text: str = Field(min_length=1, max_length=4_000)


class GoalNoteIn(BaseModel):
    text: str = Field(max_length=4_000)


class ScheduleIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1, max_length=100_000)
    trigger: Dict[str, Any]
    timezone: str = Field(default="Asia/Seoul", min_length=1, max_length=100)
    enabled: bool = True
    resource_profile: str = Field(
        default="balanced", pattern="^(eco|balanced|performance)$"
    )
    permission_policy: str = Field(
        default="approval", pattern="^(readonly|approval)$"
    )
    budget: Dict[str, Any] = Field(default_factory=dict)


class SchedulePatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    goal: Optional[str] = Field(default=None, min_length=1, max_length=100_000)
    trigger: Optional[Dict[str, Any]] = None
    timezone: Optional[str] = Field(default=None, min_length=1, max_length=100)
    enabled: Optional[bool] = None
    resource_profile: Optional[str] = Field(
        default=None, pattern="^(eco|balanced|performance)$"
    )
    permission_policy: Optional[str] = Field(
        default=None, pattern="^(readonly|approval)$"
    )
    budget: Optional[Dict[str, Any]] = None


class ComputerSessionIn(BaseModel):
    app: Optional[str] = Field(default=None, max_length=200)
    frontmost: bool = True
    deadline_sec: float = Field(default=900, ge=30, le=3600)


class ComputerCommandIn(BaseModel):
    payload: Dict[str, Any] = Field(default_factory=dict)


class VoicePreviewIn(BaseModel):
    text: str = Field(
        default="Hello, I am Rau. Voice systems are online.",
        min_length=1,
        max_length=240,
    )
    provider: str = Field(default="elevenlabs", pattern="^(elevenlabs|cartesia)$")
    voice_id: str = Field(min_length=3, max_length=128)
    model: str = Field(default="", max_length=128)
    effect: str = Field(default="none", pattern="^(none|robot|childlike)$")
    voice_settings: Dict[str, Any] = Field(
        default_factory=lambda: {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.0,
            "speed": 1.0,
            "use_speaker_boost": True,
        }
    )


@app.on_event("startup")
async def _startup() -> None:
    from rau.heartbeat.presence import load_presence
    from rau.pet import pet_binary, start_pet

    load_presence()
    runtime = os.environ.get("RAU_RUNTIME") == "1"
    if runtime:
        state.enable_durable_state()
        SCHEDULER.start()
        from rau.resources import current_profile

        if current_profile()["dream_enabled"]:
            start_dreamer()
        start_heartbeat()
    # A game of chess outlives the process that was hosting it. He restarts to
    # dream, or the machine sleeps, and an hour of play would otherwise be gone
    # — so an unfinished board is picked back up before anyone asks for it.
    # Failing to is not worth refusing to boot over.
    try:
        from rau.games.chess import session as chess_session

        if chess_session.resume() is not None:
            print("Picked the chess game back up.")
    except Exception as exc:  # noqa: BLE001
        print(f"Could not resume the chess game: {exc}")

    settings = load_settings()
    port = int(settings.get("hub_port") or 8765)
    # The pet is a client, so it needs an address it can dial. A wildcard bind
    # is a listening address, not a destination — handing it through leaves the
    # pet trying to connect to 0.0.0.0 and silently never arriving.
    host = str(settings.get("hub_host") or "127.0.0.1")
    if host in ("", "0.0.0.0", "::", "[::]"):
        host = "127.0.0.1"
    if runtime:
        try:
            if start_pet(f"http://{host}:{port}"):
                print(f"Desktop pet: {pet_binary()}")
        except Exception as exc:  # noqa: BLE001
            # A cosmetic companion window must never be the reason the hub —
            # and with it the whole app — refuses to come up.
            print(f"Desktop pet not started: {exc}")


@app.on_event("shutdown")
async def _shutdown() -> None:
    from rau.dream.dreamer import stop_dreamer
    from rau.heartbeat.presence import stop_heartbeat
    from rau.pet import stop_pet
    from rau.pi.supervisor import PI_SUPERVISOR

    # Cancel in-flight agent jobs first: their worker threads are joined at
    # interpreter exit, so leaving one running turns shutdown into a wait of
    # up to max_runtime_sec (or a 24h confirm wait).
    orchestrator.cancel_all()
    stop_dreamer()
    stop_heartbeat()
    SCHEDULER.stop()
    stop_pet()
    PI_SUPERVISOR.stop()
    # Stockfish is a subprocess on its own event-loop thread; without this it
    # outlives the hub that opened it.
    try:
        from rau.games.chess import engine as chess_engine

        chess_engine.close()
    except Exception:
        # Shutdown is not the place to raise about a process that is going away
        # anyway.
        pass


@app.get("/api/status")
def api_status():
    snap = state.status_snapshot()
    snap["eye_server"] = True
    snap["identity_ready"] = identity_store.has_soul()
    snap["providers"] = provider_status()
    snap["mcp"] = MCP.status()
    from rau.resources import current_profile

    snap["resource_profile"] = current_profile()
    snap["memory"] = memory_store.summary()
    models = load_models()
    from rau.providers.reasoning import effort_snapshot

    snap["effort"] = effort_snapshot(models)
    snap["goal"] = goal_store.get_goal()
    snap["skills_count"] = len(skills_public())
    perms = get_permissions()
    snap["permissions"] = perms
    snap["permission_mode"] = global_mode(perms)
    return snap


@app.get("/api/health")
def api_health():
    """Cheap liveness snapshot; never scans providers, memory, or the filesystem."""
    snap = state.status_snapshot()
    return {
        "ok": True,
        "timestamp": snap["timestamp"],
        "listening": snap["listening"],
        "face_busy": snap["face_busy"],
        "hard_task": snap["hard_task"],
        "confirm": snap["confirm"],
        "scheduler": SCHEDULER.status() if state.durable_enabled() else {"running": False},
    }


@app.get("/api/emotion")
def api_emotion_get():
    return state.get_emotion()


@app.post("/api/emotion")
def api_emotion_post(body: EmotionIn):
    return state.set_emotion(body.emotion, body.text)


@app.get("/api/log")
def api_log_get():
    return {"log": state.get_log()}


@app.post("/api/log")
def api_log_post(body: LogIn):
    state.add_log(body.role, body.text)
    return {"ok": True}


@app.get("/api/control")
def api_control_get():
    return {"command": state.pop_control()}


@app.post("/api/control")
def api_control_post(body: ControlIn):
    state.push_control(body.model_dump(exclude_none=True))
    # Resolve confirms immediately when posted as control
    if body.action in ("confirm", "deny", "cancel_confirm"):
        orchestrator.resolve_confirm(body.action == "confirm", body.id)
    return {"ok": True}


@app.post("/api/confirm")
def api_confirm(body: ConfirmIn):
    orchestrator.resolve_confirm(body.approved, body.id)
    return {"ok": True, "approved": body.approved}


@app.get("/api/hard-task")
def api_hard_task_get():
    return state.get_hard_task()


@app.post("/api/hard-task")
def api_hard_task_start(body: HardTaskIn):
    result = orchestrator.start_hard_task(body.goal)
    if result.get("reason") in {"empty_goal", "invalid_goal", "goal_too_large"}:
        return JSONResponse(result, status_code=400)
    if result.get("reason") == "readonly":
        return JSONResponse(result, status_code=403)
    if not result.get("ok"):
        return JSONResponse(result, status_code=409)
    return result


@app.post("/api/hard-task/cancel")
def api_hard_task_cancel():
    return orchestrator.cancel_hard_task()


@app.post("/api/hard-task/redirect")
def api_hard_task_redirect(body: HardTaskIn):
    result = orchestrator.redirect_hard_task(body.goal)
    if result.get("reason") in {"empty_goal", "invalid_goal", "goal_too_large"}:
        return JSONResponse(result, status_code=400)
    if result.get("reason") == "readonly":
        return JSONResponse(result, status_code=403)
    if not result.get("ok"):
        return JSONResponse(result, status_code=409)
    return result


@app.get("/api/jobs")
def api_jobs_list():
    return {
        "jobs": orchestrator.list_jobs(),
        "max_parallel": orchestrator.max_parallel_jobs(),
    }


@app.post("/api/jobs")
def api_jobs_start(body: JobIn):
    result = orchestrator.start_job(body.goal)
    if not result.get("ok"):
        if result.get("reason") == "readonly":
            return JSONResponse(result, status_code=403)
        bad_input = result.get("reason") == "empty_goal"
        return JSONResponse(result, status_code=400 if bad_input else 409)
    return result


@app.get("/api/jobs/{job_id}")
def api_job_get(job_id: str):
    job = orchestrator.get_job(job_id)
    if job is None:
        return JSONResponse({"ok": False, "error": "unknown job"}, status_code=404)
    steps = []
    if state.durable_enabled():
        from rau.control import control_store

        steps = control_store.list_steps(job_id)
    return {"job": job, "steps": steps}


@app.get("/api/confirmations")
def api_confirmations_list(state_filter: str = "pending"):
    if not state.durable_enabled():
        pending = state.get_confirm()
        return {"confirmations": [pending] if pending else []}
    from rau.control import control_store

    allowed = state_filter if state_filter in {"pending", "decided", "expired"} else None
    return {"confirmations": control_store.list_confirmations(state=allowed)}


@app.post("/api/jobs/{job_id}/cancel")
def api_jobs_cancel(job_id: str):
    result = orchestrator.cancel_job(job_id)
    if not result.get("ok"):
        return JSONResponse(result, status_code=404)
    return result


@app.post("/api/jobs/{job_id}/pause")
def api_jobs_pause(job_id: str):
    result = orchestrator.pause_job(job_id)
    if not result.get("ok"):
        return JSONResponse(result, status_code=404)
    return result


@app.post("/api/jobs/{job_id}/resume")
def api_jobs_resume(job_id: str):
    result = orchestrator.resume_job(job_id)
    if not result.get("ok"):
        return JSONResponse(result, status_code=404)
    return result


@app.post("/api/jobs/{job_id}/steer")
def api_jobs_steer(job_id: str, body: JobSteerIn):
    result = orchestrator.steer_job(job_id, body.instruction)
    if not result.get("ok"):
        code = 400 if "instruction" in str(result.get("error") or "") else 409
        return JSONResponse(result, status_code=code)
    return result


@app.get("/api/activity")
def api_activity(
    turn_id: Optional[str] = None,
    job_id: Optional[str] = None,
    after_seq: int = 0,
    limit: int = 200,
):
    from rau.activity import ACTIVITY

    return {
        "activity": ACTIVITY.list(
            turn_id=turn_id,
            job_id=job_id,
            after_seq=max(0, after_seq),
            limit=max(1, min(1000, limit)),
        )
    }


@app.get("/api/activity/active")
def api_activity_active(limit: int = 200):
    from rau.activity import ACTIVITY

    return {"activity": ACTIVITY.active(limit=max(1, min(1000, limit)))}


@app.get("/api/schedules")
def api_schedules_list():
    return {"schedules": SCHEDULER.store.list_schedules()}


@app.post("/api/schedules")
def api_schedules_create(body: ScheduleIn):
    try:
        return {"ok": True, "schedule": SCHEDULER.create(body.model_dump())}
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.get("/api/schedules/{schedule_id}")
def api_schedule_get(schedule_id: str):
    schedule = SCHEDULER.store.get_schedule(schedule_id)
    if schedule is None:
        return JSONResponse({"ok": False, "error": "unknown schedule"}, status_code=404)
    return {"schedule": schedule}


@app.patch("/api/schedules/{schedule_id}")
def api_schedule_patch(schedule_id: str, body: SchedulePatch):
    try:
        schedule = SCHEDULER.update(
            schedule_id, body.model_dump(exclude_none=True)
        )
        return {"ok": True, "schedule": schedule}
    except KeyError:
        return JSONResponse({"ok": False, "error": "unknown schedule"}, status_code=404)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.delete("/api/schedules/{schedule_id}")
def api_schedule_delete(schedule_id: str):
    if not SCHEDULER.delete(schedule_id):
        return JSONResponse({"ok": False, "error": "unknown schedule"}, status_code=404)
    return {"ok": True, "id": schedule_id}


@app.post("/api/schedules/{schedule_id}/run")
def api_schedule_run(schedule_id: str):
    try:
        return {"ok": True, "run": SCHEDULER.run_now(schedule_id)}
    except KeyError:
        return JSONResponse({"ok": False, "error": "unknown schedule"}, status_code=404)
    except RuntimeError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)


@app.post("/api/schedules/{schedule_id}/pause")
def api_schedule_pause(schedule_id: str):
    try:
        return {"ok": True, "schedule": SCHEDULER.pause(schedule_id)}
    except KeyError:
        return JSONResponse({"ok": False, "error": "unknown schedule"}, status_code=404)


@app.post("/api/schedules/{schedule_id}/resume")
def api_schedule_resume(schedule_id: str):
    try:
        return {"ok": True, "schedule": SCHEDULER.resume(schedule_id)}
    except KeyError:
        return JSONResponse({"ok": False, "error": "unknown schedule"}, status_code=404)


@app.get("/api/schedules/{schedule_id}/runs")
def api_schedule_runs(schedule_id: str, limit: int = 100):
    if SCHEDULER.store.get_schedule(schedule_id) is None:
        return JSONResponse({"ok": False, "error": "unknown schedule"}, status_code=404)
    return {
        "runs": SCHEDULER.store.list_schedule_runs(
            schedule_id, limit=max(1, min(1000, limit))
        )
    }


@app.get("/api/computer/sessions")
def api_computer_sessions():
    from rau.computer.session import COMPUTER

    return COMPUTER.status()


@app.post("/api/computer/sessions")
def api_computer_session_start(body: ComputerSessionIn):
    from rau.computer.session import COMPUTER

    try:
        return {
            "ok": True,
            "session": COMPUTER.start(
                app=body.app,
                frontmost=body.frontmost,
                deadline_sec=body.deadline_sec,
            ),
        }
    except RuntimeError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)


@app.get("/api/computer/sessions/{session_id}")
def api_computer_session_get(session_id: str):
    from rau.computer.session import COMPUTER

    result = COMPUTER.status(session_id)
    if not result.get("ok"):
        return JSONResponse(result, status_code=404)
    return result


@app.post("/api/computer/sessions/{session_id}/observe")
def api_computer_observe(session_id: str, body: ComputerCommandIn):
    from rau.computer.session import COMPUTER

    try:
        return COMPUTER.observe(session_id, **body.payload)
    except (RuntimeError, TypeError, ValueError) as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)


@app.post("/api/computer/sessions/{session_id}/act")
def api_computer_act(session_id: str, body: ComputerCommandIn):
    from rau.computer.session import COMPUTER

    try:
        return COMPUTER.act(session_id, body.payload)
    except (RuntimeError, TypeError, ValueError) as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)


@app.post("/api/computer/sessions/{session_id}/assert")
def api_computer_assert(session_id: str, body: ComputerCommandIn):
    from rau.computer.session import COMPUTER

    try:
        return COMPUTER.assert_condition(session_id, body.payload)
    except (RuntimeError, TypeError, ValueError) as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)


@app.post("/api/computer/sessions/{session_id}/wait")
def api_computer_wait(session_id: str, body: ComputerCommandIn):
    from rau.computer.session import COMPUTER

    payload = dict(body.payload)
    condition = payload.pop("condition", payload)
    try:
        return COMPUTER.wait_for(
            session_id,
            condition,
            timeout_sec=float(payload.get("timeout_sec") or 15.0),
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)


@app.post("/api/computer/sessions/{session_id}/finish")
def api_computer_finish(session_id: str, body: ComputerCommandIn):
    from rau.computer.session import COMPUTER

    try:
        return COMPUTER.finish(
            session_id,
            outcome=str(body.payload.get("outcome") or "completed"),
            summary=str(body.payload.get("summary") or ""),
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)


@app.get("/api/identity")
def api_identity():
    return identity_store.status()


@app.post("/api/identity/fresh")
def api_identity_fresh():
    return identity_store.apply_fresh()


@app.post("/api/identity/hard")
def api_identity_hard(body: IdentityApplyHard):
    return identity_store.apply_hard(body.identity, body.backstory)


@app.post("/api/identity/steer")
def api_identity_steer(body: IdentitySteer):
    return identity_store.hard_steer(body.identity, body.backstory)


@app.get("/api/models")
def api_models_get():
    return load_models()


@app.put("/api/models")
def api_models_put(body: ModelsIn):
    cfg = load_models()
    data = body.model_dump(exclude_none=True)
    for k, v in data.items():
        cfg[k] = {**(cfg.get(k) or {}), **v}
    try:
        return save_models(cfg)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.get("/api/providers/status")
def api_providers():
    return provider_status()


@app.get("/api/models/catalog")
def api_models_catalog():
    return catalog()


@app.get("/api/voice/status")
def api_voice_status():
    """Which STT backend voice mode will actually use, and why."""
    from rau.voice.stt import available_stt, resolve_stt
    from rau.providers.catalog import STT_PROVIDERS

    provider, slot = resolve_stt()
    meta = STT_PROVIDERS.get(provider) or {}
    models = load_models()
    tts = models.get("tts") or {}
    tts_provider = str(tts.get("provider") or "elevenlabs")
    tts_env = (
        "CARTESIA_API_KEY" if tts_provider == "cartesia" else "ELEVENLABS_API_KEY"
    )
    return {
        "stt": {
            "provider": provider,
            "configured_provider": slot.get("_configured_provider") or provider,
            "model": slot.get("model") or "",
            "language": slot.get("language") or "",
            # True when the configured backend was unusable and we fell back.
            "fallback": bool(slot.get("_fallback")),
            "partials": bool(meta.get("partials")),
            "label": meta.get("label") or provider,
            "reason": slot.get("_reason") or "",
        },
        "available": available_stt(),
        "tts_ready": has_secret(tts_env),
        "tts": {
            "provider": tts_provider,
            "voice_id": tts.get("voice_id") or "",
            "model": tts.get("model") or "",
            "preset": tts.get("preset") or "",
            "effect": tts.get("effect") or "none",
        },
    }


@app.get("/api/voice/voices")
def api_voice_voices(provider: str = "elevenlabs"):
    """Voices visible to the selected provider key."""
    if provider not in ("elevenlabs", "cartesia"):
        return JSONResponse(
            {"ok": False, "error": "Unsupported TTS provider."}, status_code=400
        )
    env_name = (
        "CARTESIA_API_KEY" if provider == "cartesia" else "ELEVENLABS_API_KEY"
    )
    label = "Cartesia" if provider == "cartesia" else "ElevenLabs"
    if not has_secret(env_name):
        return JSONResponse(
            {"ok": False, "error": f"Connect a {label} API key first."},
            status_code=409,
        )
    try:
        from rau.voice.tts_api import list_voices

        return {"ok": True, "voices": list_voices(provider)}
    except Exception as exc:  # noqa: BLE001 — provider detail belongs in settings
        return JSONResponse(
            {"ok": False, "error": f"Could not load {label} voices: {str(exc)[:300]}"},
            status_code=502,
        )


@app.post("/api/voice/preview")
def api_voice_preview(body: VoicePreviewIn):
    """Synthesize a short sample using the exact pending settings."""
    env_name = (
        "CARTESIA_API_KEY"
        if body.provider == "cartesia"
        else "ELEVENLABS_API_KEY"
    )
    label = "Cartesia" if body.provider == "cartesia" else "ElevenLabs"
    if not has_secret(env_name):
        return JSONResponse(
            {"ok": False, "error": f"Connect a {label} API key first."},
            status_code=409,
        )
    text = body.text.strip()
    if not text:
        # Whitespace-only input passes min_length=1 but synthesises nothing;
        # reject it here instead of burning a billed API call on empty text.
        return JSONResponse({"ok": False, "error": "text is empty"}, status_code=400)
    try:
        # Apply the same validation as persisted settings without modifying the
        # user's models.json.
        cfg = load_models()
        model = body.model.strip() or (
            "sonic-3.5" if body.provider == "cartesia" else "eleven_flash_v2_5"
        )
        cfg["tts"] = {
            "provider": body.provider,
            "voice_id": body.voice_id,
            "model": model,
            "preset": "preview",
            "effect": body.effect,
            "voice_settings": body.voice_settings,
        }
        from rau.providers.registry import _validated_models
        from rau.voice.tts_api import render_preview

        checked = _validated_models(cfg)["tts"]
        wav = render_preview(
            provider=str(checked["provider"]),
            text=text,
            voice_id=str(checked["voice_id"]),
            model=str(checked["model"]),
            effect=str(checked["effect"]),
            voice_settings=dict(checked["voice_settings"]),
        )
        return Response(
            content=wav,
            media_type="audio/wav",
            headers={"Cache-Control": "no-store"},
        )
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    except Exception as exc:  # noqa: BLE001 — surface provider failures to settings
        return JSONResponse(
            {"ok": False, "error": f"Voice preview failed: {str(exc)[:300]}"},
            status_code=502,
        )


@app.get("/api/browse/status")
def api_browse_status():
    """Which web-browsing backend a request would actually use, and why."""
    from rau.browse import status as browse_status

    return browse_status()


@app.get("/api/effort")
def api_effort_get():
    from rau.providers.reasoning import effort_snapshot

    return effort_snapshot(load_models())


@app.get("/api/resource-profile")
def api_resource_profile_get():
    from rau.resources import current_profile

    return current_profile()


@app.put("/api/resource-profile")
def api_resource_profile_put(body: ResourceProfileIn):
    from rau.resources import profile_policy

    settings = load_settings()
    settings["resource_profile"] = body.profile
    save_settings(settings)
    profile = profile_policy(body.profile)
    BUS.emit("resource_profile", profile=profile)
    return profile


@app.put("/api/effort")
def api_effort_put(body: EffortIn):
    from rau.providers.reasoning import clamp_effort, reasoning_for

    models = load_models()
    data = body.model_dump(exclude_none=True)

    def _apply(slot: str, level: str) -> Optional[str]:
        slot_cfg = models.setdefault(slot, {})
        provider = str(slot_cfg.get("provider") or "openrouter")
        model = str(slot_cfg.get("model") or "")
        cap = reasoning_for(provider, model)
        if not cap.get("supported"):
            return f"{slot}: this model has no reasoning control"
        allowed = list(cap.get("levels") or [])
        if level not in allowed:
            return (
                f"{slot}: effort {level!r} not allowed "
                f"(allowed: {', '.join(allowed) or 'none'})"
            )
        clamped = clamp_effort(provider, model, level)
        if clamped is None:
            return f"{slot}: this model has no reasoning control"
        slot_cfg["effort"] = clamped
        return None

    if "all" in data:
        level = str(data["all"]).lower()
        if level not in EFFORT_LEVELS:
            return JSONResponse({"ok": False, "error": "invalid effort"}, status_code=400)
        errors = []
        for slot in _EFFORT_SLOTS:
            err = _apply(slot, level)
            if err:
                errors.append(err)
        if len(errors) == len(_EFFORT_SLOTS):
            return JSONResponse(
                {"ok": False, "error": "; ".join(errors)}, status_code=400
            )
    for slot in _EFFORT_SLOTS:
        if slot in data:
            level = str(data[slot]).lower()
            if level not in EFFORT_LEVELS:
                return JSONResponse(
                    {"ok": False, "error": f"invalid effort for {slot}"},
                    status_code=400,
                )
            err = _apply(slot, level)
            if err:
                return JSONResponse({"ok": False, "error": err}, status_code=400)
    save_models(models)
    return api_effort_get()


@app.get("/api/skills")
def api_skills():
    return {"skills": skills_public()}


@app.get("/api/skills/{name}")
def api_skill_get(name: str):
    skill = load_skill(name)
    if not skill:
        return JSONResponse({"ok": False, "error": "unknown skill"}, status_code=404)
    return {
        "name": skill.name,
        "description": skill.description,
        "slash": skill.slash,
        "always": skill.always,
        "body": skill.body,
    }


@app.get("/api/goal")
def api_goal_get():
    return {"goal": goal_store.get_goal()}


@app.put("/api/goal")
def api_goal_put(body: GoalIn):
    goal = goal_store.set_goal(body.text)
    if goal.get("ok") is False:
        return JSONResponse(goal, status_code=400)
    return {"ok": True, "goal": goal}


@app.delete("/api/goal")
def api_goal_delete():
    return goal_store.clear_goal()


@app.post("/api/goal/note")
def api_goal_note(body: GoalNoteIn):
    return goal_store.add_note(body.text)


@app.get("/api/setup/state")
def api_setup_state():
    """Everything the setup wizard needs to decide which steps are already done."""
    providers = auth_status()
    configured = {p["id"] for p in providers if p.get("configured")}
    models = load_models()

    def slot_ok(slot: str) -> bool:
        cfg = models.get(slot) or {}
        prov = cfg.get("provider") or ""
        auth_slot = PROVIDER_AUTH.get(prov)
        return bool(cfg.get("model")) and auth_slot in configured

    brains_ready = bool(configured & set(PROVIDER_AUTH.values()))
    models_ready = all(slot_ok(s) for s in ("face", "subagent", "dream"))
    identity = identity_store.status()

    return {
        "identity_ready": bool(identity.get("ready")),
        "brains_ready": brains_ready,
        "models_ready": models_ready,
        "voice_ready": bool({"elevenlabs", "cartesia"} & configured),
        "apps_ready": "composio" in configured,
        "complete": bool(identity.get("ready")) and brains_ready and models_ready,
        "configured": sorted(configured),
        "providers": providers,
        "models": models,
        "identity": {
            "has_identity": identity.get("has_identity"),
            "has_backstory": identity.get("has_backstory"),
            "has_soul": identity.get("has_soul"),
            "identity_text": identity.get("identity") or "",
            "backstory_text": identity.get("backstory") or "",
        },
        "examples": identity.get("examples") or {},
    }


@app.get("/api/auth")
def api_auth_list():
    return {"providers": auth_status()}


@app.put("/api/auth/{provider_id}")
def api_auth_set(provider_id: str, body: AuthKeyIn):
    slot = slot_by_id(provider_id)
    if not slot:
        return JSONResponse({"ok": False, "error": "unknown provider"}, status_code=404)
    try:
        result = set_secret(slot["env"], body.key)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    return {"ok": True, "provider": provider_id, **result, "providers": auth_status()}


@app.delete("/api/auth/{provider_id}")
def api_auth_clear(provider_id: str):
    slot = slot_by_id(provider_id)
    if not slot:
        return JSONResponse({"ok": False, "error": "unknown provider"}, status_code=404)
    result = clear_secret(slot["env"])
    return {"ok": True, "provider": provider_id, **result, "providers": auth_status()}


@app.post("/api/auth/{provider_id}/verify")
def api_auth_verify(provider_id: str, body: Optional[AuthVerifyIn] = None):
    """Prove a key actually works before the wizard lets you move on.

    Sends `key` when given (check-before-save), otherwise checks the stored one.
    """
    if not slot_by_id(provider_id):
        return JSONResponse({"ok": False, "error": "unknown provider"}, status_code=404)
    return provider_verify.verify(provider_id, body.key if body else None)


@app.post("/api/auth/composio/connect")
def api_composio_connect():
    """Return URL(s) to open Composio auth / app connections."""
    result = MCP.composio_connect()
    return result


@app.get("/api/mcp/status")
def api_mcp():
    return MCP.status()


@app.get("/api/memory")
def api_memory():
    return memory_store.summary()


@app.post("/api/dream/run")
def api_dream_run():
    try:
        result = run_dream()
    except Exception:
        log.exception("dream run failed")
        return JSONResponse(
            {"ok": False, "error": "dream run failed"}, status_code=500
        )
    # run_dream() holds a non-blocking lock: a second trigger while one is in
    # flight is a conflict, not a failure.
    if isinstance(result, dict) and result.get("status") == "already_running":
        return JSONResponse(result, status_code=409)
    return result


@app.get("/api/settings")
def api_settings():
    return load_settings()


@app.get("/api/permissions")
def api_permissions_get():
    perms = get_permissions()
    return {"permissions": perms, "mode": global_mode(perms)}


@app.put("/api/permissions")
def api_permissions_put(body: PermissionsIn):
    partial = body.model_dump(exclude_none=True)
    if not partial:
        perms = get_permissions()
        return {"ok": True, "permissions": perms, "mode": global_mode(perms)}
    try:
        permissions = set_permissions(partial)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return {
        "ok": True,
        "permissions": permissions,
        "mode": global_mode(permissions),
    }


class PetVisibilityBody(BaseModel):
    """Face mutex and menu-bar hide/show for the desktop pet."""

    face_open: Optional[bool] = None
    user_hidden: Optional[bool] = None
    visible: Optional[bool] = None


@app.get("/api/pet")
def api_get_pet():
    return state.get_pet()


@app.post("/api/pet/visibility")
def api_pet_visibility(body: PetVisibilityBody):
    kwargs: Dict[str, Any] = {}
    if body.face_open is not None:
        kwargs["face_open"] = body.face_open
    if body.user_hidden is not None:
        kwargs["user_hidden"] = body.user_hidden
    elif body.visible is not None:
        # Convenience: visible=false ⇒ user hide; visible=true ⇒ clear user hide.
        kwargs["user_hidden"] = not bool(body.visible)
    snap = state.set_pet_visibility(**kwargs)
    BUS.emit("pet_visibility", **snap)
    return {"ok": True, **snap}


@app.post("/api/chat")
def api_chat(body: ChatIn):
    """
    Text face turn (dashboard / --text mode).

    The reply still comes back whole in the HTTP response — every existing
    caller keeps working — but it is also streamed over `/ws` as turn-scoped
    `chat_started` / `chat_delta` / `chat_done` events, so a body plan anchored
    to a phrase fires when that phrase actually becomes visible rather than
    when the whole answer lands at once.
    """
    from rau.face import brain, choreography
    from rau.heartbeat.presence import note_user_reply

    text = (body.text or "").strip()
    if not text:
        return JSONResponse({"ok": False, "error": "empty"}, status_code=400)
    note_user_reply()
    turn_id = choreography.new_turn_id()
    state.add_log("user", text, turn_id)
    try:
        # The broadcast lives inside chat_streaming; nothing extra to do here.
        reply = str(brain.chat_streaming(text, on_token=lambda _t: None, turn_id=turn_id))
    except brain.Cancelled as cancelled:
        # Newest user turn wins. Let an already-started tool settle internally,
        # retain only the interrupted history marker, and never enqueue stale
        # text/TTS after the replacement request.
        brain.finish_interrupted_turn(cancelled, cancelled.generated)
        return {
            "ok": True,
            "reply": "",
            "turn_id": turn_id,
            "interrupted": True,
        }
    except Exception:
        # The raw exception can carry provider URLs, keys, or internals — log
        # it, but answer in-voice without the detail.
        log.exception("chat turn failed")
        reply = "I hit a snag thinking. Give me a moment and try again."
    state.add_log("rau", reply, turn_id)
    # Sticky mood / runtime emotion already applied inside chat_streaming.
    emo = state.get_emotion()
    state.set_emotion(str(emo.get("emotion") or "curious"), reply)
    state.push_control({"action": "speak", "text": reply})
    return {"ok": True, "reply": reply, "turn_id": turn_id}


@app.get("/api/room/props")
def api_room_props():
    """Where every movable object in the room currently is."""
    from rau.face import props

    return {"layout": props.layout(), "props": props.PROPS, "spots": props.SPOTS}


@app.post("/api/room/props/reset")
def api_room_props_reset():
    from rau.face import props

    return {"ok": True, "layout": props.reset_layout()}


@app.get("/api/game/kittens")
def api_kittens_state():
    """
    The table as you are allowed to see it.

    Only needed on load and after a reconnect — every change is pushed over
    `/ws` as `game_state`. The payload is redacted in `rau/games/kittens/view.py`
    before it leaves the process, not in the component that renders it, because
    a websocket frame is one devtools panel away from being read.
    """
    from rau.games.kittens import session as kittens

    return {"ok": True, "state": kittens.state(), "record": kittens.tally()}


@app.post("/api/game/kittens")
def api_kittens_start():
    from rau.games.kittens import session as kittens

    if kittens.active():
        return {"ok": True, "state": kittens.state()}
    return {"ok": True, "state": kittens.start()}


@app.delete("/api/game/kittens")
def api_kittens_end():
    from rau.games.kittens import session as kittens

    return kittens.end("cleared from the table")


@app.post("/api/game/kittens/move")
def api_kittens_move(body: Dict[str, Any]):
    """
    Your move.

    Applied synchronously so the answer is the new table rather than a promise
    of one. Rau's reply is not part of this response: it arrives as an ordinary
    streamed chat turn a moment later, which is what makes this feel like
    playing him instead of pressing a button.
    """
    from rau.games.kittens import session as kittens
    from rau.games.kittens.engine import USER

    result = kittens.apply_move(USER, body or {})
    if not result.get("ok"):
        return JSONResponse(result, status_code=400)
    return result


@app.get("/api/game/chess")
def api_chess_state():
    """
    The board as it stands.

    Nothing here is redacted, because chess has nothing to hide: both players
    are looking at the same position. The client is still told rather than
    asked — it never works out what is legal, it sends a move and finds out.
    """
    from rau.games.chess import session as chess_session

    return {"ok": True, "state": chess_session.state(), "record": chess_session.tally()}


@app.post("/api/game/chess")
def api_chess_start(body: Optional[Dict[str, Any]] = None):
    """
    Set the board up.

    An unfinished game on disk is preferred to a new one: walking away from a
    game and coming back to a fresh position would be worse than useless, it
    would be a small betrayal. `resume` returns None when there is nothing to
    come back to.
    """
    from rau.games.chess import session as chess_session

    if chess_session.active():
        return {"ok": True, "state": chess_session.state()}
    # `resume` treats any game already in memory as the thing to hand back,
    # including a finished one — which is right for the boot path it was written
    # for and wrong here. A board someone is looking at the end of is the exact
    # moment they press play again, so only reach for the disk when the table is
    # genuinely empty.
    if chess_session.current() is None:
        resumed = chess_session.resume()
        if resumed is not None:
            return {"ok": True, "state": resumed, "resumed": True}
    # None when the page expressed no preference, which is the common case and
    # the one that alternates: he takes the other colour from last game.
    colour = (body or {}).get("rau_color")
    return {"ok": True, "state": chess_session.start(rau_color=str(colour) if colour else None)}


@app.delete("/api/game/chess")
def api_chess_end():
    from rau.games.chess import session as chess_session

    return chess_session.end("cleared from the table")


@app.post("/api/game/chess/move")
def api_chess_move(body: Dict[str, Any]):
    """
    Your move.

    Applied synchronously, so a refusal comes back on this call rather than as
    a surprise a second later — the piece has to snap back to where it started
    while your hand is still on it. His reply is not part of this response: he
    takes his time over it, and the taking of time is the point.
    """
    from rau.games.chess import session as chess_session
    from rau.games.chess.board import USER

    result = chess_session.apply_move(USER, body or {})
    if not result.get("ok"):
        return JSONResponse(result, status_code=400)
    return result


@app.get("/api/panels")
def api_panels():
    from rau.face import panels

    return {"panels": panels.list_panels()}


@app.get("/api/panels/{panel_id}")
def api_panel(panel_id: str):
    """
    The panel document itself.

    Served as its own document so the browser can mount it in a sandboxed
    frame. It carries the same Content-Security-Policy as the inline copy, as
    a response header this time, so the rules hold however it is reached.
    """
    from rau.face import panels

    panel = panels.get_panel(panel_id)
    if not panel:
        return JSONResponse({"ok": False, "error": "unknown panel"}, status_code=404)
    return HTMLResponse(
        panel["document"],
        headers={
            "Content-Security-Policy": panels.CSP,
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            # It is only ever framed by this app, from this origin.
            "X-Frame-Options": "SAMEORIGIN",
            "Cache-Control": "no-store",
        },
    )


@app.delete("/api/panels")
def api_panels_clear():
    from rau.face import panels

    panels.clear_panels()
    return {"ok": True}


@app.delete("/api/panels/{panel_id}")
def api_panel_close(panel_id: str):
    """Take one panel down. Permanent — there is no archive to restore from."""
    from rau.face import panels

    result = panels.close_panel(panel_id)
    if not result.get("ok"):
        return JSONResponse(result, status_code=404)
    return result


@app.get("/api/events/history")
def api_events():
    return {"events": BUS.history(80)}


@app.websocket("/ws/voice")
async def ws_voice(ws: WebSocket):
    """
    Live voice: binary frames up are mic PCM16 @16k, binary frames down are
    TTS PCM16 @24k. Control travels as JSON alongside.
    """
    from rau.voice.session import VoiceSession, session_info, warm_voice

    await ws.accept()
    requested_profile = str(ws.query_params.get("profile") or "normal").lower()
    if requested_profile not in ("normal", "hyper"):
        requested_profile = "normal"
    session = VoiceSession(
        ws.send_json,
        ws.send_bytes,
        profile=requested_profile,
    )
    # In the background: first-turn latency is most visible, so warm TTS/LLM
    # clients before the user speaks rather than on the first reply.
    warm_voice()

    # The host-side mic loop and a browser session must not both listen, or
    # every utterance is transcribed twice.
    state.acquire_browser_voice()

    try:
        await ws.send_json({"t": "hello", **session_info(session.profile)})
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break

            data = msg.get("bytes")
            if data is not None:
                error = session.feed(data)
                if error:
                    # feed() closes the mic itself when the stream is dead
                    # (utterance cap, consumer stall); any other error is one
                    # bad frame — report it and keep listening rather than
                    # tearing the whole utterance down.
                    mic = session._mic
                    await session.send(t="error", detail=f"audio: {error}")
                    if mic is None or mic.closed:
                        await session.stop_stt()
                        await session.set_phase("idle")
                continue

            raw = msg.get("text")
            if raw is None:
                continue
            if len(raw) > 65_536:
                await session.send(t="error", detail="voice command is too large")
                continue
            try:
                cmd = json.loads(raw)
            except json.JSONDecodeError:
                await session.send(t="error", detail="invalid voice command JSON")
                continue
            if not isinstance(cmd, dict):
                await session.send(t="error", detail="voice command must be an object")
                continue

            kind = cmd.get("t")
            try:
                if kind == "speech_start":
                    await session.speech_start()
                elif kind == "speech_end":
                    await session.speech_end()
                elif kind == "barge":
                    played = cmd.get("playedMs", 0)
                    if isinstance(played, bool) or not isinstance(played, (int, float)):
                        raise ValueError("playedMs must be a number")
                    await session.barge(float(played))
                elif kind == "text":
                    # Typed input while in voice mode — same turn machinery.
                    value = cmd.get("text")
                    if not isinstance(value, str):
                        raise ValueError("text must be a string")
                    text = value.strip()
                    if len(text) > 16_000:
                        raise ValueError("text is too long")
                    if text:
                        await session.begin_turn(text)
                elif kind == "stop":
                    await session.stop()
                elif kind == "profile":
                    profile = cmd.get("profile")
                    if not isinstance(profile, str):
                        raise ValueError("profile must be a string")
                    session.set_profile(profile.lower())
                    await session.send(t="profile", profile=session.profile)
                elif kind == "latency_report":
                    turn_id = cmd.get("turn_id")
                    value = cmd.get("eou_to_playback_ms")
                    profile = cmd.get("profile")
                    if not isinstance(turn_id, str):
                        raise ValueError("turn_id must be a string")
                    if (
                        isinstance(value, bool)
                        or not isinstance(value, (int, float))
                    ):
                        raise ValueError("eou_to_playback_ms must be a number")
                    if not isinstance(profile, str):
                        raise ValueError("profile must be a string")
                    session.record_latency_report(
                        turn_id=turn_id,
                        eou_to_playback_ms=float(value),
                        profile=profile.lower(),
                    )
                else:
                    raise ValueError("unknown voice command")
            except (TypeError, ValueError) as e:
                await session.send(t="error", detail=str(e))
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001 — never let one socket kill the hub
        # Raw exception text can leak internals; the client only needs to know
        # the session errored.
        log.exception("voice websocket failed")
        try:
            await ws.send_json({"t": "error", "detail": "internal voice error"})
        except Exception:
            pass
    finally:
        try:
            await session.close()
        finally:
            state.release_browser_voice()


def _live_status() -> Dict[str, Any]:
    snap = state.status_snapshot()
    perms = get_permissions()
    snap["permissions"] = perms
    snap["permission_mode"] = global_mode(perms)
    return snap


@app.websocket("/ws")
async def ws_events(ws: WebSocket):
    await ws.accept()
    q = BUS.subscribe_async()
    try:
        await ws.send_json({"kind": "hello", "status": _live_status()})
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=15.0)
                await ws.send_json(event)
            except asyncio.TimeoutError:
                await ws.send_json({"kind": "ping", "status": _live_status()})
    except (WebSocketDisconnect, OSError, RuntimeError):
        # All three are one event — the client vanished mid-send (abrupt tab
        # close surfaces as ClientDisconnected, an OSError, or as a RuntimeError
        # from sending after the close frame). Nothing to do but unsubscribe.
        pass
    finally:
        BUS.unsubscribe_async(q)


def _index_path() -> Optional[Path]:
    idx = WEB_DIST / "index.html"
    return idx if idx.exists() else None


@app.get("/")
async def root():
    idx = _index_path()
    if idx:
        return FileResponse(idx)
    return JSONResponse(
        {
            "name": "Rau",
            "message": "Web UI not built yet. Run: cd web && npm run build",
            "identity_ready": identity_store.has_soul(),
        }
    )


# SPA fallback + static assets
if WEB_DIST.exists():
    assets = WEB_DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    _web_root = WEB_DIST.resolve()

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        if full_path.startswith("api/") or full_path == "ws":
            return JSONResponse({"error": "not found"}, status_code=404)
        # full_path is client-controlled: "../" segments (the server decodes
        # %2e%2e%2f before routing) must never resolve outside the built UI
        # tree, or any readable file on the machine becomes downloadable.
        candidate = (_web_root / full_path).resolve()
        if candidate.is_relative_to(_web_root) and candidate.is_file():
            return FileResponse(candidate)
        idx = _index_path()
        if idx:
            return FileResponse(idx)
        return JSONResponse({"error": "not built"}, status_code=404)


def main() -> None:
    import uvicorn

    os.environ.setdefault("RAU_RUNTIME", "1")
    settings = load_settings()
    host = settings.get("hub_host") or "127.0.0.1"
    port = int(settings.get("hub_port") or 8765)
    print(f"Rau Hub: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
