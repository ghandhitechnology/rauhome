#!/usr/bin/env python3
"""Measure Rau's 30-minute idle power baseline or compare two reports."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rau.power import comparison, measure, write_report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("measure")
    run.add_argument("--pid", type=int, required=True, help="Rau root process PID")
    run.add_argument("--duration", type=float, default=1800.0)
    run.add_argument("--interval", type=float, default=5.0)
    run.add_argument("--label", default="idle")
    run.add_argument("--output", type=Path, required=True)
    compare = subparsers.add_parser("compare")
    compare.add_argument("before", type=Path)
    compare.add_argument("after", type=Path)
    compare.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.command == "measure":
        report = measure(
            args.pid,
            duration_sec=args.duration,
            interval_sec=args.interval,
            label=args.label,
        )
        write_report(args.output, report)
    else:
        before = json.loads(args.before.read_text(encoding="utf-8"))
        after = json.loads(args.after.read_text(encoding="utf-8"))
        report = comparison(before, after)
        if args.output:
            write_report(args.output, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
