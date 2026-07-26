"""Repeatable idle CPU, memory, and wakeup measurements for Rau."""
from __future__ import annotations

import ctypes
import json
import os
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


class _RUsageInfoV2(ctypes.Structure):
    _fields_ = [
        ("uuid", ctypes.c_ubyte * 16),
        ("user_time", ctypes.c_uint64),
        ("system_time", ctypes.c_uint64),
        ("pkg_idle_wakeups", ctypes.c_uint64),
        ("interrupt_wakeups", ctypes.c_uint64),
        ("pageins", ctypes.c_uint64),
        ("wired_size", ctypes.c_uint64),
        ("resident_size", ctypes.c_uint64),
        ("phys_footprint", ctypes.c_uint64),
        ("proc_start_abstime", ctypes.c_uint64),
        ("proc_exit_abstime", ctypes.c_uint64),
        ("child_user_time", ctypes.c_uint64),
        ("child_system_time", ctypes.c_uint64),
        ("child_pkg_idle_wakeups", ctypes.c_uint64),
        ("child_interrupt_wakeups", ctypes.c_uint64),
        ("child_pageins", ctypes.c_uint64),
        ("child_elapsed_abstime", ctypes.c_uint64),
    ]


def _darwin_wakeups(pid: int) -> Optional[int]:
    if os.uname().sysname != "Darwin":
        return None
    try:
        libproc = ctypes.CDLL("/usr/lib/libproc.dylib")
        proc_pid_rusage = libproc.proc_pid_rusage
        proc_pid_rusage.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(_RUsageInfoV2),
        ]
        proc_pid_rusage.restype = ctypes.c_int
        usage = _RUsageInfoV2()
        if proc_pid_rusage(int(pid), 2, ctypes.byref(usage)) != 0:
            return None
        return int(usage.pkg_idle_wakeups + usage.interrupt_wakeups)
    except Exception:
        return None


def _process_snapshot() -> Dict[int, Dict[str, Any]]:
    completed = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,%cpu=,rss=,comm="],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    result: Dict[int, Dict[str, Any]] = {}
    for line in completed.stdout.splitlines():
        fields = line.strip().split(None, 4)
        if len(fields) < 4:
            continue
        try:
            pid, ppid = int(fields[0]), int(fields[1])
            cpu, rss = float(fields[2]), int(fields[3])
        except ValueError:
            continue
        result[pid] = {
            "pid": pid,
            "ppid": ppid,
            "cpu_percent": cpu,
            "rss_kib": rss,
            "command": fields[4] if len(fields) > 4 else "",
        }
    return result


def _tree_pids(root_pid: int, processes: Dict[int, Dict[str, Any]]) -> set[int]:
    selected = {int(root_pid)}
    changed = True
    while changed:
        changed = False
        for pid, process in processes.items():
            if pid not in selected and process["ppid"] in selected:
                selected.add(pid)
                changed = True
    return selected


def _percentile(values: Iterable[float], percentile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    index = (len(ordered) - 1) * percentile
    lower = int(index)
    upper = min(len(ordered) - 1, lower + 1)
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def summarize(
    *,
    pid: int,
    label: str,
    started_at: float,
    ended_at: float,
    samples: list[Dict[str, Any]],
    wakeup_deltas: Dict[int, int],
) -> Dict[str, Any]:
    cpu = [float(sample["cpu_percent"]) for sample in samples]
    rss = [int(sample["rss_kib"]) for sample in samples]
    duration = max(0.001, ended_at - started_at)
    total_wakeups = sum(max(0, int(value)) for value in wakeup_deltas.values())
    return {
        "schema_version": 1,
        "label": label,
        "root_pid": int(pid),
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_sec": duration,
        "sample_count": len(samples),
        "median_cpu_percent": statistics.median(cpu) if cpu else 0.0,
        "p95_cpu_percent": _percentile(cpu, 0.95),
        "mean_rss_mib": (statistics.fmean(rss) / 1024.0) if rss else 0.0,
        "wakeups": total_wakeups if wakeup_deltas else None,
        "wakeups_per_sec": (total_wakeups / duration) if wakeup_deltas else None,
        "observed_pids": sorted(
            {int(process_pid) for sample in samples for process_pid in sample["pids"]}
        ),
        "samples": samples,
    }


def measure(
    pid: int,
    *,
    duration_sec: float = 1800.0,
    interval_sec: float = 5.0,
    label: str = "idle",
) -> Dict[str, Any]:
    if duration_sec <= 0 or interval_sec <= 0:
        raise ValueError("duration and interval must be positive")
    if pid <= 0:
        raise ValueError("pid must be positive")
    started_at = time.time()
    deadline = time.monotonic() + duration_sec
    samples: list[Dict[str, Any]] = []
    wakeup_first: Dict[int, int] = {}
    wakeup_last: Dict[int, int] = {}
    while True:
        processes = _process_snapshot()
        pids = _tree_pids(pid, processes)
        live = [processes[child] for child in pids if child in processes]
        if not live:
            raise RuntimeError(f"process tree rooted at PID {pid} is not running")
        for child in pids:
            wakeups = _darwin_wakeups(child)
            if wakeups is not None:
                wakeup_first.setdefault(child, wakeups)
                wakeup_last[child] = wakeups
        samples.append(
            {
                "at": time.time(),
                "pids": sorted(pids),
                "cpu_percent": sum(float(process["cpu_percent"]) for process in live),
                "rss_kib": sum(int(process["rss_kib"]) for process in live),
            }
        )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(interval_sec, remaining))
    ended_at = time.time()
    wakeup_deltas = {
        child: wakeup_last[child] - first
        for child, first in wakeup_first.items()
        if child in wakeup_last
    }
    return summarize(
        pid=pid,
        label=label,
        started_at=started_at,
        ended_at=ended_at,
        samples=samples,
        wakeup_deltas=wakeup_deltas,
    )


def comparison(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    def reduction(metric: str) -> Optional[float]:
        old = before.get(metric)
        new = after.get(metric)
        if old is None or new is None or float(old) <= 0:
            return None
        return (float(old) - float(new)) / float(old) * 100.0

    cpu_reduction = reduction("median_cpu_percent")
    wakeup_reduction = reduction("wakeups_per_sec")
    available = [
        value for value in (cpu_reduction, wakeup_reduction) if value is not None
    ]
    return {
        "schema_version": 1,
        "before": before.get("label"),
        "after": after.get("label"),
        "median_cpu_reduction_percent": cpu_reduction,
        "wakeup_reduction_percent": wakeup_reduction,
        "target_reduction_percent": 50.0,
        "passes_available_metrics": bool(available)
        and all(value >= 50.0 for value in available),
    }


def write_report(path: Path, report: Dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
