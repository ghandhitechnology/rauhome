"""Central resource-profile policy.

Profiles are intentionally data rather than scattered conditionals so every
runtime surface can make the same power/performance trade-off.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

PROFILES: Dict[str, Dict[str, Any]] = {
    "eco": {
        "max_parallel_jobs": 1,
        "face_max_tokens": 384,
        "worker_max_tokens": 2048,
        "worker_effort_ceiling": "medium",
        "idle_fps": 15,
        "active_fps": 30,
        "max_dpr": 1.0,
        "dream_enabled": False,
        "pi_idle_timeout_sec": 90,
    },
    "balanced": {
        "max_parallel_jobs": 3,
        "face_max_tokens": 512,
        "worker_max_tokens": 4096,
        "worker_effort_ceiling": "high",
        "idle_fps": 24,
        "active_fps": 30,
        "max_dpr": 1.5,
        "dream_enabled": True,
        "pi_idle_timeout_sec": 300,
    },
    "performance": {
        "max_parallel_jobs": 6,
        "face_max_tokens": 768,
        "worker_max_tokens": 8192,
        "worker_effort_ceiling": "max",
        "idle_fps": 60,
        "active_fps": 60,
        "max_dpr": 2.0,
        "dream_enabled": True,
        "pi_idle_timeout_sec": 600,
    },
}


def normalize_profile(value: Any) -> str:
    name = str(value or "balanced").lower()
    return name if name in PROFILES else "balanced"


def profile_policy(name: Any) -> Dict[str, Any]:
    normalized = normalize_profile(name)
    return {"name": normalized, **deepcopy(PROFILES[normalized])}


def current_profile() -> Dict[str, Any]:
    from rau.providers.registry import load_settings

    return profile_policy(load_settings().get("resource_profile"))
