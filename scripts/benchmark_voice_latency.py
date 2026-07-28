#!/usr/bin/env python3
"""Validate an alternating Normal/Hyper voice latency run from Rau logs."""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from pathlib import Path

RECORD = re.compile(
    r"voice_eou_to_playback_ms=(?P<ms>\d+(?:\.\d+)?)\s+"
    r"profile=(?P<profile>normal|hyper)\b"
)


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile, suitable for a small acceptance sample."""
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[rank - 1]


def parse_records(text: str) -> list[tuple[str, float]]:
    return [
        (match.group("profile"), float(match.group("ms")))
        for match in RECORD.finditer(text)
    ]


def summarize(records: list[tuple[str, float]], per_profile: int) -> dict:
    selected: list[tuple[str, float]] = []
    counts = {"normal": 0, "hyper": 0}
    for profile, value in records:
        expected = "normal" if len(selected) % 2 == 0 else "hyper"
        if profile != expected:
            raise ValueError(
                f"records must alternate normal/hyper; "
                f"item {len(selected) + 1} is {profile}"
            )
        selected.append((profile, value))
        counts[profile] += 1
        if all(count >= per_profile for count in counts.values()):
            break

    if any(count < per_profile for count in counts.values()):
        raise ValueError(
            f"need {per_profile} records per profile; found "
            f"normal={counts['normal']} hyper={counts['hyper']}"
        )
    values = {
        profile: [value for item_profile, value in selected if item_profile == profile]
        for profile in ("normal", "hyper")
    }
    result = {
        profile: {
            "turns": len(items),
            "median_ms": round(statistics.median(items), 1),
            "p95_ms": round(percentile(items, 0.95), 1),
        }
        for profile, items in values.items()
    }
    result["passed"] = bool(
        result["hyper"]["median_ms"] < 1500
        and result["hyper"]["p95_ms"] <= result["normal"]["p95_ms"]
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read Rau voice_eou_to_playback_ms logs from a warm run that "
            "alternates Normal then Hyper using the same prompt/configuration."
        )
    )
    parser.add_argument("log", type=Path, help="Rau log file, or '-' for stdin")
    parser.add_argument(
        "--per-profile",
        type=int,
        default=30,
        help="required turns for each profile (default: 30; 60 total)",
    )
    args = parser.parse_args()
    if args.per_profile < 1:
        parser.error("--per-profile must be positive")
    text = sys.stdin.read() if str(args.log) == "-" else args.log.read_text()
    try:
        result = summarize(parse_records(text), args.per_profile)
    except ValueError as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, indent=2))
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
