"""Client for the pi agent sidecar (see pi-sidecar/)."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Callable, Dict, Iterator, List, Optional

DEFAULT_BASE_URL = "http://127.0.0.1:8791"

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

    def payload(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


def pi_skill(skill: Any) -> Dict[str, Any]:
    """Project a Rau skill (rau.skills.loader.Skill) onto pi's shape.

    Duck-typed on purpose: the loader's dataclass is not imported here so the
    bridge stays independent of it. Note that pi only advertises name,
    description and location in the system prompt — the body is expected to be
    read back off disk by the agent, so `filePath` has to be reachable from the
    run's cwd or the skill is a dead reference.
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
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.stream_timeout = stream_timeout

    def health(self) -> Dict[str, Any]:
        return self._request("GET", "/health")

    def available(self) -> bool:
        try:
            return bool(self.health().get("ok"))
        except PiSidecarError:
            return False

    def start(self, spec: RunSpec) -> str:
        snap = self._request("POST", "/runs", spec.payload())
        return str(snap["id"])

    def snapshot(self, run_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/runs/{run_id}")

    def list_runs(self) -> List[Dict[str, Any]]:
        return list(self._request("GET", "/runs").get("runs") or [])

    def cancel(self, run_id: str) -> bool:
        return bool(self._request("POST", f"/runs/{run_id}/cancel", {}).get("cancelled"))

    def confirm(self, run_id: str, confirm_id: str, approved: bool) -> bool:
        body = {"confirm_id": confirm_id, "approved": bool(approved)}
        return bool(self._request("POST", f"/runs/{run_id}/confirm", body).get("accepted"))

    def events(self, run_id: str) -> Iterator[Dict[str, Any]]:
        """Yield the run's server-sent events until it settles.

        The stream replays from the run's start, so attaching late never loses
        the confirm request or the result.
        """
        req = urllib.request.Request(
            f"{self.base_url}/runs/{run_id}/events",
            headers={"Accept": "text/event-stream"},
        )
        try:
            resp = urllib.request.urlopen(req, timeout=self.stream_timeout)
        except (urllib.error.URLError, OSError) as e:
            raise PiSidecarError(f"cannot stream run {run_id}: {e}") from e
        with resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                event = json.loads(line[5:].strip())
                if event.get("type") == "close":
                    return
                yield event

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
        try:
            for event in self.events(run_id):
                kind = event.get("type")
                if kind == "state" and on_progress:
                    on_progress(str(event.get("progress") or ""))
                elif kind == "text" and on_text:
                    on_text(str(event.get("delta") or ""))
                elif kind == "confirm_request":
                    self._handle_confirm(run_id, event, on_confirm)
                elif kind == "result":
                    settled = RunResult(
                        id=run_id,
                        state=str(event.get("state") or "failed"),
                        result=str(event.get("result") or ""),
                        error=str(event.get("error") or ""),
                    )
        finally:
            stop_watch.set()
            if watcher:
                watcher.join(timeout=2.0)
        return settled

    def _handle_confirm(
        self,
        run_id: str,
        event: Dict[str, Any],
        on_confirm: Optional[ConfirmFn],
    ) -> None:
        request = ConfirmRequest(
            id=str(event.get("confirm_id") or ""),
            tool=str(event.get("tool") or ""),
            summary=str(event.get("summary") or ""),
            input=dict(event.get("input") or {}),
        )
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
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}")
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
