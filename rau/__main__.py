"""python -m rau [hub|face|all]"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time

from rau.env import load_dotenv
from rau.paths import ensure_dirs


def main(argv: list[str] | None = None) -> None:
    # Separates a real long-lived runtime from import-only test clients. Durable
    # recovery, schedulers, and the desktop pet are process services and should
    # never start merely because a module was imported.
    load_dotenv()
    ensure_dirs()
    parser = argparse.ArgumentParser(prog="rau")
    parser.add_argument(
        "mode",
        nargs="?",
        default="all",
        choices=["hub", "face", "all", "text", "doctor", "launch-agent"],
        help="run Rau, diagnose it, or manage its single LaunchAgent",
    )
    parser.add_argument(
        "launch_action",
        nargs="?",
        choices=["install", "status", "remove"],
        default="status",
    )
    parser.add_argument("--no-audio", action="store_true", help="Start face without mic loop")
    args = parser.parse_args(argv)

    if args.mode == "doctor":
        from rau.doctor import format_report, run_doctor

        report = run_doctor()
        print(format_report(report))
        raise SystemExit(0 if report["ok"] else 1)

    if args.mode == "launch-agent":
        from rau import launch_agent

        if args.launch_action == "install":
            print(launch_agent.install(no_audio=args.no_audio))
        else:
            print(getattr(launch_agent, args.launch_action)())
        return

    os.environ.setdefault("RAU_RUNTIME", "1")

    if args.mode in ("hub", "all", "text"):
        if args.mode == "hub":
            from rau.hub.server import main as hub_main
            from rau.pet import stop_pet

            try:
                hub_main()
            finally:
                stop_pet()
            return

        # hub in background thread
        def run_hub():
            import uvicorn
            from rau.hub.server import app
            from rau.providers.registry import load_settings

            s = load_settings()
            uvicorn.run(
                app,
                host=s.get("hub_host") or "127.0.0.1",
                port=int(s.get("hub_port") or 8765),
                log_level="warning",
            )

        t = threading.Thread(target=run_hub, daemon=True, name="rau-hub")
        t.start()
        time.sleep(0.6)
        print("Rau Hub up on http://127.0.0.1:8765")

    if args.mode in ("face", "all"):
        from rau.face.pipeline import start_face, stop_face
        from rau.pet import stop_pet

        start_face(with_audio=not args.no_audio)
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            stop_face()
            stop_pet()
            print("\nRau signing off.")
        return

    if args.mode == "text":
        from rau.pet import stop_pet

        print("Text mode: open the dashboard. Control via /api/control and chat endpoints.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            stop_pet()
            print("\nbye")
        return


if __name__ == "__main__":
    main(sys.argv[1:])
