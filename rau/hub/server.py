"""Rau local hub — HTTP + WebSocket API, serves web/dist."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
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
from rau.identity import store as identity_store
from rau.mcp.client import MCP
from rau.memory import store as memory_store
from rau.paths import WEB_DIST, ensure_dirs
from rau.providers.catalog import PROVIDER_AUTH, catalog
from rau.providers.registry import (
    EFFORT_LEVELS,
    load_models,
    load_settings,
    provider_status,
    save_models,
)
from rau.providers import verify as provider_verify
from rau.skills import goals as goal_store
from rau.skills.loader import load_skill, skills_public
from rau import state

load_dotenv(override=False)
ensure_dirs()

app = FastAPI(title="Rau Hub", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class EmotionIn(BaseModel):
    emotion: str = "idle"
    text: str = ""


class LogIn(BaseModel):
    role: str = "user"
    text: str = ""


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


class IdentityApplyFresh(BaseModel):
    mode: str = "fresh"


class IdentityApplyHard(BaseModel):
    identity: str
    backstory: str


class IdentitySteer(BaseModel):
    identity: Optional[str] = None
    backstory: Optional[str] = None


class ModelsIn(BaseModel):
    face: Optional[Dict[str, Any]] = None
    subagent: Optional[Dict[str, Any]] = None
    dream: Optional[Dict[str, Any]] = None
    tts: Optional[Dict[str, Any]] = None
    stt: Optional[Dict[str, Any]] = None


class ConfirmIn(BaseModel):
    approved: bool
    id: Optional[str] = None


class ChatIn(BaseModel):
    text: str


class AuthKeyIn(BaseModel):
    key: str


class AuthVerifyIn(BaseModel):
    key: Optional[str] = None


class EffortIn(BaseModel):
    face: Optional[str] = None
    subagent: Optional[str] = None
    dream: Optional[str] = None
    all: Optional[str] = None


class GoalIn(BaseModel):
    text: str


class GoalNoteIn(BaseModel):
    text: str


@app.on_event("startup")
async def _startup() -> None:
    start_dreamer()
    start_heartbeat()


@app.get("/api/status")
def api_status():
    snap = state.status_snapshot()
    snap["eye_server"] = True
    snap["identity_ready"] = identity_store.has_soul()
    snap["providers"] = provider_status()
    snap["mcp"] = MCP.status()
    snap["memory"] = memory_store.summary()
    models = load_models()
    snap["effort"] = {
        "face": (models.get("face") or {}).get("effort") or "medium",
        "subagent": (models.get("subagent") or {}).get("effort") or "high",
        "dream": (models.get("dream") or {}).get("effort") or "medium",
        "levels": list(EFFORT_LEVELS),
    }
    snap["goal"] = goal_store.get_goal()
    snap["skills_count"] = len(skills_public())
    return snap


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
    return orchestrator.start_hard_task(body.goal)


@app.post("/api/hard-task/cancel")
def api_hard_task_cancel():
    return orchestrator.cancel_hard_task()


@app.post("/api/hard-task/redirect")
def api_hard_task_redirect(body: HardTaskIn):
    return orchestrator.redirect_hard_task(body.goal)


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
        bad_input = result.get("reason") == "empty_goal"
        return JSONResponse(result, status_code=400 if bad_input else 409)
    return result


@app.post("/api/jobs/{job_id}/cancel")
def api_jobs_cancel(job_id: str):
    result = orchestrator.cancel_job(job_id)
    if not result.get("ok"):
        return JSONResponse(result, status_code=404)
    return result


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
    return save_models(cfg)


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
    return {
        "stt": {
            "provider": provider,
            "model": slot.get("model") or "",
            "language": slot.get("language") or "",
            # True when the configured backend was unusable and we fell back.
            "fallback": bool(slot.get("_fallback")),
            "partials": bool(meta.get("partials")),
            "label": meta.get("label") or provider,
        },
        "available": available_stt(),
        "tts_ready": has_secret("ELEVENLABS_API_KEY"),
    }


@app.get("/api/effort")
def api_effort_get():
    models = load_models()
    return {
        "face": (models.get("face") or {}).get("effort") or "medium",
        "subagent": (models.get("subagent") or {}).get("effort") or "high",
        "dream": (models.get("dream") or {}).get("effort") or "medium",
        "levels": list(EFFORT_LEVELS),
    }


@app.put("/api/effort")
def api_effort_put(body: EffortIn):
    models = load_models()
    data = body.model_dump(exclude_none=True)
    if "all" in data:
        level = str(data["all"]).lower()
        if level not in EFFORT_LEVELS:
            return JSONResponse({"ok": False, "error": "invalid effort"}, status_code=400)
        for slot in ("face", "subagent", "dream"):
            models.setdefault(slot, {})["effort"] = level
    for slot in ("face", "subagent", "dream"):
        if slot in data:
            level = str(data[slot]).lower()
            if level not in EFFORT_LEVELS:
                return JSONResponse({"ok": False, "error": f"invalid effort for {slot}"}, status_code=400)
            models.setdefault(slot, {})["effort"] = level
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
    return {"ok": True, "goal": goal_store.set_goal(body.text)}


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
        "voice_ready": "elevenlabs" in configured,
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
        return run_dream()
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/api/settings")
def api_settings():
    return load_settings()


@app.post("/api/chat")
def api_chat(body: ChatIn):
    """Text face turn (dashboard / --text mode)."""
    from rau.face import brain
    from rau.heartbeat.presence import note_user_reply

    text = (body.text or "").strip()
    if not text:
        return JSONResponse({"ok": False, "error": "empty"}, status_code=400)
    note_user_reply()
    state.add_log("user", text)
    try:
        reply = brain.chat(text)
    except Exception as e:
        reply = f"I hit a snag thinking: {e}"
    state.add_log("rau", reply)
    state.set_emotion("curious", reply)
    state.push_control({"action": "speak", "text": reply})
    return {"ok": True, "reply": reply}


@app.get("/api/events/history")
def api_events():
    return {"events": BUS.history(80)}


@app.websocket("/ws/voice")
async def ws_voice(ws: WebSocket):
    """
    Live voice: binary frames up are mic PCM16 @16k, binary frames down are
    TTS PCM16 @24k. Control travels as JSON alongside.
    """
    from rau.voice.session import VoiceSession, session_info

    await ws.accept()
    session = VoiceSession(ws.send_json, ws.send_bytes)

    # The host-side mic loop and a browser session must not both listen, or
    # every utterance is transcribed twice.
    was_listening = bool(state.status_snapshot().get("listening"))
    if was_listening:
        state.set_listening(False)

    try:
        await ws.send_json({"t": "hello", **session_info()})
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break

            data = msg.get("bytes")
            if data:
                session.feed(data)
                continue

            raw = msg.get("text")
            if not raw:
                continue
            try:
                cmd = json.loads(raw)
            except json.JSONDecodeError:
                continue

            kind = cmd.get("t")
            if kind == "speech_start":
                await session.speech_start()
            elif kind == "speech_end":
                await session.speech_end()
            elif kind == "barge":
                await session.barge(float(cmd.get("playedMs") or 0))
            elif kind == "text":
                # Typed input while in voice mode — same turn machinery.
                text = str(cmd.get("text") or "").strip()
                if text:
                    await session.begin_turn(text)
            elif kind == "stop":
                await session.stop_stt()
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001 — never let one socket kill the hub
        try:
            await ws.send_json({"t": "error", "detail": str(e)})
        except Exception:
            pass
    finally:
        await session.close()
        if was_listening:
            state.set_listening(True)


@app.websocket("/ws")
async def ws_events(ws: WebSocket):
    await ws.accept()
    q = BUS.subscribe_async()
    try:
        await ws.send_json({"kind": "hello", "status": state.status_snapshot()})
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=15.0)
                await ws.send_json(event)
            except asyncio.TimeoutError:
                await ws.send_json({"kind": "ping", "status": state.status_snapshot()})
    except WebSocketDisconnect:
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

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        if full_path.startswith("api/") or full_path == "ws":
            return JSONResponse({"error": "not found"}, status_code=404)
        candidate = WEB_DIST / full_path
        if candidate.exists() and candidate.is_file():
            return FileResponse(candidate)
        idx = _index_path()
        if idx:
            return FileResponse(idx)
        return JSONResponse({"error": "not built"}, status_code=404)


def main() -> None:
    import uvicorn

    settings = load_settings()
    host = settings.get("hub_host") or "127.0.0.1"
    port = int(settings.get("hub_port") or 8765)
    print(f"Rau Hub: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
