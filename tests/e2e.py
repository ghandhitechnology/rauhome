"""
End-to-end smoke test against a real hub process.

The other suites fake the provider layer, which proves the message plumbing but
not that the server actually serves. This boots `rau.hub.server` on a spare
port and drives the real HTTP routes and the real `/ws/voice` socket, so a
change that breaks wiring, routing or the WebSocket handshake cannot pass
quietly.

No API keys required: the chat route is exercised for reachability and correct
error surfacing rather than for a model reply.

    python tests/e2e.py
"""
from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS: List[str] = []
FAIL: List[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  [{'ok  ' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def get(url: str, timeout: float = 10) -> Dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def post(url: str, body: Dict[str, Any], timeout: float = 30) -> Dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"_status": e.code, "_body": e.read().decode()[:200]}


def wait_up(base: str, proc: subprocess.Popen, timeout: float = 45) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            get(f"{base}/api/status", timeout=2)
            return True
        except Exception:
            time.sleep(0.4)
    return False


async def voice_socket(base_ws: str) -> Dict[str, Any]:
    """Drive the real /ws/voice endpoint the way the browser client does."""
    import websockets

    out: Dict[str, Any] = {"hello": None, "accepted_audio": False, "phases": []}
    async with websockets.connect(f"{base_ws}/ws/voice", open_timeout=10) as ws:
        out["hello"] = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        await ws.send(json.dumps({"t": "speech_start"}))
        # 200ms of silence at 16kHz mono PCM16 — shape matters, content does not.
        await ws.send(b"\x00\x00" * 3200)
        await ws.send(json.dumps({"t": "stop"}))
        out["accepted_audio"] = True
        try:
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=1.5)
                if isinstance(raw, str):
                    msg = json.loads(raw)
                    if msg.get("t") == "phase":
                        out["phases"].append(msg.get("phase"))
        except (asyncio.TimeoutError, Exception):
            pass
    return out


def main() -> int:
    print("=" * 62)
    print("Rau end-to-end (real hub process)")
    print("=" * 62)

    port = free_port()
    base = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "rau.hub.server:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "error"],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    try:
        print("\nboot")
        up = wait_up(base, proc)
        if not up:
            out = (proc.stdout.read().decode()[-1500:] if proc.stdout else "")
            check("hub starts", False, out)
            return 1
        check("hub starts", True, f"port {port}")

        print("\nHTTP surface")
        status = get(f"{base}/api/status")
        check("/api/status responds", "identity_ready" in status)
        check("hard_task view present", isinstance(status.get("hard_task"), dict))

        voice = get(f"{base}/api/voice/status")
        check("/api/voice/status responds", "stt" in voice, str(voice.get("stt", {}).get("provider")))

        jobs = get(f"{base}/api/jobs")
        check("/api/jobs responds", isinstance(jobs.get("jobs"), list))

        catalog = get(f"{base}/api/models/catalog")
        check("catalog includes stt providers", "stt_providers" in catalog)

        print("\nchat route (reachability, not a model reply)")
        reply = post(f"{base}/api/chat", {"text": "ping"})
        # With no provider key the hub answers with a graceful error string
        # rather than a 500 — that path must keep working.
        served = "reply" in reply or reply.get("_status") == 400
        check("/api/chat is served", served, str(reply)[:90])
        if "reply" in reply:
            check("chat reply is a string", isinstance(reply["reply"], str), str(reply["reply"])[:60])

        log = get(f"{base}/api/log")
        check("chat turn reached the log", any(m.get("role") == "user" for m in log.get("log", [])))

        print("\nvoice socket")
        try:
            res = asyncio.run(voice_socket(f"ws://127.0.0.1:{port}"))
            hello = res["hello"] or {}
            check("/ws/voice handshake", hello.get("t") == "hello", str(hello)[:90])
            check("declares sample rates", hello.get("sample_rate_in") == 16000
                  and hello.get("sample_rate_out") == 24000)
            check("accepts binary mic frames", res["accepted_audio"])
        except Exception as e:  # noqa: BLE001
            check("/ws/voice handshake", False, f"{type(e).__name__}: {e}")

        print("\njob lifecycle over HTTP")
        started = post(f"{base}/api/jobs", {"goal": "e2e smoke goal"})
        if started.get("ok"):
            check("job starts via REST", True, started["id"][:8])
            time.sleep(0.5)
            cancelled = post(f"{base}/api/jobs/{started['id']}/cancel", {})
            check("job cancels via REST", bool(cancelled.get("ok")), str(cancelled)[:70])
        else:
            check("job starts via REST", False, str(started)[:90])

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    print("\n" + "=" * 62)
    print(f"{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("failed: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
