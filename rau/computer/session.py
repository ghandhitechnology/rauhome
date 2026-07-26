"""Recoverable Accessibility-first computer-use sessions."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from rau.computer import cua
from rau.control.store import ControlStore, control_store
from rau.events import BUS

ACTIVE_STATES = {"active", "acting", "verifying"}
MUTATING_ACTIONS = {
    "activate",
    "click",
    "double_click",
    "type",
    "key",
    "drag",
    "move",
}
SECURE_ROLES = {"AXSecureTextField"}
SECURE_TITLE_WORDS = {
    "authentication",
    "permission",
    "password",
    "touch id",
    "keychain",
    "screen recording",
    "accessibility access",
}
MAX_AX_NODES = 300
DEFAULT_LEASE_SEC = 120.0
DEFAULT_DEADLINE_SEC = 15 * 60.0


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _ax_value(element: Any, attribute: Any) -> Any:
    try:
        import ApplicationServices as AS  # type: ignore

        result = AS.AXUIElementCopyAttributeValue(element, attribute, None)
        if isinstance(result, tuple):
            if len(result) >= 2 and int(result[0]) == 0:
                return result[1]
            return None
        return result
    except Exception:
        return None


def _ax_text(value: Any, limit: int = 500) -> str:
    if value is None:
        return ""
    try:
        return str(value)[:limit]
    except Exception:
        return ""


def _ax_point(value: Any) -> Optional[Tuple[float, float]]:
    if value is None:
        return None
    try:
        import ApplicationServices as AS  # type: ignore

        result = AS.AXValueGetValue(value, AS.kAXValueCGPointType, None)
        if isinstance(result, tuple) and len(result) >= 2 and result[0]:
            point = result[1]
            return float(point.x), float(point.y)
    except Exception:
        return None
    return None


def _ax_size(value: Any) -> Optional[Tuple[float, float]]:
    if value is None:
        return None
    try:
        import ApplicationServices as AS  # type: ignore

        result = AS.AXValueGetValue(value, AS.kAXValueCGSizeType, None)
        if isinstance(result, tuple) and len(result) >= 2 and result[0]:
            size = result[1]
            return float(size.width), float(size.height)
    except Exception:
        return None
    return None


def accessibility_tree(
    *,
    app: Optional[str] = None,
    frontmost: bool = True,
    max_nodes: int = MAX_AX_NODES,
    include_handles: bool = False,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Return a bounded AX tree plus optional ephemeral element handles."""
    info = cua._window_info(app=app, frontmost=frontmost or not app)
    pid = int(info.get("owner_pid") or 0)
    if pid <= 0:
        return [], {}
    try:
        import ApplicationServices as AS  # type: ignore
    except Exception:
        return [], {}
    root = AS.AXUIElementCreateApplication(pid)
    nodes: List[Dict[str, Any]] = []
    handles: Dict[str, Any] = {}
    queue: List[Tuple[Any, str, int]] = [(root, "0", 0)]
    seen: set[int] = set()
    while queue and len(nodes) < max(1, min(MAX_AX_NODES, int(max_nodes))):
        element, path, depth = queue.pop(0)
        identity = id(element)
        if identity in seen:
            continue
        seen.add(identity)
        role = _ax_text(_ax_value(element, AS.kAXRoleAttribute), 100)
        title = _ax_text(_ax_value(element, AS.kAXTitleAttribute))
        description = _ax_text(_ax_value(element, AS.kAXDescriptionAttribute))
        identifier = _ax_text(
            _ax_value(element, getattr(AS, "kAXIdentifierAttribute", "AXIdentifier"))
        )
        value = ""
        secure = role in SECURE_ROLES
        if not secure:
            value = _ax_text(_ax_value(element, AS.kAXValueAttribute))
        position = _ax_point(_ax_value(element, AS.kAXPositionAttribute))
        size = _ax_size(_ax_value(element, AS.kAXSizeAttribute))
        node_id = _digest(
            {
                "pid": pid,
                "path": path,
                "role": role,
                "title": title,
                "identifier": identifier,
            }
        )[:20]
        node: Dict[str, Any] = {
            "id": node_id,
            "path": path,
            "depth": depth,
            "role": role,
            "title": title,
            "label": description,
            "identifier": identifier,
            "value": "<secure>" if secure else value,
            "secure": secure,
        }
        if position and size:
            node["frame"] = {
                "x": round(position[0]),
                "y": round(position[1]),
                "width": round(size[0]),
                "height": round(size[1]),
            }
        nodes.append(node)
        if include_handles:
            handles[node_id] = element
        children = _ax_value(element, AS.kAXChildrenAttribute)
        if isinstance(children, (list, tuple)):
            for index, child in enumerate(children[:100]):
                queue.append((child, f"{path}.{index}", depth + 1))
    return nodes, handles


def _matches(node: Dict[str, Any], target: Dict[str, Any]) -> bool:
    for key in ("id", "role", "identifier"):
        wanted = str(target.get(key) or "")
        if wanted and str(node.get(key) or "") != wanted:
            return False
    for key in ("title", "label", "value"):
        wanted = str(target.get(key) or "").casefold()
        if wanted and wanted not in str(node.get(key) or "").casefold():
            return False
    return True


def _resolve_semantic(
    target: Dict[str, Any], *, app: Optional[str], frontmost: bool
) -> Tuple[Optional[Dict[str, Any]], Any]:
    nodes, handles = accessibility_tree(
        app=app, frontmost=frontmost, include_handles=True
    )
    candidates = [node for node in nodes if _matches(node, target)]
    index = int(target.get("index") or 0)
    if index < 0 or index >= len(candidates):
        return None, None
    node = candidates[index]
    return node, handles.get(str(node["id"]))


def _semantic_press(element: Any) -> Tuple[bool, str]:
    if element is None:
        return False, "semantic target is no longer available"
    try:
        import ApplicationServices as AS  # type: ignore

        code = AS.AXUIElementPerformAction(element, AS.kAXPressAction)
        if int(code) != 0:
            return False, f"Accessibility press failed with code {code}"
        return True, ""
    except Exception as exc:
        return False, f"Accessibility press failed: {exc}"


def _semantic_focus(element: Any) -> Tuple[bool, str]:
    if element is None:
        return False, "semantic target is no longer available"
    try:
        import ApplicationServices as AS  # type: ignore

        code = AS.AXUIElementSetAttributeValue(
            element, AS.kAXFocusedAttribute, True
        )
        if int(code) != 0:
            return False, f"Accessibility focus failed with code {code}"
        return True, ""
    except Exception as exc:
        return False, f"Accessibility focus failed: {exc}"


def _seconds_since_user_input() -> Optional[float]:
    try:
        import Quartz  # type: ignore

        values = []
        for event_type in (
            getattr(Quartz, "kCGEventMouseMoved", 5),
            getattr(Quartz, "kCGEventLeftMouseDown", 1),
            getattr(Quartz, "kCGEventKeyDown", 10),
        ):
            values.append(
                float(
                    Quartz.CGEventSourceSecondsSinceLastEventType(
                        Quartz.kCGEventSourceStateCombinedSessionState, event_type
                    )
                )
            )
        return min(values) if values else None
    except Exception:
        return None


class ComputerSessionManager:
    def __init__(
        self,
        store: ControlStore = control_store,
        *,
        capture: Callable[..., Dict[str, Any]] = cua.capture_screenshot,
        inspect: Callable[..., Tuple[List[Dict[str, Any]], Dict[str, Any]]] = accessibility_tree,
        action: Callable[..., Dict[str, Any]] = cua.execute_action,
    ):
        self.store = store
        self.capture = capture
        self.inspect = inspect
        self.action = action
        self._lock = threading.RLock()

    def start(
        self,
        *,
        job_id: Optional[str] = None,
        step_id: Optional[str] = None,
        app: Optional[str] = None,
        frontmost: bool = True,
        deadline_sec: float = DEFAULT_DEADLINE_SEC,
    ) -> Dict[str, Any]:
        now = time.time()
        session_id = str(uuid.uuid4())
        owner = f"{os.getpid()}:{threading.get_ident()}"
        session = self.store.create_computer_session(
            {
                "id": session_id,
                "job_id": job_id,
                "step_id": step_id,
                "state": "active",
                "app": {"name": app or "", "frontmost": bool(frontmost)},
                "lease_owner": owner,
                "lease_expires": now + DEFAULT_LEASE_SEC,
                "deadline": now + max(30.0, min(3600.0, float(deadline_sec))),
                "effect_state": "none",
            }
        )
        BUS.emit("computer_session", action="started", session=self._public(session))
        return self._public(session)

    def status(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        if session_id:
            session = self.store.get_computer_session(session_id)
            if session is None:
                return {"ok": False, "error": "unknown computer session"}
            return {"ok": True, "session": self._public(session)}
        return {
            "ok": True,
            "capabilities": cua.cua_status(),
            "sessions": [
                self._public(session)
                for session in self.store.list_computer_sessions(limit=20)
            ],
        }

    def observe(
        self,
        session_id: str,
        *,
        app: Optional[str] = None,
        frontmost: Optional[bool] = None,
        display_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            session = self._session(session_id)
            self._check_observable(session)
            app_cfg = session.get("app") or {}
            wanted_app = app if app is not None else str(app_cfg.get("name") or "") or None
            use_frontmost = (
                bool(frontmost)
                if frontmost is not None
                else bool(app_cfg.get("frontmost", not wanted_app))
            )
            shot = self.capture(
                display_id=display_id,
                app=wanted_app,
                frontmost=use_frontmost,
            )
            if not shot.get("ok"):
                return {"ok": False, "error": shot.get("error") or "capture failed"}
            try:
                nodes, _ = self.inspect(
                    app=wanted_app,
                    frontmost=use_frontmost,
                    max_nodes=MAX_AX_NODES,
                    include_handles=False,
                )
            except Exception:
                nodes = []
            window = {
                key: shot.get(key)
                for key in (
                    "window_id",
                    "title",
                    "window_bounds",
                    "app",
                    "bundle_id",
                )
                if shot.get(key) is not None
            }
            app_meta = {
                "name": shot.get("app") or wanted_app or "",
                "bundle_id": shot.get("bundle_id") or "",
            }
            image_b64 = str(shot.get("image_b64") or "")
            observation_id = str(uuid.uuid4())
            fingerprint = _digest(
                {
                    "app": app_meta,
                    "window": window,
                    "display_id": shot.get("display_id"),
                    "width": shot.get("width"),
                    "height": shot.get("height"),
                }
            )
            persisted = self.store.save_computer_observation(
                {
                    "id": observation_id,
                    "session_id": session_id,
                    "fingerprint": fingerprint,
                    "app": app_meta,
                    "window": window,
                    "displays": shot.get("displays") or [],
                    "accessibility": nodes,
                    "image_hash": hashlib.sha256(image_b64.encode()).hexdigest()
                    if image_b64
                    else "",
                    "width": shot.get("width") or 0,
                    "height": shot.get("height") or 0,
                    "user_idle_sec": _seconds_since_user_input(),
                }
            )
            self.store.update_computer_session(
                session_id,
                app={**app_cfg, "name": app_meta["name"]},
                window=window,
                latest_observation_id=observation_id,
                lease_expires=time.time() + DEFAULT_LEASE_SEC,
            )
            return {
                "ok": True,
                "observation": persisted,
                "image_b64": image_b64,
                "mime": shot.get("mime") or "image/png",
            }

    def inspect_ui(self, session_id: str) -> Dict[str, Any]:
        session = self._session(session_id)
        observation_id = session.get("latest_observation_id")
        if not observation_id:
            return self.observe(session_id)
        observation = self.store.get_computer_observation(str(observation_id))
        return {
            "ok": observation is not None,
            "observation": observation,
            "error": "" if observation else "observation is unavailable",
        }

    def focus(self, session_id: str, app: str) -> Dict[str, Any]:
        session = self._session(session_id)
        self._check_live(session)
        if not app.strip():
            return {"ok": False, "error": "app is required"}
        code, detail = cua._osascript(
            f"tell application {cua._apple_string(app.strip())} to activate"
        )
        if code != 0:
            return {"ok": False, "error": detail or "could not focus app"}
        self.store.update_computer_session(
            session_id,
            app={"name": app.strip(), "frontmost": True},
            latest_observation_id=None,
        )
        return self.observe(session_id, app=app.strip(), frontmost=True)

    def act(
        self,
        session_id: str,
        request: Dict[str, Any],
        cancel: Optional[threading.Event] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            session = self._session(session_id)
            self._check_live(session)
            kind = str(request.get("action") or "").lower().strip()
            if kind not in MUTATING_ACTIONS:
                return {"ok": False, "error": "computer_act requires a mutating action"}
            observation = self._latest_observation(session)
            if observation is None:
                return {
                    "ok": False,
                    "error": "observe the computer before acting",
                    "replan_required": True,
                }
            idle_now = _seconds_since_user_input()
            idle_then = observation.get("user_idle_sec")
            if (
                idle_now is not None
                and idle_then is not None
                and idle_now < 2.0
                and idle_now + 0.5 < float(idle_then)
            ):
                self.store.update_computer_session(
                    session_id,
                    state="awaiting_review",
                    effect_state="none",
                    result={"reason": "user_takeover"},
                )
                BUS.emit("computer_takeover", session_id=session_id)
                return {
                    "ok": False,
                    "paused": True,
                    "error": "physical user input detected; computer use paused",
                }

            target = request.get("target")
            if not isinstance(target, dict):
                return {"ok": False, "error": "target must be an object"}
            target_kind = str(target.get("kind") or "semantic").lower()
            compatible, reason = self._validate_target_context(
                session, observation, target
            )
            if not compatible:
                return {
                    "ok": False,
                    "error": reason,
                    "replan_required": True,
                }
            action_args: Dict[str, Any] = {"action": kind}
            if "text" in request:
                action_args["text"] = request.get("text")
            if "key" in request:
                action_args["key"] = request.get("key")
            if target_kind == "visual":
                if kind in {"type", "key"} and not bool(
                    request.get("_interactive_confirmed")
                ):
                    return {
                        "ok": False,
                        "error": (
                            "visual typing/key actions require an exact "
                            "interactive confirmation"
                        ),
                        "secure": True,
                    }
                if str(target.get("observation_id") or "") != str(observation["id"]):
                    return {
                        "ok": False,
                        "error": "visual target belongs to a stale observation",
                        "replan_required": True,
                    }
                for field in ("x", "y", "x2", "y2", "display_id"):
                    if field in target:
                        action_args[field] = target[field]
            elif target_kind == "semantic":
                app_cfg = session.get("app") or {}
                try:
                    current_nodes, handles = self.inspect(
                        app=str(app_cfg.get("name") or "") or None,
                        frontmost=bool(app_cfg.get("frontmost", True)),
                        max_nodes=MAX_AX_NODES,
                        include_handles=True,
                    )
                except Exception:
                    current_nodes, handles = [], {}
                candidates = [
                    candidate
                    for candidate in current_nodes
                    if _matches(candidate, target)
                ]
                index = int(target.get("index") or 0)
                node = (
                    candidates[index]
                    if 0 <= index < len(candidates)
                    else None
                )
                handle = handles.get(str(node.get("id"))) if node else None
                if node is None:
                    return {
                        "ok": False,
                        "error": "semantic target was not found in the current UI",
                        "replan_required": True,
                    }
                secure_error = self._secure_target_error(node, kind)
                if secure_error and not bool(request.get("_interactive_confirmed")):
                    return {"ok": False, "error": secure_error, "secure": True}
                if kind in {"activate", "click"}:
                    self.store.update_computer_session(
                        session_id, state="acting", effect_state="unknown"
                    )
                    ok, detail = _semantic_press(handle)
                    if ok:
                        raw_result = {
                            "ok": True,
                            "action": kind,
                            "semantic": True,
                        }
                    else:
                        frame = node.get("frame") or {}
                        if not frame:
                            raw_result = {
                                "ok": False,
                                "action": kind,
                                "error": detail,
                            }
                        else:
                            raw_result = self.action(
                                {
                                    "action": "click",
                                    "x": int(frame["x"] + frame["width"] / 2),
                                    "y": int(frame["y"] + frame["height"] / 2),
                                },
                                cancel=cancel,
                                auto_verify=False,
                            )
                elif kind == "type":
                    focused, detail = _semantic_focus(handle)
                    if not focused:
                        return {
                            "ok": False,
                            "error": detail,
                            "replan_required": True,
                        }
                    self.store.update_computer_session(
                        session_id, state="acting", effect_state="unknown"
                    )
                    raw_result = self.action(
                        action_args, cancel=cancel, auto_verify=False
                    )
                else:
                    frame = node.get("frame") or {}
                    if not frame:
                        return {
                            "ok": False,
                            "error": "semantic target has no actionable frame",
                            "replan_required": True,
                        }
                    action_args["x"] = int(frame["x"] + frame["width"] / 2)
                    action_args["y"] = int(frame["y"] + frame["height"] / 2)
                    self.store.update_computer_session(
                        session_id, state="acting", effect_state="unknown"
                    )
                    raw_result = self.action(
                        action_args, cancel=cancel, auto_verify=False
                    )
            else:
                return {"ok": False, "error": "target.kind must be semantic or visual"}

            if target_kind == "visual":
                self.store.update_computer_session(
                    session_id, state="acting", effect_state="unknown"
                )
                raw_result = self.action(action_args, cancel=cancel, auto_verify=False)

            self.store.update_computer_session(session_id, state="verifying")
            after = self.observe(session_id)
            if not after.get("ok"):
                self.store.update_computer_session(
                    session_id,
                    state="awaiting_review",
                    effect_state="unknown",
                    result={"action": raw_result, "verify_error": after.get("error")},
                )
                return {
                    "ok": False,
                    "effect_state": "unknown",
                    "error": "action returned but verification observation failed",
                    "action_result": raw_result,
                    "replan_required": True,
                }
            postcondition = request.get("postcondition")
            verified = bool(raw_result.get("ok"))
            verify_detail = ""
            if isinstance(postcondition, dict):
                verified, verify_detail = self._assert_observation(
                    after["observation"], postcondition
                )
            effect_state = "applied" if verified else "applied_unverified"
            self.store.update_computer_session(
                session_id,
                state="active",
                effect_state=effect_state,
                lease_expires=time.time() + DEFAULT_LEASE_SEC,
                result={
                    "action": {
                        key: value
                        for key, value in raw_result.items()
                        if key not in {"image_b64", "text"}
                    },
                    "verified": verified,
                    "verify_detail": verify_detail,
                },
            )
            BUS.emit(
                "computer_action",
                session_id=session_id,
                action=kind,
                verified=verified,
                effect_state=effect_state,
            )
            return {
                "ok": verified,
                "effect_state": effect_state,
                "verified": verified,
                "verify_detail": verify_detail,
                "action_result": raw_result,
                "observation": after.get("observation"),
                "image_b64": after.get("image_b64"),
                "mime": after.get("mime"),
                "replan_required": not verified,
            }

    def assert_condition(
        self, session_id: str, condition: Dict[str, Any]
    ) -> Dict[str, Any]:
        session = self._session(session_id)
        observation = self._latest_observation(session)
        if observation is None:
            observed = self.observe(session_id)
            if not observed.get("ok"):
                return observed
            observation = observed["observation"]
        ok, detail = self._assert_observation(observation, condition)
        if ok and session.get("state") == "awaiting_review":
            self.store.update_computer_session(
                session_id,
                state="active",
                effect_state="applied",
                lease_expires=time.time() + DEFAULT_LEASE_SEC,
                result={
                    **(session.get("result") or {}),
                    "recovered_by_assertion": condition,
                },
            )
        return {"ok": ok, "detail": detail, "observation_id": observation["id"]}

    def wait_for(
        self,
        session_id: str,
        condition: Dict[str, Any],
        *,
        timeout_sec: float = 15.0,
        cancel: Optional[threading.Event] = None,
    ) -> Dict[str, Any]:
        deadline = time.monotonic() + max(0.1, min(30.0, float(timeout_sec)))
        last = ""
        while time.monotonic() < deadline:
            if cancel is not None and cancel.wait(0.0):
                return {"ok": False, "cancelled": True, "error": "cancelled"}
            observed = self.observe(session_id)
            if not observed.get("ok"):
                last = str(observed.get("error") or "")
            else:
                ok, detail = self._assert_observation(
                    observed["observation"], condition
                )
                if ok:
                    current = self._session(session_id)
                    if current.get("state") == "awaiting_review":
                        self.store.update_computer_session(
                            session_id,
                            state="active",
                            effect_state="applied",
                            lease_expires=time.time() + DEFAULT_LEASE_SEC,
                            result={
                                **(current.get("result") or {}),
                                "recovered_by_assertion": condition,
                            },
                        )
                    return {
                        "ok": True,
                        "detail": detail,
                        "observation_id": observed["observation"]["id"],
                    }
                last = detail
            if cancel is not None:
                if cancel.wait(0.5):
                    return {"ok": False, "cancelled": True, "error": "cancelled"}
            else:
                time.sleep(0.5)
        return {"ok": False, "error": "condition timed out", "detail": last}

    def finish(
        self, session_id: str, *, outcome: str = "completed", summary: str = ""
    ) -> Dict[str, Any]:
        session = self._session(session_id)
        state = outcome if outcome in {"completed", "failed", "cancelled"} else "completed"
        value = self.store.update_computer_session(
            session_id,
            state=state,
            lease_owner=None,
            lease_expires=None,
            result={**(session.get("result") or {}), "summary": summary[:4000]},
        )
        assert value is not None
        BUS.emit("computer_session", action="finished", session=self._public(value))
        return {"ok": True, "session": self._public(value)}

    def _session(self, session_id: str) -> Dict[str, Any]:
        value = self.store.get_computer_session(str(session_id))
        if value is None:
            raise ValueError("unknown computer session")
        return value

    @staticmethod
    def _check_live(session: Dict[str, Any]) -> None:
        if session.get("state") not in ACTIVE_STATES:
            raise RuntimeError(
                f"computer session is {session.get('state')}; review or start another"
            )
        deadline = session.get("deadline")
        if deadline is not None and float(deadline) <= time.time():
            raise RuntimeError("computer session deadline expired")

    @staticmethod
    def _check_observable(session: Dict[str, Any]) -> None:
        if session.get("state") not in ACTIVE_STATES | {"awaiting_review"}:
            raise RuntimeError(f"computer session is {session.get('state')}")
        deadline = session.get("deadline")
        if deadline is not None and float(deadline) <= time.time():
            raise RuntimeError("computer session deadline expired")

    def _latest_observation(
        self, session: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        observation_id = session.get("latest_observation_id")
        return (
            self.store.get_computer_observation(str(observation_id))
            if observation_id
            else None
        )

    def _validate_target_context(
        self,
        session: Dict[str, Any],
        observation: Dict[str, Any],
        target: Dict[str, Any],
    ) -> Tuple[bool, str]:
        app_cfg = session.get("app") or {}
        try:
            current = self.capture(
                display_id=target.get("display_id")
                if isinstance(target.get("display_id"), int)
                else None,
                app=str(app_cfg.get("name") or "") or None,
                frontmost=bool(app_cfg.get("frontmost", True)),
            )
        except Exception as exc:
            return False, f"could not validate current target context: {exc}"
        if not current.get("ok"):
            return False, str(current.get("error") or "target context unavailable")
        previous_window = observation.get("window") or {}
        for key, current_key in (
            ("window_id", "window_id"),
            ("window_bounds", "window_bounds"),
        ):
            previous = previous_window.get(key)
            present = current.get(current_key)
            if previous is not None and present != previous:
                return False, f"window {key} changed since observation"
        previous_app = observation.get("app") or {}
        wanted_bundle = str(target.get("bundle_id") or "")
        current_bundle = str(current.get("bundle_id") or "")
        observed_bundle = str(previous_app.get("bundle_id") or "")
        if wanted_bundle and wanted_bundle not in {current_bundle, observed_bundle}:
            return False, "target bundle identity does not match the active application"
        wanted_window = target.get("window_id")
        if wanted_window is not None and wanted_window != current.get("window_id"):
            return False, "target window identity does not match the active window"
        display_ids = {
            int(display.get("display_id"))
            for display in current.get("displays") or []
            if display.get("display_id") is not None
        }
        target_display = target.get("display_id")
        if target_display is not None and int(target_display) not in display_ids:
            return False, "target display is no longer active"
        return True, ""

    @staticmethod
    def _secure_target_error(node: Dict[str, Any], action: str) -> str:
        if action not in MUTATING_ACTIONS:
            return ""
        if node.get("secure") or str(node.get("role") or "") in SECURE_ROLES:
            return "secure text fields require a separately confirmed interactive flow"
        blob = " ".join(
            str(node.get(key) or "") for key in ("title", "label", "value")
        ).casefold()
        if any(word in blob for word in SECURE_TITLE_WORDS):
            return "authentication and permission dialogs require exact interactive confirmation"
        return ""

    @staticmethod
    def _assert_observation(
        observation: Dict[str, Any], condition: Dict[str, Any]
    ) -> Tuple[bool, str]:
        kind = str(condition.get("kind") or "exists").lower()
        target = condition.get("target")
        if not isinstance(target, dict):
            return False, "condition.target must be an object"
        nodes = observation.get("accessibility") or []
        matches = [node for node in nodes if _matches(node, target)]
        if kind == "exists":
            return bool(matches), "target exists" if matches else "target not found"
        if kind == "not_exists":
            return not matches, "target absent" if not matches else "target still exists"
        if kind == "text_contains":
            text = str(condition.get("text") or "").casefold()
            ok = any(
                text
                in " ".join(str(node.get(k) or "") for k in ("title", "label", "value")).casefold()
                for node in matches
            )
            return ok, "text found" if ok else "text not found"
        return False, f"unknown condition kind {kind}"

    @staticmethod
    def _public(session: Dict[str, Any]) -> Dict[str, Any]:
        return {
            key: value
            for key, value in session.items()
            if key not in {"lease_owner"}
        }


COMPUTER = ComputerSessionManager()


def compatibility_cua_action(
    args: Dict[str, Any],
    *,
    job_id: Optional[str] = None,
    cancel: Optional[threading.Event] = None,
) -> Dict[str, Any]:
    """Translate the legacy one-shot CUA schema onto a persisted session."""
    action = str(args.get("action") or "").lower()
    supplied_session_id = str(args.get("session_id") or "").strip()
    if action == "status":
        return COMPUTER.status(supplied_session_id or None)
    if action in {"wait", "scroll"}:
        # These legacy actions have no target/effect contract. Keep them during
        # migration; all click/type/key/drag/move paths use the safe session.
        return cua.execute_action(args, cancel=cancel, auto_verify=True)
    created_here = not supplied_session_id
    if supplied_session_id:
        status = COMPUTER.status(supplied_session_id)
        if not status.get("ok"):
            return status
        session_id = supplied_session_id
    else:
        session = COMPUTER.start(
            job_id=job_id,
            app=str(args.get("app") or "") or None,
            frontmost=bool(args.get("frontmost", not args.get("app"))),
        )
        session_id = str(session["id"])
    observed = COMPUTER.observe(
        session_id,
        app=str(args.get("app") or "") or None,
        frontmost=bool(args.get("frontmost", not args.get("app"))),
        display_id=args.get("display_id")
        if isinstance(args.get("display_id"), int)
        else None,
    )
    if not observed.get("ok") or action == "screenshot":
        if action != "screenshot":
            COMPUTER.finish(session_id, outcome="failed", summary=str(observed.get("error") or ""))
        return {**observed, "session_id": session_id}
    observation_id = str(observed["observation"]["id"])
    request: Dict[str, Any] = {
        "action": action,
        "target": {
            "kind": "visual",
            "observation_id": observation_id,
            **{
                key: args[key]
                for key in ("x", "y", "x2", "y2", "display_id")
                if key in args
            },
        },
        **{
            key: args[key]
            for key in ("text", "key", "_interactive_confirmed")
            if key in args
        },
    }
    result = COMPUTER.act(session_id, request, cancel=cancel)
    # Preserve an explicitly continued session so subsequent compatibility
    # calls can observe and verify within the same exclusive lease. One-shot
    # callers keep their old behavior and release the machine immediately.
    if created_here:
        COMPUTER.finish(
            session_id,
            outcome="completed" if result.get("ok") else "failed",
            summary="legacy CUA compatibility action",
        )
    return {**result, "session_id": session_id}
