"""In-process event bus for hub, face, agent, heartbeat."""
from __future__ import annotations

import asyncio
import threading
import time
from collections import defaultdict, deque
from typing import Any, Callable, Deque, Dict, List, Tuple

ASYNC_QUEUE_SIZE = 256


class EventBus:
    def __init__(self, history: int = 200):
        self._subs: Dict[str, List[Callable[[Dict[str, Any]], None]]] = defaultdict(list)
        self._async_queues: List[Tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self._history: Deque[Dict[str, Any]] = deque(maxlen=history)
        self._lock = threading.RLock()

    def emit(self, kind: str, **payload: Any) -> Dict[str, Any]:
        # Reserved envelope fields cannot be spoofed by a payload.
        event = {**payload, "kind": str(kind), "ts": time.time()}
        with self._lock:
            self._history.append(event)
            listeners = list(self._subs.get(kind, [])) + list(self._subs.get("*", []))
            queues = list(self._async_queues)
        for fn in listeners:
            try:
                fn(event)
            except Exception:
                pass
        for loop, q in queues:
            def deliver(queue: asyncio.Queue = q) -> None:
                # A slow/disconnected event socket must not grow memory without
                # bound. Preserve the newest state by evicting the oldest item.
                if queue.full():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    pass

            try:
                loop.call_soon_threadsafe(deliver)
            except RuntimeError:
                # The subscriber loop has already closed.
                pass
        # The live bus remains best-effort and fast. When the runtime durable
        # plane is enabled, append a bounded envelope after delivery so a disk
        # problem cannot prevent the UI from seeing current state.
        try:
            from rau import state

            if state.durable_enabled():
                from rau.control import control_store

                safe_payload = {
                    key: value
                    for key, value in payload.items()
                    if key not in {"image_b64", "audio", "content"}
                }
                encoded = str(safe_payload)
                if len(encoded) > 20_000:
                    safe_payload = {"truncated": True, "size": len(encoded)}
                control_store.append_event(
                    str(kind),
                    "job" if payload.get("job_id") or payload.get("id") else "runtime",
                    str(payload.get("job_id") or payload.get("id") or "") or None,
                    safe_payload,
                    created=float(event["ts"]),
                )
        except Exception:
            pass
        return event

    def on(self, kind: str, fn: Callable[[Dict[str, Any]], None]) -> None:
        with self._lock:
            self._subs[kind].append(fn)

    def off(self, kind: str, fn: Callable[[Dict[str, Any]], None]) -> None:
        with self._lock:
            self._subs[kind] = [
                existing for existing in self._subs.get(kind, []) if existing != fn
            ]

    def subscribe_async(self) -> asyncio.Queue:
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue(maxsize=ASYNC_QUEUE_SIZE)
        with self._lock:
            self._async_queues.append((loop, q))
        return q

    def unsubscribe_async(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._async_queues = [
                (loop, queue)
                for loop, queue in self._async_queues
                if queue is not q
            ]

    def history(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            count = max(0, int(limit))
            return list(self._history)[-count:] if count else []


BUS = EventBus()
