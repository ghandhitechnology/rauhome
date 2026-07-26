"""Durable, public-safe activity spans for turns and background work.

This module is the only path from provider/tool internals to the activity UI.
It deliberately stores useful evidence rather than raw prompts, payloads, file
contents, screenshots, typed text, or opaque reasoning continuation blocks.
"""
from __future__ import annotations

import os
import re
import threading
import time
import uuid
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urlsplit, urlunsplit

from rau.control import control_store
from rau.events import BUS

PUBLIC_KINDS = {
    "reasoning",
    "planning",
    "tool",
    "approval",
    "execution",
    "verification",
    "retry",
    "completion",
}
ACTIVE_STATUSES = {"queued", "running", "awaiting_confirm"}
TERMINAL_STATUSES = {"completed", "failed", "cancelled", "interrupted"}

_DROP_KEYS = {
    "audio",
    "audio_b64",
    "authorization",
    "cookie",
    "encrypted_content",
    "file_content",
    "image",
    "image_b64",
    "images",
    "password",
    "prompt",
    "raw",
    "raw_payload",
    "reasoning_signature",
    "screenshot",
    "screenshots",
    "secret",
    "signature",
    "system",
    "system_prompt",
    "token",
}
_TYPED_KEYS = {
    "content",
    "input",
    "keystrokes",
    "secure_text",
    "text",
    "typed_text",
    "value",
}
_SECRET_KEY_RE = re.compile(
    r"(?:api[_-]?key|auth|bearer|cookie|credential|password|secret|signature|token)",
    re.IGNORECASE,
)
_AUTH_RE = re.compile(
    r"(?i)\b(?:authorization\s*:\s*)?(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"
)
_TOKEN_RE = re.compile(
    r"\b(?:sk|rk|pk|ghp|github_pat|xox[abprs])[-_A-Za-z0-9]{12,}\b"
)
_MAX_STRING = 1200
_MAX_ITEMS = 30
_MAX_DEPTH = 5


def _configured_secrets() -> Iterable[str]:
    for key, value in os.environ.items():
        if value and len(value) >= 8 and _SECRET_KEY_RE.search(key):
            yield value


def _clean_string(value: str) -> str:
    clean = _AUTH_RE.sub("[redacted credential]", value)
    clean = _TOKEN_RE.sub("[redacted credential]", clean)
    for secret in _configured_secrets():
        if secret in clean:
            clean = clean.replace(secret, "[redacted secret]")
    if len(clean) > _MAX_STRING:
        clean = clean[:_MAX_STRING] + "…"
    return clean


def _safe_url(value: str) -> str:
    try:
        parts = urlsplit(value)
    except ValueError:
        return _clean_string(value)
    if parts.scheme not in {"http", "https"}:
        return _clean_string(value)
    host = parts.hostname or ""
    try:
        port = parts.port
    except ValueError:
        # urlsplit defers port validation to attribute access; a non-numeric
        # port must not fail the whole span. Drop it, keep host and path.
        port = None
    if port:
        host = f"{host}:{port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


def sanitize_activity(value: Any, *, _key: str = "", _depth: int = 0) -> Any:
    """Return a bounded public representation of an internal value."""
    key = _key.lower()
    if _depth > _MAX_DEPTH:
        return "[bounded]"
    if key in _DROP_KEYS or _SECRET_KEY_RE.search(key):
        return "[redacted]"
    if key in _TYPED_KEYS:
        if isinstance(value, str):
            return {"redacted": True, "characters": len(value)}
        return "[redacted typed input]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if value.startswith(("http://", "https://")):
            return _safe_url(value)
        return _clean_string(value)
    if isinstance(value, dict):
        result: Dict[str, Any] = {}
        for index, (child_key, child_value) in enumerate(value.items()):
            if index >= _MAX_ITEMS:
                result["_truncated"] = len(value) - _MAX_ITEMS
                break
            public_key = str(child_key)[:80]
            result[public_key] = sanitize_activity(
                child_value, _key=public_key, _depth=_depth + 1
            )
        return result
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        public = [
            sanitize_activity(item, _depth=_depth + 1)
            for item in items[:_MAX_ITEMS]
        ]
        if len(items) > _MAX_ITEMS:
            public.append({"truncated": len(items) - _MAX_ITEMS})
        return public
    return _clean_string(str(value))


class ActivityManager:
    """Persists spans before broadcasting their corresponding live event."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._buffers: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _event_payload(span: Dict[str, Any]) -> Dict[str, Any]:
        payload = {
            key: span.get(key)
            for key in (
                "id",
                "seq",
                "revision",
                "source",
                "status",
                "label",
                "summary",
                "details",
                "turn_id",
                "job_id",
                "step_id",
                "parent_span_id",
                "started",
                "updated",
                "ended",
            )
        }
        payload["activity_kind"] = span.get("kind")
        return payload

    def start(
        self,
        kind: str,
        label: str,
        *,
        source: str = "rau",
        summary: str = "",
        details: Optional[Dict[str, Any]] = None,
        turn_id: Optional[str] = None,
        job_id: Optional[str] = None,
        step_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        status: str = "running",
        broadcast: bool = True,
    ) -> Dict[str, Any]:
        now = time.time()
        public = control_store.create_activity_span(
            {
                "id": str(uuid.uuid4()),
                "kind": kind if kind in PUBLIC_KINDS else "execution",
                "source": source[:80],
                "status": status,
                "label": _clean_string(label)[:200],
                "summary": _clean_string(summary),
                "details": sanitize_activity(details or {}),
                "turn_id": turn_id,
                "job_id": job_id,
                "step_id": step_id,
                "parent_span_id": parent_span_id,
                "started": now,
                "updated": now,
            }
        )
        with self._lock:
            self._buffers[public["id"]] = {
                "summary": public["summary"],
                "details": public["details"],
                "last_persist": now,
                "last_broadcast": now,
            }
        if broadcast:
            BUS.emit("activity_started", **self._event_payload(public))
        return public

    def announce(self, span_id: str) -> Optional[Dict[str, Any]]:
        """Publish a span that was synchronously persisted without broadcast."""
        public = control_store.get_activity_span(span_id)
        if public is not None:
            BUS.emit("activity_started", **self._event_payload(public))
        return public

    def delta(
        self,
        span_id: str,
        *,
        text: str = "",
        summary: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        force: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Coalesce high-frequency reasoning deltas for disk and WebSocket."""
        now = time.time()
        with self._lock:
            buffer = self._buffers.get(span_id)
            if buffer is None:
                current = control_store.get_activity_span(span_id)
                if current is None:
                    return None
                buffer = {
                    "summary": current.get("summary") or "",
                    "details": current.get("details") or {},
                    "last_persist": float(current.get("updated") or now),
                    "last_broadcast": 0.0,
                }
                self._buffers[span_id] = buffer
            if summary is not None:
                buffer["summary"] = _clean_string(summary)
            elif text:
                buffer["summary"] = _clean_string(
                    str(buffer.get("summary") or "") + text
                )
            if details is not None:
                buffer["details"] = sanitize_activity(details)
            persist = force or now - float(buffer["last_persist"]) >= 0.5
            broadcast = force or now - float(buffer["last_broadcast"]) >= 0.06
            if persist:
                current = control_store.update_activity_span(
                    span_id,
                    {
                        "summary": buffer["summary"],
                        "details": buffer["details"],
                        "updated": now,
                    },
                )
                buffer["last_persist"] = now
            else:
                current = control_store.get_activity_span(span_id)
            if current is None:
                return None
            current["summary"] = buffer["summary"]
            current["details"] = buffer["details"]
            if broadcast:
                buffer["last_broadcast"] = now
                BUS.emit("activity_delta", **self._event_payload(current))
            return current

    def finish(
        self,
        span_id: str,
        *,
        status: str = "completed",
        summary: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        now = time.time()
        with self._lock:
            buffer = self._buffers.pop(span_id, {})
        changes: Dict[str, Any] = {
            "status": status if status in TERMINAL_STATUSES else "completed",
            "ended": now,
            "updated": now,
        }
        if summary is not None:
            changes["summary"] = _clean_string(summary)
        elif "summary" in buffer:
            changes["summary"] = buffer["summary"]
        if details is not None:
            changes["details"] = sanitize_activity(details)
        elif "details" in buffer:
            changes["details"] = buffer["details"]
        public = control_store.update_activity_span(span_id, changes)
        if public is not None:
            BUS.emit("activity_finished", **self._event_payload(public))
        return public

    def list(
        self,
        *,
        turn_id: Optional[str] = None,
        job_id: Optional[str] = None,
        after_seq: int = 0,
        limit: int = 200,
    ) -> list[Dict[str, Any]]:
        return control_store.list_activity(
            turn_id=turn_id,
            job_id=job_id,
            after_seq=after_seq,
            limit=limit,
        )

    def active(self, *, limit: int = 200) -> list[Dict[str, Any]]:
        return control_store.list_activity(active_only=True, limit=limit)

    def purge(self, *, retention_days: int = 7) -> int:
        return control_store.purge_activity(
            time.time() - max(1, retention_days) * 86_400
        )


ACTIVITY = ActivityManager()
