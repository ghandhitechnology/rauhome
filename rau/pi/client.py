"""Client for the pi agent sidecar (see pi-sidecar/)."""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Callable, Dict, Iterator, List, Optional

DEFAULT_BASE_URL = "http://127.0.0.1:8791"
MAX_JSON_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_EVENT_LINE_BYTES = 2 * 1024 * 1024
MAX_EVENT_STREAM_BYTES = 32 * 1024 * 1024

#: Mirrors rau.state — the sidecar reports its runs in the same vocabulary so a
#: run can be projected straight onto a Job without a translation table.
ACTIVE_RUN_STATES = ("running", "awaiting_confirm")
TERMINAL_RUN_STATES = ("done", "failed", "cancelled")


class PiSidecarError(RuntimeError):
    """The sidecar refused a request or could not be reached."""


@dataclass
class ConfirmRequest:
    """A tool call the sidecar is holding until someone approves it."""

    id: str
    tool: str
    summary: str
    input: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RunResult:
    id: str
    state: str
    result: str = ""
    error: str = ""
    completion: Dict[str, Any] = field(default_factory=dict)
    session_path: str = ""

    @property
    def ok(self) -> bool:
        return self.state == "done"


@dataclass
class RunSpec:
    """Everything the sidecar needs to start one run.

    `provider="faux"` drives pi's scripted fake provider, which is how this can
    be exercised with no API keys at all.
    """

    goal: str
    cwd: Optional[str] = None
    provider: str = "faux"
    model: str = "faux-1"
    faux_scenario: str = "tool"
    system_prompt: Optional[str] = None
    skills: List[Dict[str, Any]] = field(default_factory=list)
    tools: List[str] = field(default_factory=lambda: ["bash", "read", "write", "edit"])
    confirm_tools: List[str] = field(default_factory=lambda: ["bash", "write", "edit"])
    confirm_timeout_ms: int = 45_000
    max_turns: int = 24
    run_timeout_ms: int = 15 * 60_000

    def payload(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


def pi_skill(skill: Any) -> Dict[str, Any]:
    """Project a Rau skill (rau.skills.loader.Skill) onto pi's shape.

    Duck-typed on purpose: the loader's dataclass is not imported here so the
    bridge stays independent of it. The sidecar advertises the validated file
    location and also injects `content`, preserving in-memory skills and runs
    that intentionally omit the read tool.
    """
    return {
        "name": str(getattr(skill, "name", "")),
        "description": str(getattr(skill, "description", "")),
        "content": str(getattr(skill, "body", "")),
        "filePath": str(getattr(skill, "path", "")),
    }


ProgressFn = Callable[[str], None]
TextFn = Callable[[str], None]
ConfirmFn = Callable[[ConfirmRequest], bool]


class PiSidecar:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 10.0,
        stream_timeout: float = 900.0,
        token: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.stream_timeout = stream_timeout
        self.token = token if token is not None else os.environ.get("PI_SIDECAR_TOKEN", "")

    def _headers(self, *, stream: bool = False) -> Dict[str, str]:
        headers = {
            "Accept": "text/event-stream" if stream else "application/json",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def health(self) -> Dict[str, Any]:
        return self._request("GET", "/health")

    def available(self) -> bool:
        try:
            return bool(self.health().get("ok"))
        except PiSidecarError:
            return False

    def start(self, spec: RunSpec) -> str:
        snap = self._request("POST", "/runs", spec.payload())
        run_id = snap.get("id")
        if not isinstance(run_id, str) or not run_id:
            raise PiSidecarError("sidecar start response has no run id")
        self._run_id(run_id)
        return run_id

    def snapshot(self, run_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/runs/{self._run_id(run_id)}")

    def list_runs(self) -> List[Dict[str, Any]]:
        runs = self._request("GET", "/runs").get("runs") or []
        if not isinstance(runs, list) or not all(isinstance(run, dict) for run in runs):
            raise PiSidecarError("sidecar returned an invalid run list")
        return list(runs)

    def cancel(self, run_id: str) -> bool:
        return bool(
            self._request("POST", f"/runs/{self._run_id(run_id)}/cancel", {}).get(
                "cancelled"
            )
        )

    def confirm(self, run_id: str, confirm_id: str, approved: bool) -> bool:
        body = {"confirm_id": confirm_id, "approved": bool(approved)}
        return bool(
            self._request(
                "POST", f"/runs/{self._run_id(run_id)}/confirm", body
            ).get("accepted")
        )

    def events(self, run_id: str) -> Iterator[Dict[str, Any]]:
        """Yield the run's server-sent events until it settles.

        The stream replays from the run's start, so attaching late never loses
        the confirm request or the result. A dropped socket reconnects from the
        last sequence id; malformed frames are ignored up to a small ceiling so
        one bad event cannot kill the run or create an unbounded retry loop.
        """
        safe_id = self._run_id(run_id)
        last_seq = 0
        retries = 0
        malformed = 0
        saw_result = False

        while True:
            req = urllib.request.Request(
                f"{self.base_url}/runs/{safe_id}/events?after={last_seq}",
                headers={
                    **self._headers(stream=True),
                    "Last-Event-ID": str(last_seq),
                },
            )
            try:
                resp = urllib.request.urlopen(req, timeout=self.stream_timeout)
                with resp:
                    for raw in self._stream_lines(resp, run_id):
                        line = raw.decode("utf-8", "replace").strip()
                        if not line.startswith("data:"):
                            continue
                        blob = line[5:].strip()
                        try:
                            event = json.loads(blob)
                        except json.JSONDecodeError:
                            malformed += 1
                            if malformed > 16:
                                raise PiSidecarError(
                                    f"too many malformed events for run {run_id}"
                                )
                            continue
                        if not isinstance(event, dict):
                            malformed += 1
                            if malformed > 16:
                                raise PiSidecarError(
                                    f"too many malformed events for run {run_id}"
                                )
                            continue
                        seq = event.get("seq")
                        if not isinstance(seq, int) or seq <= 0:
                            malformed += 1
                            if malformed > 16:
                                raise PiSidecarError(
                                    f"too many malformed events for run {run_id}"
                                )
                            continue
                        if seq <= last_seq:
                            continue
                        last_seq = seq
                        kind = event.get("type")
                        if not isinstance(kind, str):
                            malformed += 1
                            if malformed > 16:
                                raise PiSidecarError(
                                    f"too many malformed events for run {run_id}"
                                )
                            continue
                        retries = 0
                        if kind == "result":
                            saw_result = True
                        if kind == "close":
                            if not saw_result:
                                recovered = self._terminal_result(run_id)
                                if recovered:
                                    yield recovered
                            return
                        yield event
                # A clean EOF without `close` is still a dropped stream.
                raise OSError("event stream ended before close")
            except PiSidecarError:
                raise
            except (urllib.error.URLError, OSError) as e:
                recovered = self._terminal_result(run_id)
                if recovered:
                    if not saw_result:
                        yield recovered
                    return
                retries += 1
                if retries > 3:
                    raise PiSidecarError(
                        f"cannot stream run {run_id} after {retries} attempts: {e}"
                    ) from e
                time.sleep(min(0.5, 0.1 * (2 ** (retries - 1))))

    def run(
        self,
        spec: RunSpec,
        on_progress: Optional[ProgressFn] = None,
        on_text: Optional[TextFn] = None,
        on_confirm: Optional[ConfirmFn] = None,
        cancel: Optional[threading.Event] = None,
    ) -> RunResult:
        """Start a goal and block until it settles — the `_run_subagent` shape.

        `cancel` is watched on its own thread: the event stream is a blocking
        socket read, so a caller's cancel can only reach the sidecar out of
        band, and the cancel's own events are what wake the reader back up.
        """
        run_id = self.start(spec)
        stop_watch = threading.Event()
        watcher: Optional[threading.Thread] = None
        if cancel is not None:
            watcher = threading.Thread(
                target=self._watch_cancel,
                args=(run_id, cancel, stop_watch),
                daemon=True,
                name=f"pi-cancel-{run_id[:8]}",
            )
            watcher.start()

        settled = RunResult(id=run_id, state="failed", error="stream ended without a result")
        handled_confirms: set[str] = set()
        try:
            for event in self.events(run_id):
                kind = event.get("type")
                if kind == "state" and on_progress:
                    self._callback("progress", on_progress, str(event.get("progress") or ""))
                elif kind == "text" and on_text:
                    self._callback("text", on_text, str(event.get("delta") or ""))
                elif kind == "confirm_request":
                    confirm_id = event.get("confirm_id")
                    if isinstance(confirm_id, str) and confirm_id not in handled_confirms:
                        handled_confirms.add(confirm_id)
                        self._handle_confirm(run_id, event, on_confirm)
                elif kind == "result":
                    state = event.get("state")
                    if state not in TERMINAL_RUN_STATES:
                        continue
                    settled = RunResult(
                        id=run_id,
                        state=str(state),
                        result=str(event.get("result") or ""),
                        error=str(event.get("error") or ""),
                        completion=dict(event.get("completion") or {})
                        if isinstance(event.get("completion"), dict)
                        else {},
                        session_path=str(event.get("session_path") or ""),
                    )
        except Exception as e:
            self._cancel_quiet(run_id)
            if isinstance(e, PiSidecarError):
                raise
            raise PiSidecarError(f"run {run_id} event handling failed: {e}") from e
        finally:
            stop_watch.set()
            if watcher:
                watcher.join(timeout=2.0)

        if settled.state == "failed" and settled.error == "stream ended without a result":
            recovered = self._terminal_result(run_id)
            if recovered:
                settled = RunResult(
                    id=run_id,
                    state=str(recovered["state"]),
                    result=str(recovered.get("result") or ""),
                    error=str(recovered.get("error") or ""),
                    completion=dict(recovered.get("completion") or {})
                    if isinstance(recovered.get("completion"), dict)
                    else {},
                    session_path=str(recovered.get("session_path") or ""),
                )
            else:
                self._cancel_quiet(run_id)
        return settled

    def _handle_confirm(
        self,
        run_id: str,
        event: Dict[str, Any],
        on_confirm: Optional[ConfirmFn],
    ) -> None:
        raw_input = event.get("input")
        request = ConfirmRequest(
            id=str(event.get("confirm_id") or ""),
            tool=str(event.get("tool") or ""),
            summary=str(event.get("summary") or ""),
            input=dict(raw_input) if isinstance(raw_input, dict) else {},
        )
        if not request.id:
            return
        # No handler means nobody can approve, and the sidecar would sit on its
        # confirm timeout before continuing. Deny immediately instead.
        if on_confirm is None:
            self._answer_confirm(run_id, request.id, False)
            return
        # Decided off the reader thread. A handler that waits on a human holds
        # this thread for as long as the human takes, and the events that end
        # `run()` — the cancel's own result among them — arrive on it, so
        # deciding inline makes cancel latency equal to the human's. The sidecar
        # keys the reply on the confirm id and rejects one for a gate that has
        # already settled, so an answer that lands too late is inert.
        threading.Thread(
            target=self._decide_confirm,
            args=(run_id, request, on_confirm),
            daemon=True,
            name=f"pi-confirm-{run_id[:8]}",
        ).start()

    def _decide_confirm(
        self,
        run_id: str,
        request: ConfirmRequest,
        on_confirm: ConfirmFn,
    ) -> None:
        try:
            approved = bool(on_confirm(request))
        except Exception:
            # A handler that raises must still answer, or the run parks until the
            # sidecar's confirm timeout with nobody left to release it.
            approved = False
        self._answer_confirm(run_id, request.id, approved)

    def _answer_confirm(self, run_id: str, confirm_id: str, approved: bool) -> None:
        try:
            self.confirm(run_id, confirm_id, approved)
        except PiSidecarError:
            # The run cancelled or timed out while the decision was pending; its
            # own confirm_result already settled the gate.
            pass

    def _watch_cancel(
        self,
        run_id: str,
        cancel: threading.Event,
        stop: threading.Event,
    ) -> None:
        while not stop.is_set():
            if cancel.wait(timeout=0.25):
                try:
                    self.cancel(run_id)
                except PiSidecarError:
                    pass
                return

    def _terminal_result(self, run_id: str) -> Optional[Dict[str, Any]]:
        try:
            snap = self.snapshot(run_id)
        except PiSidecarError:
            return None
        state = snap.get("state")
        if state not in TERMINAL_RUN_STATES:
            return None
        return {
            "type": "result",
            "state": state,
            "result": snap.get("result") or "",
            "error": snap.get("error") or "",
            "completion": snap.get("completion") or {},
            "session_path": snap.get("session_path") or "",
        }

    def _cancel_quiet(self, run_id: str) -> None:
        try:
            self.cancel(run_id)
        except PiSidecarError:
            pass

    @staticmethod
    def _callback(name: str, callback: Callable[[str], None], value: str) -> None:
        try:
            callback(value)
        except Exception as e:
            raise PiSidecarError(f"{name} callback failed: {e}") from e

    @staticmethod
    def _run_id(run_id: str) -> str:
        if (
            not isinstance(run_id, str)
            or not run_id
            or not re.fullmatch(r"[A-Za-z0-9-]{1,128}", run_id)
        ):
            raise PiSidecarError("invalid run id")
        # Quote rather than concatenate caller text into an endpoint path.
        return urllib.parse.quote(run_id, safe="")

    @staticmethod
    def _stream_lines(resp: Any, run_id: str) -> Iterator[bytes]:
        total = 0
        readline = getattr(resp, "readline", None)
        source = (
            iter(lambda: readline(MAX_EVENT_LINE_BYTES + 1), b"")
            if callable(readline)
            else iter(resp)
        )
        for raw in source:
            if len(raw) > MAX_EVENT_LINE_BYTES:
                raise PiSidecarError(
                    f"event line for run {run_id} exceeded {MAX_EVENT_LINE_BYTES} bytes"
                )
            total += len(raw)
            if total > MAX_EVENT_STREAM_BYTES:
                raise PiSidecarError(
                    f"event stream for run {run_id} exceeded {MAX_EVENT_STREAM_BYTES} bytes"
                )
            yield raw

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={**self._headers(), "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read(MAX_JSON_RESPONSE_BYTES + 1)
                if len(raw) > MAX_JSON_RESPONSE_BYTES:
                    raise PiSidecarError(
                        f"{method} {path} response exceeded "
                        f"{MAX_JSON_RESPONSE_BYTES} bytes"
                    )
                decoded = json.loads(raw.decode("utf-8") or "{}")
                if not isinstance(decoded, dict):
                    raise PiSidecarError(f"{method} {path} returned non-object JSON")
                return decoded
        except json.JSONDecodeError as e:
            raise PiSidecarError(f"{method} {path} returned malformed JSON") from e
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:400]
            raise PiSidecarError(f"{method} {path} -> {e.code}: {detail}") from e
        except (urllib.error.URLError, OSError) as e:
            raise PiSidecarError(f"{method} {path} unreachable: {e}") from e


def run_goal(
    goal: str,
    on_progress: Optional[ProgressFn] = None,
    on_confirm: Optional[ConfirmFn] = None,
    cancel: Optional[threading.Event] = None,
    spec: Optional[RunSpec] = None,
    base_url: str = DEFAULT_BASE_URL,
) -> RunResult:
    """Blocking one-shot: goal in, progress out, result back."""
    resolved = replace(spec, goal=goal) if spec is not None else RunSpec(goal=goal)
    return PiSidecar(base_url).run(
        resolved,
        on_progress=on_progress,
        on_confirm=on_confirm,
        cancel=cancel,
    )
