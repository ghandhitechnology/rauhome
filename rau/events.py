"""In-process event bus for hub, face, agent, heartbeat."""
from __future__ import annotations

import asyncio
import threading
import time
from collections import defaultdict, deque
from typing import Any, Callable, Deque, Dict, List, Optional


class EventBus:
    def __init__(self, history: int = 200):
        self._subs: Dict[str, List[Callable[[Dict[str, Any]], None]]] = defaultdict(list)
        self._async_queues: List[asyncio.Queue] = []
        self._history: Deque[Dict[str, Any]] = deque(maxlen=history)
        self._lock = threading.RLock()

    def emit(self, kind: str, **payload: Any) -> Dict[str, Any]:
        event = {"kind": kind, "ts": time.time(), **payload}
        with self._lock:
            self._history.append(event)
            listeners = list(self._subs.get(kind, [])) + list(self._subs.get("*", []))
            queues = list(self._async_queues)
        for fn in listeners:
            try:
                fn(event)
            except Exception:
                pass
        for q in queues:
            try:
                q.put_nowait(event)
            except Exception:
                pass
        return event

    def on(self, kind: str, fn: Callable[[Dict[str, Any]], None]) -> None:
        with self._lock:
            self._subs[kind].append(fn)

    def subscribe_async(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self._async_queues.append(q)
        return q

    def unsubscribe_async(self, q: asyncio.Queue) -> None:
        with self._lock:
            if q in self._async_queues:
                self._async_queues.remove(q)

    def history(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._history)[-limit:]


BUS = EventBus()
