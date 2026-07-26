from __future__ import annotations

import os
from pathlib import Path

from rau.activity import sanitize_activity
from rau.control.store import ControlStore


def test_schema_v3_activity_is_ordered_correlated_and_revisable(tmp_path: Path):
    store = ControlStore(tmp_path / "control.db")
    store.initialize()
    assert store.schema_status()["schema_version"] == 3

    first = store.create_activity_span(
        {
            "id": "span-1",
            "kind": "planning",
            "source": "test",
            "status": "running",
            "label": "Planning",
            "turn_id": "turn-1",
            "job_id": "job-1",
        }
    )
    second = store.create_activity_span(
        {
            "id": "span-2",
            "kind": "tool",
            "source": "test",
            "status": "running",
            "label": "Reading a file",
            "turn_id": "turn-1",
            "job_id": "job-1",
        }
    )
    assert second["seq"] > first["seq"]

    finished = store.update_activity_span(
        "span-2",
        {"status": "completed", "summary": "Read 3 lines", "ended": 10.0},
    )
    assert finished and finished["revision"] == 2
    assert [item["id"] for item in store.list_activity(turn_id="turn-1")] == [
        "span-1",
        "span-2",
    ]
    assert [item["id"] for item in store.list_activity(after_seq=first["seq"])] == [
        "span-2"
    ]


def test_activity_sanitizer_never_exports_payloads_or_credentials(monkeypatch):
    monkeypatch.setenv("RAU_TEST_API_KEY", "super-secret-credential")
    public = sanitize_activity(
        {
            "path": "rau/agent/tools.py",
            "url": "https://user:pass@example.com/path?token=secret",
            "authorization": "Bearer definitely-private",
            "text": "what the user typed",
            "file_content": "private source",
            "screenshot": "base64-image",
            "system_prompt": "hidden policy",
            "error": "failed with super-secret-credential",
            "exit_code": 1,
        }
    )
    encoded = repr(public)
    for forbidden in (
        "what the user typed",
        "private source",
        "base64-image",
        "hidden policy",
        "super-secret-credential",
        "user:pass",
        "?token=",
    ):
        assert forbidden not in encoded
    assert public["path"] == "rau/agent/tools.py"
    assert public["exit_code"] == 1


def test_activity_retention_keeps_active_spans(tmp_path: Path):
    store = ControlStore(tmp_path / "control.db")
    store.initialize()
    store.create_activity_span(
        {
            "id": "active",
            "kind": "execution",
            "source": "test",
            "status": "running",
            "label": "Working",
            "started": 1,
            "updated": 1,
        }
    )
    store.create_activity_span(
        {
            "id": "old",
            "kind": "completion",
            "source": "test",
            "status": "completed",
            "label": "Done",
            "started": 1,
            "updated": 1,
            "ended": 1,
        }
    )
    assert store.purge_activity(2) == 1
    assert store.get_activity_span("active") is not None
    assert store.get_activity_span("old") is None
