"""Rau local hub — HTTP + WebSocket API, serves web/dist."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
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
)
from rau.providers import verify as provider_verify
from rau.skills import goals as goal_store
from rau.skills.loader import load_skill, skills_public
from rau import state

load_dotenv(override=False)
ensure_dirs()

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
    all: Optional[str] = None


class GoalIn(BaseModel):
    text: str = Field(min_length=1, max_length=4_000)


class GoalNoteIn(BaseModel):
    text: str


class VoicePreviewIn(BaseModel):
    text: str = Field(
        default="Hello, I am Rau. Voice systems are online.",
        min_length=1,
        max_length=240,
    )
    voice_id: str = Field(min_length=3, max_length=128)
    model: str = Field(default="eleven_flash_v2_5", min_length=3, max_length=128)
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
    start_dreamer()
    start_heartbeat()
    settings = load_settings()
    port = int(settings.get("hub_port") or 8765)
    # The pet is a client, so it needs an address it can dial. A wildcard bind
    # is a listening address, not a destination — handing it through leaves the
    # pet trying to connect to 0.0.0.0 and silently never arriving.
    host = str(settings.get("hub_host") or "127.0.0.1")
    if host in ("", "0.0.0.0", "::", "[::]"):
        host = "127.0.0.1"
    try:
        if start_pet(f"http://{host}:{port}"):
            print(f"Desktop pet: {pet_binary()}")
    except Exception as exc:  # noqa: BLE001
        # A cosmetic companion window must never be the reason the hub —
        # and with it the whole app — refuses to come up.
        print(f"Desktop pet not started: {exc}")


@app.get("/api/status")
def api_status():
    snap = state.status_snapshot()
    snap["eye_server"] = True
    snap["identity_ready"] = identity_store.has_soul()
    snap["providers"] = provider_status()
    snap["mcp"] = MCP.status()
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
        "tts_ready": has_secret("ELEVENLABS_API_KEY"),
        "tts": {
            "voice_id": (load_models().get("tts") or {}).get("voice_id") or "",
            "preset": (load_models().get("tts") or {}).get("preset") or "",
            "effect": (load_models().get("tts") or {}).get("effect") or "none",
        },
    }


@app.get("/api/voice/voices")
def api_voice_voices():
    """Voices visible to the saved ElevenLabs key, including user-created ones."""
    if not has_secret("ELEVENLABS_API_KEY"):
        return JSONResponse(
            {"ok": False, "error": "Connect an ElevenLabs API key first."},
            status_code=409,
        )
    try:
        from rau.voice.elevenlabs_api import list_voices

        return {"ok": True, "voices": list_voices()}
    except Exception as exc:  # noqa: BLE001 — provider detail belongs in settings
        return JSONResponse(
            {"ok": False, "error": f"Could not load ElevenLabs voices: {str(exc)[:300]}"},
            status_code=502,
        )


@app.post("/api/voice/preview")
def api_voice_preview(body: VoicePreviewIn):
    """Synthesize a short sample using the exact pending settings."""
    if not has_secret("ELEVENLABS_API_KEY"):
        return JSONResponse(
            {"ok": False, "error": "Connect an ElevenLabs API key first."},
            status_code=409,
        )
    try:
        # Apply the same validation as persisted settings without modifying the
        # user's models.json.
        cfg = load_models()
        cfg["tts"] = {
            "provider": "elevenlabs",
            "voice_id": body.voice_id,
            "model": body.model,
            "preset": "preview",
            "effect": body.effect,
            "voice_settings": body.voice_settings,
        }
        from rau.providers.registry import _validated_models
        from rau.voice.elevenlabs_api import render_preview

        checked = _validated_models(cfg)["tts"]
        wav = render_preview(
            text=body.text.strip(),
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


@app.get("/api/effort")
def api_effort_get():
    from rau.providers.reasoning import effort_snapshot

    return effort_snapshot(load_models())


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
        for slot in ("face", "subagent", "dream"):
            err = _apply(slot, level)
            if err:
                errors.append(err)
        if len(errors) == 3:
            return JSONResponse(
                {"ok": False, "error": "; ".join(errors)}, status_code=400
            )
    for slot in ("face", "subagent", "dream"):
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
    state.add_log("user", text)
    turn_id = choreography.new_turn_id()
    try:
        # The broadcast lives inside chat_streaming; nothing extra to do here.
        reply = str(brain.chat_streaming(text, on_token=lambda _t: None, turn_id=turn_id))
    except Exception as e:
        reply = f"I hit a snag thinking: {e}"
    state.add_log("rau", reply)
    # Sticky mood / runtime emotion already applied inside chat_streaming.
    emo = state.get_emotion()
    state.set_emotion(str(emo.get("emotion") or "curious"), reply)
    state.push_control({"action": "speak", "text": reply})
    return {"ok": True, "reply": reply, "turn_id": turn_id}


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
    state.acquire_browser_voice()

    try:
        await ws.send_json({"t": "hello", **session_info()})
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break

            data = msg.get("bytes")
            if data is not None:
                error = session.feed(data)
                if error:
                    await session.send(t="error", detail=f"audio: {error}")
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
                else:
                    raise ValueError("unknown voice command")
            except (TypeError, ValueError) as e:
                await session.send(t="error", detail=str(e))
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001 — never let one socket kill the hub
        try:
            await ws.send_json({"t": "error", "detail": str(e)})
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
