"""SQLite/WAL control-plane persistence.

The in-process state module remains the low-latency view used by the face and
websocket clients. This store is the durable source of truth for work that must
survive a hub restart.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from rau.paths import CONTROL_DB, ensure_dirs

SCHEMA_VERSION = 3
ACTIVE_STATES = (
    "queued",
    "planning",
    "running",
    "verifying",
    "awaiting_confirm",
)
TERMINAL_STATES = ("completed", "failed", "cancelled", "interrupted")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _object(raw: Any, default: Any) -> Any:
    if raw in (None, ""):
        return default
    try:
        return json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


class ControlStore:
    """Small transactional repository with one connection per operation."""

    def __init__(self, path: Path | str = CONTROL_DB):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._ready = False

    def initialize(self) -> None:
        with self._lock:
            if self._ready:
                return
            ensure_dirs()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as db:
                db.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS schema_meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS jobs (
                        id TEXT PRIMARY KEY,
                        goal TEXT NOT NULL,
                        state TEXT NOT NULL,
                        progress TEXT NOT NULL DEFAULT '',
                        result TEXT NOT NULL DEFAULT '',
                        parent_id TEXT,
                        depth INTEGER NOT NULL DEFAULT 1,
                        plan_json TEXT NOT NULL DEFAULT '{}',
                        budget_json TEXT NOT NULL DEFAULT '{}',
                        executor TEXT NOT NULL DEFAULT 'python',
                        attempt INTEGER NOT NULL DEFAULT 0,
                        lease_owner TEXT,
                        lease_expires REAL,
                        scheduled_run_id TEXT,
                        origin_turn_id TEXT,
                        plan_revision INTEGER NOT NULL DEFAULT 1,
                        terminal_reason TEXT NOT NULL DEFAULT '',
                        created REAL NOT NULL,
                        updated REAL NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS jobs_state_idx
                        ON jobs(state, updated);

                    CREATE TABLE IF NOT EXISTS steps (
                        id TEXT PRIMARY KEY,
                        job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                        ordinal INTEGER NOT NULL,
                        title TEXT NOT NULL,
                        goal TEXT NOT NULL DEFAULT '',
                        state TEXT NOT NULL,
                        executor TEXT NOT NULL DEFAULT 'python',
                        effect_class TEXT NOT NULL DEFAULT 'read',
                        capabilities_json TEXT NOT NULL DEFAULT '[]',
                        dependencies_json TEXT NOT NULL DEFAULT '[]',
                        expected_output_json TEXT NOT NULL DEFAULT '{}',
                        expected_evidence_json TEXT NOT NULL DEFAULT '[]',
                        preconditions_json TEXT NOT NULL DEFAULT '[]',
                        result_json TEXT NOT NULL DEFAULT '{}',
                        evidence_json TEXT NOT NULL DEFAULT '[]',
                        attempt INTEGER NOT NULL DEFAULT 0,
                        retry_budget INTEGER NOT NULL DEFAULT 0,
                        strategy TEXT NOT NULL DEFAULT '',
                        timeout_sec REAL NOT NULL DEFAULT 300,
                        concurrency_key TEXT NOT NULL DEFAULT '',
                        plan_revision INTEGER NOT NULL DEFAULT 1,
                        idempotency_key TEXT,
                        effect_state TEXT NOT NULL DEFAULT 'none',
                        lease_owner TEXT,
                        lease_expires REAL,
                        deadline REAL,
                        terminal_reason TEXT NOT NULL DEFAULT '',
                        created REAL NOT NULL,
                        updated REAL NOT NULL,
                        UNIQUE(job_id, ordinal)
                    );
                    CREATE INDEX IF NOT EXISTS steps_job_idx
                        ON steps(job_id, ordinal);

                    CREATE TABLE IF NOT EXISTS confirmations (
                        id TEXT PRIMARY KEY,
                        job_id TEXT NOT NULL,
                        step_id TEXT,
                        tool TEXT NOT NULL,
                        arguments_digest TEXT NOT NULL,
                        target_digest TEXT NOT NULL DEFAULT '',
                        summary TEXT NOT NULL,
                        state TEXT NOT NULL DEFAULT 'pending',
                        approved INTEGER,
                        created REAL NOT NULL,
                        expires REAL NOT NULL,
                        decided REAL
                    );
                    CREATE INDEX IF NOT EXISTS confirms_pending_idx
                        ON confirmations(state, expires, created);

                    CREATE TABLE IF NOT EXISTS schedules (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        enabled INTEGER NOT NULL DEFAULT 1,
                        goal TEXT NOT NULL,
                        trigger_kind TEXT NOT NULL,
                        trigger_json TEXT NOT NULL,
                        timezone TEXT NOT NULL,
                        resource_profile TEXT NOT NULL DEFAULT 'balanced',
                        permission_policy TEXT NOT NULL DEFAULT 'approval',
                        overlap_policy TEXT NOT NULL DEFAULT 'coalesce',
                        budget_json TEXT NOT NULL DEFAULT '{}',
                        next_run_at REAL,
                        last_nominal_at REAL,
                        revision INTEGER NOT NULL DEFAULT 1,
                        deleted_at REAL,
                        created REAL NOT NULL,
                        updated REAL NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS schedules_due_idx
                        ON schedules(enabled, next_run_at);

                    CREATE TABLE IF NOT EXISTS schedule_runs (
                        id TEXT PRIMARY KEY,
                        schedule_id TEXT NOT NULL REFERENCES schedules(id) ON DELETE CASCADE,
                        schedule_revision INTEGER NOT NULL,
                        nominal_at REAL NOT NULL,
                        nominal_key TEXT NOT NULL,
                        enqueued_at REAL NOT NULL,
                        job_id TEXT,
                        state TEXT NOT NULL,
                        attempt INTEGER NOT NULL DEFAULT 0,
                        retry_at REAL,
                        coalesced_count INTEGER NOT NULL DEFAULT 1,
                        missed_from REAL,
                        missed_to REAL,
                        outcome_json TEXT NOT NULL DEFAULT '{}',
                        created REAL NOT NULL,
                        updated REAL NOT NULL,
                        UNIQUE(schedule_id, schedule_revision, nominal_key)
                    );
                    CREATE INDEX IF NOT EXISTS schedule_runs_schedule_idx
                        ON schedule_runs(schedule_id, created DESC);

                    CREATE TABLE IF NOT EXISTS computer_sessions (
                        id TEXT PRIMARY KEY,
                        job_id TEXT,
                        step_id TEXT,
                        state TEXT NOT NULL,
                        app_json TEXT NOT NULL DEFAULT '{}',
                        window_json TEXT NOT NULL DEFAULT '{}',
                        latest_observation_id TEXT,
                        lease_owner TEXT,
                        lease_expires REAL,
                        deadline REAL,
                        effect_state TEXT NOT NULL DEFAULT 'none',
                        result_json TEXT NOT NULL DEFAULT '{}',
                        created REAL NOT NULL,
                        updated REAL NOT NULL
                    );
                    CREATE UNIQUE INDEX IF NOT EXISTS computer_active_lease_idx
                        ON computer_sessions((1))
                        WHERE state IN ('active', 'acting', 'verifying', 'awaiting_review');

                    CREATE TABLE IF NOT EXISTS computer_observations (
                        id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL REFERENCES computer_sessions(id),
                        fingerprint TEXT NOT NULL,
                        app_json TEXT NOT NULL DEFAULT '{}',
                        window_json TEXT NOT NULL DEFAULT '{}',
                        displays_json TEXT NOT NULL DEFAULT '[]',
                        accessibility_json TEXT NOT NULL DEFAULT '[]',
                        image_hash TEXT NOT NULL DEFAULT '',
                        width INTEGER NOT NULL DEFAULT 0,
                        height INTEGER NOT NULL DEFAULT 0,
                        user_idle_sec REAL,
                        created REAL NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS computer_observations_session_idx
                        ON computer_observations(session_id, created DESC);

                    CREATE TABLE IF NOT EXISTS idempotency (
                        key TEXT PRIMARY KEY,
                        scope TEXT NOT NULL,
                        request_digest TEXT NOT NULL,
                        state TEXT NOT NULL,
                        result_json TEXT NOT NULL DEFAULT '{}',
                        created REAL NOT NULL,
                        updated REAL NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS control_events (
                        seq INTEGER PRIMARY KEY AUTOINCREMENT,
                        kind TEXT NOT NULL,
                        entity_type TEXT NOT NULL,
                        entity_id TEXT,
                        payload_json TEXT NOT NULL,
                        created REAL NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS activity_spans (
                        seq INTEGER PRIMARY KEY AUTOINCREMENT,
                        id TEXT NOT NULL UNIQUE,
                        revision INTEGER NOT NULL DEFAULT 1,
                        kind TEXT NOT NULL,
                        source TEXT NOT NULL,
                        status TEXT NOT NULL,
                        label TEXT NOT NULL,
                        summary TEXT NOT NULL DEFAULT '',
                        details_json TEXT NOT NULL DEFAULT '{}',
                        turn_id TEXT,
                        job_id TEXT,
                        step_id TEXT,
                        parent_span_id TEXT,
                        started REAL NOT NULL,
                        updated REAL NOT NULL,
                        ended REAL
                    );
                    CREATE INDEX IF NOT EXISTS activity_turn_idx
                        ON activity_spans(turn_id, seq);
                    CREATE INDEX IF NOT EXISTS activity_job_idx
                        ON activity_spans(job_id, seq);
                    CREATE INDEX IF NOT EXISTS activity_active_idx
                        ON activity_spans(status, updated);
                    """
                )
                # Migrations are additive and safe to re-run. SQLite cannot
                # express IF NOT EXISTS for ADD COLUMN on supported macOS
                # versions, so inspect before altering.
                run_columns = {
                    str(row["name"])
                    for row in db.execute("PRAGMA table_info(schedule_runs)")
                }
                if "retry_at" not in run_columns:
                    db.execute("ALTER TABLE schedule_runs ADD COLUMN retry_at REAL")
                job_columns = {
                    str(row["name"]) for row in db.execute("PRAGMA table_info(jobs)")
                }
                if "origin_turn_id" not in job_columns:
                    db.execute("ALTER TABLE jobs ADD COLUMN origin_turn_id TEXT")
                if "plan_revision" not in job_columns:
                    db.execute(
                        "ALTER TABLE jobs ADD COLUMN plan_revision INTEGER "
                        "NOT NULL DEFAULT 1"
                    )
                step_columns = {
                    str(row["name"]) for row in db.execute("PRAGMA table_info(steps)")
                }
                for column, declaration in (
                    ("goal", "TEXT NOT NULL DEFAULT ''"),
                    ("effect_class", "TEXT NOT NULL DEFAULT 'read'"),
                    ("expected_output_json", "TEXT NOT NULL DEFAULT '{}'"),
                    ("retry_budget", "INTEGER NOT NULL DEFAULT 0"),
                    ("timeout_sec", "REAL NOT NULL DEFAULT 300"),
                    ("concurrency_key", "TEXT NOT NULL DEFAULT ''"),
                    ("plan_revision", "INTEGER NOT NULL DEFAULT 1"),
                ):
                    if column not in step_columns:
                        db.execute(
                            f"ALTER TABLE steps ADD COLUMN {column} {declaration}"
                        )
                # v1 accidentally indexed the state value, allowing one
                # session per active state. Recreate it as a constant partial
                # index so exactly one active machine lease exists globally.
                db.execute("DROP INDEX IF EXISTS computer_active_lease_idx")
                db.execute(
                    """
                    UPDATE computer_sessions
                    SET state='interrupted', lease_owner=NULL,
                        lease_expires=NULL, updated=?
                    WHERE state IN
                        ('active', 'acting', 'verifying', 'awaiting_review')
                      AND id NOT IN (
                        SELECT id FROM computer_sessions
                        WHERE state IN
                            ('active', 'acting', 'verifying', 'awaiting_review')
                        ORDER BY updated DESC LIMIT 1
                      )
                    """,
                    (time.time(),),
                )
                db.execute(
                    """
                    CREATE UNIQUE INDEX computer_active_lease_idx
                    ON computer_sessions((1))
                    WHERE state IN
                        ('active', 'acting', 'verifying', 'awaiting_review')
                    """
                )
                db.execute(
                    """
                    INSERT INTO schema_meta(key, value) VALUES('schema_version', ?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value
                    """,
                    (str(SCHEMA_VERSION),),
                )
            self._ready = True

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(str(self.path), timeout=10.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        try:
            with db:
                yield db
        finally:
            db.close()

    def _ensure(self) -> None:
        if not self._ready:
            self.initialize()

    def append_event(
        self,
        kind: str,
        entity_type: str,
        entity_id: Optional[str],
        payload: Dict[str, Any],
        *,
        created: Optional[float] = None,
    ) -> int:
        self._ensure()
        with self._lock, self._connect() as db:
            cur = db.execute(
                """
                INSERT INTO control_events(kind, entity_type, entity_id, payload_json, created)
                VALUES(?,?,?,?,?)
                """,
                (kind, entity_type, entity_id, _json(payload), created or time.time()),
            )
            return int(cur.lastrowid)

    def create_activity_span(self, span: Dict[str, Any]) -> Dict[str, Any]:
        """Persist a public, already-sanitized activity span."""
        self._ensure()
        now = time.time()
        with self._lock, self._connect() as db:
            db.execute(
                """
                INSERT INTO activity_spans(
                    id, revision, kind, source, status, label, summary,
                    details_json, turn_id, job_id, step_id, parent_span_id,
                    started, updated, ended
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    str(span["id"]),
                    int(span.get("revision") or 1),
                    str(span.get("kind") or "execution"),
                    str(span.get("source") or "rau"),
                    str(span.get("status") or "running"),
                    str(span.get("label") or "Working"),
                    str(span.get("summary") or ""),
                    _json(span.get("details") or {}),
                    span.get("turn_id"),
                    span.get("job_id"),
                    span.get("step_id"),
                    span.get("parent_span_id"),
                    float(span.get("started") or now),
                    float(span.get("updated") or now),
                    span.get("ended"),
                ),
            )
            row = db.execute(
                "SELECT * FROM activity_spans WHERE id=?", (str(span["id"]),)
            ).fetchone()
        assert row is not None
        return self._activity_row(row)

    def update_activity_span(
        self, span_id: str, changes: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        self._ensure()
        allowed = {
            "status",
            "label",
            "summary",
            "details",
            "ended",
            "updated",
        }
        assignments: List[str] = []
        values: List[Any] = []
        for key, value in changes.items():
            if key not in allowed:
                continue
            column = "details_json" if key == "details" else key
            if key == "details":
                value = _json(value or {})
            assignments.append(f"{column}=?")
            values.append(value)
        if not assignments:
            return self.get_activity_span(span_id)
        assignments.extend(("revision=revision+1", "updated=?"))
        values.append(float(changes.get("updated") or time.time()))
        values.append(span_id)
        with self._lock, self._connect() as db:
            db.execute(
                f"UPDATE activity_spans SET {', '.join(assignments)} WHERE id=?",
                tuple(values),
            )
            row = db.execute(
                "SELECT * FROM activity_spans WHERE id=?", (span_id,)
            ).fetchone()
        return self._activity_row(row) if row else None

    def get_activity_span(self, span_id: str) -> Optional[Dict[str, Any]]:
        self._ensure()
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT * FROM activity_spans WHERE id=?", (span_id,)
            ).fetchone()
        return self._activity_row(row) if row else None

    def list_activity(
        self,
        *,
        turn_id: Optional[str] = None,
        job_id: Optional[str] = None,
        after_seq: int = 0,
        limit: int = 200,
        active_only: bool = False,
    ) -> List[Dict[str, Any]]:
        self._ensure()
        cursor = max(0, int(after_seq))
        clauses = ["seq>?"]
        values: List[Any] = [cursor]
        if turn_id:
            clauses.append("turn_id=?")
            values.append(turn_id)
        if job_id:
            clauses.append("job_id=?")
            values.append(job_id)
        if active_only:
            clauses.append("status IN ('queued','running','awaiting_confirm')")
        values.append(max(1, min(1000, int(limit))))
        order = "seq" if cursor else "seq DESC"
        with self._lock, self._connect() as db:
            rows = db.execute(
                f"""
                SELECT * FROM activity_spans
                WHERE {' AND '.join(clauses)}
                ORDER BY {order} LIMIT ?
                """,
                tuple(values),
            ).fetchall()
        values_out = [self._activity_row(row) for row in rows]
        return values_out if cursor else list(reversed(values_out))

    def purge_activity(self, before: float) -> int:
        self._ensure()
        with self._lock, self._connect() as db:
            cursor = db.execute(
                """
                DELETE FROM activity_spans
                WHERE updated<? AND status NOT IN
                    ('queued','running','awaiting_confirm')
                """,
                (float(before),),
            )
            return int(cursor.rowcount)

    def claim_idempotency(
        self, key: str, scope: str, request: Any
    ) -> Dict[str, Any]:
        """Atomically claim an effect or return its prior durable disposition."""
        self._ensure()
        now = time.time()
        digest = self.arguments_digest(request)
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT * FROM idempotency WHERE key=?", (key,)
            ).fetchone()
            if row is not None:
                if row["request_digest"] != digest:
                    return {"status": "conflict"}
                return {
                    "status": str(row["state"]),
                    "result": _object(row["result_json"], {}),
                }
            db.execute(
                """
                INSERT INTO idempotency(
                    key, scope, request_digest, state, result_json,
                    created, updated
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (key, scope, digest, "in_progress", "{}", now, now),
            )
        return {"status": "claimed"}

    def settle_idempotency(
        self, key: str, state: str, result: Any
    ) -> bool:
        self._ensure()
        if state not in {"completed", "failed", "unknown_effect"}:
            raise ValueError("invalid idempotency state")
        with self._lock, self._connect() as db:
            cursor = db.execute(
                """
                UPDATE idempotency SET state=?, result_json=?, updated=?
                WHERE key=?
                """,
                (state, _json(result), time.time(), key),
            )
            return cursor.rowcount == 1

    def upsert_job(self, job: Dict[str, Any]) -> None:
        self._ensure()
        now = time.time()
        with self._lock, self._connect() as db:
            db.execute(
                """
                INSERT INTO jobs(
                    id, goal, state, progress, result, parent_id, depth,
                    plan_json, budget_json, executor, attempt, lease_owner,
                    lease_expires, scheduled_run_id, origin_turn_id,
                    plan_revision, terminal_reason, created, updated
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    state=excluded.state, progress=excluded.progress,
                    result=excluded.result, parent_id=excluded.parent_id,
                    depth=excluded.depth, plan_json=excluded.plan_json,
                    budget_json=excluded.budget_json, executor=excluded.executor,
                    attempt=excluded.attempt, lease_owner=excluded.lease_owner,
                    lease_expires=excluded.lease_expires,
                    scheduled_run_id=excluded.scheduled_run_id,
                    origin_turn_id=excluded.origin_turn_id,
                    plan_revision=excluded.plan_revision,
                    terminal_reason=excluded.terminal_reason,
                    updated=excluded.updated
                """,
                (
                    job["id"],
                    str(job.get("goal") or ""),
                    str(job.get("state") or "queued"),
                    str(job.get("progress") or ""),
                    str(job.get("result") or ""),
                    job.get("parent_id"),
                    int(job.get("depth") or 1),
                    _json(job.get("plan") or {}),
                    _json(job.get("budget") or {}),
                    str(job.get("executor") or "python"),
                    int(job.get("attempt") or 0),
                    job.get("lease_owner"),
                    job.get("lease_expires"),
                    job.get("scheduled_run_id"),
                    job.get("origin_turn_id"),
                    int(job.get("plan_revision") or 1),
                    str(job.get("terminal_reason") or ""),
                    float(job.get("created") or now),
                    float(job.get("updated") or now),
                ),
            )

    def load_jobs(self, *, limit: int = 100) -> List[Dict[str, Any]]:
        self._ensure()
        with self._lock, self._connect() as db:
            rows = db.execute(
                "SELECT * FROM jobs ORDER BY created DESC LIMIT ?",
                (max(1, min(1000, int(limit))),),
            ).fetchall()
        return [self._job_row(row) for row in reversed(rows)]

    def renew_job_lease(
        self, job_id: str, owner: str, expires: float
    ) -> bool:
        self._ensure()
        with self._lock, self._connect() as db:
            cursor = db.execute(
                """
                UPDATE jobs SET lease_owner=?, lease_expires=?, updated=?
                WHERE id=? AND state IN
                    ('queued','planning','running','verifying')
                """,
                (owner, float(expires), time.time(), job_id),
            )
            return cursor.rowcount == 1

    def release_job_lease(self, job_id: str) -> None:
        self._ensure()
        with self._lock, self._connect() as db:
            db.execute(
                """
                UPDATE jobs SET lease_owner=NULL, lease_expires=NULL, updated=?
                WHERE id=?
                """,
                (time.time(), job_id),
            )

    def upsert_step(self, step: Dict[str, Any]) -> None:
        self._ensure()
        now = time.time()
        with self._lock, self._connect() as db:
            db.execute(
                """
                INSERT INTO steps(
                    id, job_id, ordinal, title, goal, state, executor,
                    effect_class,
                    capabilities_json, dependencies_json,
                    expected_output_json, expected_evidence_json,
                    preconditions_json, result_json,
                    evidence_json, attempt, retry_budget, strategy,
                    timeout_sec, concurrency_key, plan_revision, idempotency_key,
                    effect_state, lease_owner, lease_expires, deadline,
                    terminal_reason, created, updated
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title, goal=excluded.goal,
                    state=excluded.state, executor=excluded.executor,
                    effect_class=excluded.effect_class,
                    capabilities_json=excluded.capabilities_json,
                    dependencies_json=excluded.dependencies_json,
                    expected_output_json=excluded.expected_output_json,
                    expected_evidence_json=excluded.expected_evidence_json,
                    preconditions_json=excluded.preconditions_json,
                    result_json=excluded.result_json,
                    evidence_json=excluded.evidence_json,
                    attempt=excluded.attempt,
                    retry_budget=excluded.retry_budget,
                    strategy=excluded.strategy,
                    timeout_sec=excluded.timeout_sec,
                    concurrency_key=excluded.concurrency_key,
                    plan_revision=excluded.plan_revision,
                    idempotency_key=excluded.idempotency_key,
                    effect_state=excluded.effect_state,
                    lease_owner=excluded.lease_owner,
                    lease_expires=excluded.lease_expires,
                    deadline=excluded.deadline,
                    terminal_reason=excluded.terminal_reason,
                    updated=excluded.updated
                """,
                (
                    step["id"],
                    step["job_id"],
                    int(step.get("ordinal") or 0),
                    str(step.get("title") or ""),
                    str(step.get("goal") or step.get("title") or ""),
                    str(step.get("state") or "queued"),
                    str(step.get("executor") or "python"),
                    str(step.get("effect_class") or "read"),
                    _json(step.get("capabilities") or []),
                    _json(step.get("dependencies") or []),
                    _json(step.get("expected_output") or {}),
                    _json(step.get("expected_evidence") or []),
                    _json(step.get("preconditions") or []),
                    _json(step.get("result") or {}),
                    _json(step.get("evidence") or []),
                    int(step.get("attempt") or 0),
                    int(step.get("retry_budget") or 0),
                    str(step.get("strategy") or ""),
                    float(step.get("timeout_sec") or 300),
                    str(step.get("concurrency_key") or ""),
                    int(step.get("plan_revision") or 1),
                    step.get("idempotency_key"),
                    str(step.get("effect_state") or "none"),
                    step.get("lease_owner"),
                    step.get("lease_expires"),
                    step.get("deadline"),
                    str(step.get("terminal_reason") or ""),
                    float(step.get("created") or now),
                    float(step.get("updated") or now),
                ),
            )

    def list_steps(self, job_id: str) -> List[Dict[str, Any]]:
        self._ensure()
        with self._lock, self._connect() as db:
            rows = db.execute(
                "SELECT * FROM steps WHERE job_id=? ORDER BY ordinal", (job_id,)
            ).fetchall()
        return [self._step_row(row) for row in rows]

    def save_confirmation(self, payload: Dict[str, Any]) -> None:
        self._ensure()
        now = time.time()
        arguments = payload.get("arguments") or {}
        target = payload.get("target") or {}
        with self._lock, self._connect() as db:
            db.execute(
                """
                INSERT INTO confirmations(
                    id, job_id, step_id, tool, arguments_digest, target_digest,
                    summary, state, created, expires
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    summary=excluded.summary,
                    arguments_digest=excluded.arguments_digest,
                    target_digest=excluded.target_digest,
                    expires=excluded.expires
                """,
                (
                    str(payload["id"]),
                    str(payload["job_id"]),
                    payload.get("step_id"),
                    str(payload.get("tool") or ""),
                    self.arguments_digest(arguments),
                    self.arguments_digest(target) if target else "",
                    str(payload.get("summary") or ""),
                    "pending",
                    float(payload.get("created") or now),
                    float(payload.get("expires") or now),
                ),
            )

    def decide_confirmation(
        self,
        confirm_id: str,
        approved: bool,
        *,
        arguments: Any = None,
        target: Any = None,
        now: Optional[float] = None,
    ) -> bool:
        """Settle an exact pending gate; optional digests reject stale decisions."""
        self._ensure()
        stamp = now or time.time()
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT * FROM confirmations WHERE id=?",
                (confirm_id,),
            ).fetchone()
            if row is None or row["state"] != "pending" or float(row["expires"]) <= stamp:
                return False
            if arguments is not None and row["arguments_digest"] != self.arguments_digest(arguments):
                return False
            if target is not None and row["target_digest"] != self.arguments_digest(target):
                return False
            cur = db.execute(
                """
                UPDATE confirmations
                SET state='decided', approved=?, decided=?
                WHERE id=? AND state='pending'
                """,
                (1 if approved else 0, stamp, confirm_id),
            )
            return cur.rowcount == 1

    def expire_confirmations(self, *, now: Optional[float] = None) -> int:
        self._ensure()
        stamp = now or time.time()
        with self._lock, self._connect() as db:
            cur = db.execute(
                """
                UPDATE confirmations SET state='expired', approved=0, decided=?
                WHERE state='pending' AND expires<=?
                """,
                (stamp, stamp),
            )
            return int(cur.rowcount)

    def list_confirmations(
        self, *, state: Optional[str] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        self._ensure()
        params: List[Any] = []
        query = "SELECT * FROM confirmations"
        if state:
            query += " WHERE state=?"
            params.append(state)
        query += " ORDER BY created DESC LIMIT ?"
        params.append(max(1, min(1000, int(limit))))
        with self._lock, self._connect() as db:
            rows = db.execute(query, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def schema_status(self) -> Dict[str, Any]:
        self._ensure()
        with self._lock, self._connect() as db:
            version = db.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()
            counts = {
                name: int(
                    db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                )
                for name in (
                    "jobs",
                    "steps",
                    "schedules",
                    "schedule_runs",
                    "computer_sessions",
                    "activity_spans",
                )
            }
        return {
            "ok": True,
            "path": str(self.path),
            "schema_version": int(version[0]) if version else 0,
            "counts": counts,
        }

    def create_schedule(self, schedule: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure()
        now = time.time()
        with self._lock, self._connect() as db:
            db.execute(
                """
                INSERT INTO schedules(
                    id, name, enabled, goal, trigger_kind, trigger_json,
                    timezone, resource_profile, permission_policy,
                    overlap_policy, budget_json, next_run_at, last_nominal_at,
                    revision, deleted_at, created, updated
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    schedule["id"],
                    schedule["name"],
                    1 if schedule.get("enabled", True) else 0,
                    schedule["goal"],
                    schedule["trigger_kind"],
                    _json(schedule["trigger"]),
                    schedule["timezone"],
                    schedule.get("resource_profile") or "balanced",
                    schedule.get("permission_policy") or "approval",
                    schedule.get("overlap_policy") or "coalesce",
                    _json(schedule.get("budget") or {}),
                    schedule.get("next_run_at"),
                    schedule.get("last_nominal_at"),
                    int(schedule.get("revision") or 1),
                    None,
                    float(schedule.get("created") or now),
                    float(schedule.get("updated") or now),
                ),
            )
        value = self.get_schedule(str(schedule["id"]))
        assert value is not None
        return value

    def get_schedule(
        self, schedule_id: str, *, include_deleted: bool = False
    ) -> Optional[Dict[str, Any]]:
        self._ensure()
        query = "SELECT * FROM schedules WHERE id=?"
        if not include_deleted:
            query += " AND deleted_at IS NULL"
        with self._lock, self._connect() as db:
            row = db.execute(query, (schedule_id,)).fetchone()
        return self._schedule_row(row) if row else None

    def list_schedules(self, *, include_deleted: bool = False) -> List[Dict[str, Any]]:
        self._ensure()
        query = "SELECT * FROM schedules"
        if not include_deleted:
            query += " WHERE deleted_at IS NULL"
        query += " ORDER BY created"
        with self._lock, self._connect() as db:
            rows = db.execute(query).fetchall()
        return [self._schedule_row(row) for row in rows]

    def update_schedule(
        self, schedule_id: str, changes: Dict[str, Any], *, bump_revision: bool = True
    ) -> Optional[Dict[str, Any]]:
        self._ensure()
        allowed = {
            "name",
            "enabled",
            "goal",
            "trigger_kind",
            "trigger",
            "timezone",
            "resource_profile",
            "permission_policy",
            "overlap_policy",
            "budget",
            "next_run_at",
            "last_nominal_at",
        }
        assignments: List[str] = []
        values: List[Any] = []
        for key, value in changes.items():
            if key not in allowed:
                continue
            column = {"trigger": "trigger_json", "budget": "budget_json"}.get(key, key)
            if key in {"trigger", "budget"}:
                value = _json(value)
            if key == "enabled":
                value = 1 if value else 0
            assignments.append(f"{column}=?")
            values.append(value)
        if not assignments:
            return self.get_schedule(schedule_id)
        assignments.append("updated=?")
        values.append(time.time())
        if bump_revision:
            assignments.append("revision=revision+1")
        values.append(schedule_id)
        with self._lock, self._connect() as db:
            cursor = db.execute(
                f"""
                UPDATE schedules SET {", ".join(assignments)}
                WHERE id=? AND deleted_at IS NULL
                """,
                tuple(values),
            )
            if bump_revision and cursor.rowcount:
                db.execute(
                    """
                    UPDATE schedule_runs SET state='cancelled', updated=?
                    WHERE schedule_id=? AND state='queued'
                      AND schedule_revision<>(
                        SELECT revision FROM schedules WHERE id=?
                      )
                    """,
                    (time.time(), schedule_id, schedule_id),
                )
        return self.get_schedule(schedule_id)

    def delete_schedule(self, schedule_id: str) -> bool:
        self._ensure()
        now = time.time()
        with self._lock, self._connect() as db:
            cur = db.execute(
                """
                UPDATE schedules
                SET enabled=0, next_run_at=NULL, deleted_at=?, revision=revision+1,
                    updated=?
                WHERE id=? AND deleted_at IS NULL
                """,
                (now, now, schedule_id),
            )
            db.execute(
                """
                UPDATE schedule_runs SET state='cancelled', updated=?
                WHERE schedule_id=? AND state='queued'
                """,
                (now, schedule_id),
            )
            return cur.rowcount == 1

    def due_schedules(self, now: float) -> List[Dict[str, Any]]:
        self._ensure()
        with self._lock, self._connect() as db:
            rows = db.execute(
                """
                SELECT * FROM schedules
                WHERE deleted_at IS NULL AND enabled=1
                  AND next_run_at IS NOT NULL AND next_run_at<=?
                ORDER BY next_run_at
                """,
                (now,),
            ).fetchall()
        return [self._schedule_row(row) for row in rows]

    def next_schedule_time(self) -> Optional[float]:
        self._ensure()
        with self._lock, self._connect() as db:
            row = db.execute(
                """
                SELECT MIN(next_run_at) FROM schedules
                WHERE deleted_at IS NULL AND enabled=1 AND next_run_at IS NOT NULL
                """
            ).fetchone()
        return float(row[0]) if row and row[0] is not None else None

    def create_schedule_run(self, run: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        self._ensure()
        now = time.time()
        with self._lock, self._connect() as db:
            try:
                db.execute(
                    """
                    INSERT INTO schedule_runs(
                        id, schedule_id, schedule_revision, nominal_at, nominal_key,
                        enqueued_at, job_id, state, attempt, retry_at,
                        coalesced_count, missed_from, missed_to, outcome_json,
                        created, updated
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        run["id"],
                        run["schedule_id"],
                        int(run["schedule_revision"]),
                        float(run["nominal_at"]),
                        str(run["nominal_key"]),
                        float(run.get("enqueued_at") or now),
                        run.get("job_id"),
                        str(run.get("state") or "queued"),
                        int(run.get("attempt") or 0),
                        run.get("retry_at"),
                        int(run.get("coalesced_count") or 1),
                        run.get("missed_from"),
                        run.get("missed_to"),
                        _json(run.get("outcome") or {}),
                        float(run.get("created") or now),
                        float(run.get("updated") or now),
                    ),
                )
            except sqlite3.IntegrityError:
                return None
        return self.get_schedule_run(str(run["id"]))

    def get_schedule_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        self._ensure()
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT * FROM schedule_runs WHERE id=?", (run_id,)
            ).fetchone()
        return self._schedule_run_row(row) if row else None

    def list_schedule_runs(
        self, schedule_id: Optional[str] = None, *, limit: int = 100
    ) -> List[Dict[str, Any]]:
        self._ensure()
        params: List[Any] = []
        query = "SELECT * FROM schedule_runs"
        if schedule_id is not None:
            query += " WHERE schedule_id=?"
            params.append(schedule_id)
        query += " ORDER BY created DESC LIMIT ?"
        params.append(max(1, min(1000, int(limit))))
        with self._lock, self._connect() as db:
            rows = db.execute(query, tuple(params)).fetchall()
        return [self._schedule_run_row(row) for row in rows]

    def queued_schedule_runs(
        self, *, limit: int = 100, now: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        self._ensure()
        stamp = now or time.time()
        with self._lock, self._connect() as db:
            rows = db.execute(
                """
                SELECT * FROM schedule_runs
                WHERE state='queued' AND (retry_at IS NULL OR retry_at<=?)
                ORDER BY enqueued_at LIMIT ?
                """,
                (stamp, max(1, min(1000, int(limit)))),
            ).fetchall()
        return [self._schedule_run_row(row) for row in rows]

    def active_schedule_run(self, schedule_id: str) -> Optional[Dict[str, Any]]:
        self._ensure()
        with self._lock, self._connect() as db:
            row = db.execute(
                """
                SELECT * FROM schedule_runs
                WHERE schedule_id=? AND state IN
                    ('queued','running','awaiting_confirm','verifying')
                ORDER BY created LIMIT 1
                """,
                (schedule_id,),
            ).fetchone()
        return self._schedule_run_row(row) if row else None

    def executing_schedule_run(self, schedule_id: str) -> Optional[Dict[str, Any]]:
        """Return the occurrence currently executing, excluding queued catch-up."""
        self._ensure()
        with self._lock, self._connect() as db:
            row = db.execute(
                """
                SELECT * FROM schedule_runs
                WHERE schedule_id=? AND state IN
                    ('running','awaiting_confirm','verifying')
                ORDER BY created LIMIT 1
                """,
                (schedule_id,),
            ).fetchone()
        return self._schedule_run_row(row) if row else None

    def pending_schedule_run(self, schedule_id: str) -> Optional[Dict[str, Any]]:
        """Return the queued occurrence that later runs coalesce into."""
        self._ensure()
        with self._lock, self._connect() as db:
            row = db.execute(
                """
                SELECT * FROM schedule_runs
                WHERE schedule_id=? AND state='queued'
                ORDER BY created LIMIT 1
                """,
                (schedule_id,),
            ).fetchone()
        return self._schedule_run_row(row) if row else None

    def update_schedule_run(
        self, run_id: str, **changes: Any
    ) -> Optional[Dict[str, Any]]:
        self._ensure()
        allowed = {
            "job_id",
            "state",
            "attempt",
            "retry_at",
            "coalesced_count",
            "missed_from",
            "missed_to",
            "outcome",
        }
        assignments: List[str] = []
        values: List[Any] = []
        for key, value in changes.items():
            if key not in allowed:
                continue
            column = "outcome_json" if key == "outcome" else key
            if key == "outcome":
                value = _json(value)
            assignments.append(f"{column}=?")
            values.append(value)
        if not assignments:
            return self.get_schedule_run(run_id)
        assignments.append("updated=?")
        values.extend((time.time(), run_id))
        with self._lock, self._connect() as db:
            db.execute(
                f"UPDATE schedule_runs SET {', '.join(assignments)} WHERE id=?",
                tuple(values),
            )
        return self.get_schedule_run(run_id)

    def schedule_run_for_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        self._ensure()
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT * FROM schedule_runs WHERE job_id=?", (job_id,)
            ).fetchone()
        return self._schedule_run_row(row) if row else None

    def create_computer_session(self, session: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure()
        now = time.time()
        with self._lock, self._connect() as db:
            # An expired observer is recoverable. A process that died while
            # acting is not: preserve it for explicit review.
            db.execute(
                """
                UPDATE computer_sessions
                SET state=CASE
                    WHEN effect_state='unknown' OR state IN ('acting','verifying')
                        THEN 'awaiting_review'
                    ELSE 'interrupted' END,
                    lease_owner=NULL, lease_expires=NULL, updated=?
                WHERE state IN ('active','acting','verifying')
                  AND lease_expires IS NOT NULL AND lease_expires<=?
                """,
                (now, now),
            )
            try:
                db.execute(
                    """
                    INSERT INTO computer_sessions(
                        id, job_id, step_id, state, app_json, window_json,
                        latest_observation_id, lease_owner, lease_expires,
                        deadline, effect_state, result_json, created, updated
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        session["id"],
                        session.get("job_id"),
                        session.get("step_id"),
                        str(session.get("state") or "active"),
                        _json(session.get("app") or {}),
                        _json(session.get("window") or {}),
                        session.get("latest_observation_id"),
                        session.get("lease_owner"),
                        session.get("lease_expires"),
                        session.get("deadline"),
                        str(session.get("effect_state") or "none"),
                        _json(session.get("result") or {}),
                        float(session.get("created") or now),
                        float(session.get("updated") or now),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise RuntimeError("another computer-use session owns the machine") from exc
        value = self.get_computer_session(str(session["id"]))
        assert value is not None
        return value

    def get_computer_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        self._ensure()
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT * FROM computer_sessions WHERE id=?", (session_id,)
            ).fetchone()
        return self._computer_session_row(row) if row else None

    def list_computer_sessions(self, *, limit: int = 50) -> List[Dict[str, Any]]:
        self._ensure()
        with self._lock, self._connect() as db:
            rows = db.execute(
                "SELECT * FROM computer_sessions ORDER BY created DESC LIMIT ?",
                (max(1, min(500, int(limit))),),
            ).fetchall()
        return [self._computer_session_row(row) for row in rows]

    def update_computer_session(
        self, session_id: str, **changes: Any
    ) -> Optional[Dict[str, Any]]:
        self._ensure()
        allowed = {
            "state",
            "app",
            "window",
            "latest_observation_id",
            "lease_owner",
            "lease_expires",
            "deadline",
            "effect_state",
            "result",
        }
        assignments: List[str] = []
        values: List[Any] = []
        for key, value in changes.items():
            if key not in allowed:
                continue
            column = {"app": "app_json", "window": "window_json", "result": "result_json"}.get(
                key, key
            )
            if key in {"app", "window", "result"}:
                value = _json(value)
            assignments.append(f"{column}=?")
            values.append(value)
        if not assignments:
            return self.get_computer_session(session_id)
        assignments.append("updated=?")
        values.extend((time.time(), session_id))
        with self._lock, self._connect() as db:
            db.execute(
                f"UPDATE computer_sessions SET {', '.join(assignments)} WHERE id=?",
                tuple(values),
            )
        return self.get_computer_session(session_id)

    def save_computer_observation(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure()
        with self._lock, self._connect() as db:
            db.execute(
                """
                INSERT INTO computer_observations(
                    id, session_id, fingerprint, app_json, window_json,
                    displays_json, accessibility_json, image_hash, width, height,
                    user_idle_sec, created
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    observation["id"],
                    observation["session_id"],
                    observation["fingerprint"],
                    _json(observation.get("app") or {}),
                    _json(observation.get("window") or {}),
                    _json(observation.get("displays") or []),
                    _json(observation.get("accessibility") or []),
                    str(observation.get("image_hash") or ""),
                    int(observation.get("width") or 0),
                    int(observation.get("height") or 0),
                    observation.get("user_idle_sec"),
                    float(observation.get("created") or time.time()),
                ),
            )
            db.execute(
                """
                UPDATE computer_sessions
                SET latest_observation_id=?, updated=? WHERE id=?
                """,
                (
                    observation["id"],
                    time.time(),
                    observation["session_id"],
                ),
            )
        value = self.get_computer_observation(str(observation["id"]))
        assert value is not None
        return value

    def get_computer_observation(
        self, observation_id: str
    ) -> Optional[Dict[str, Any]]:
        self._ensure()
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT * FROM computer_observations WHERE id=?",
                (observation_id,),
            ).fetchone()
        return self._computer_observation_row(row) if row else None

    @staticmethod
    def _schedule_row(row: sqlite3.Row) -> Dict[str, Any]:
        value = dict(row)
        value["enabled"] = bool(value["enabled"])
        value["trigger"] = _object(value.pop("trigger_json", "{}"), {})
        value["budget"] = _object(value.pop("budget_json", "{}"), {})
        return value

    @staticmethod
    def _schedule_run_row(row: sqlite3.Row) -> Dict[str, Any]:
        value = dict(row)
        value["outcome"] = _object(value.pop("outcome_json", "{}"), {})
        return value

    @staticmethod
    def _computer_session_row(row: sqlite3.Row) -> Dict[str, Any]:
        value = dict(row)
        value["app"] = _object(value.pop("app_json", "{}"), {})
        value["window"] = _object(value.pop("window_json", "{}"), {})
        value["result"] = _object(value.pop("result_json", "{}"), {})
        return value

    @staticmethod
    def _computer_observation_row(row: sqlite3.Row) -> Dict[str, Any]:
        value = dict(row)
        value["app"] = _object(value.pop("app_json", "{}"), {})
        value["window"] = _object(value.pop("window_json", "{}"), {})
        value["displays"] = _object(value.pop("displays_json", "[]"), [])
        value["accessibility"] = _object(
            value.pop("accessibility_json", "[]"), []
        )
        return value

    def mark_unfinished_interrupted(self, *, now: Optional[float] = None) -> int:
        """Make restart recovery explicit instead of leaving phantom workers."""
        self._ensure()
        stamp = now or time.time()
        marks = ",".join("?" for _ in ACTIVE_STATES)
        with self._lock, self._connect() as db:
            # A scheduled job killed before execution began is safe to enqueue
            # again against the same occurrence. Once it reached running, keep
            # an explicit interrupted outcome instead of guessing about effects.
            db.execute(
                """
                UPDATE schedule_runs
                SET state='queued', job_id=NULL, retry_at=?, updated=?,
                    outcome_json=?
                WHERE state IN ('running','verifying')
                  AND job_id IN (
                    SELECT id FROM jobs WHERE state IN ('queued','planning')
                  )
                """,
                (
                    stamp,
                    stamp,
                    _json({"reason": "restart before execution; safely requeued"}),
                ),
            )
            db.execute(
                """
                UPDATE schedule_runs
                SET state='interrupted', updated=?, outcome_json=?
                WHERE state IN ('running','awaiting_confirm','verifying')
                  AND job_id IN (
                    SELECT id FROM jobs
                    WHERE state IN ('running','verifying','awaiting_confirm')
                  )
                """,
                (
                    stamp,
                    _json(
                        {
                            "reason": (
                                "process restart after execution began; "
                                "not automatically replayed"
                            )
                        }
                    ),
                ),
            )
            cur = db.execute(
                f"""
                UPDATE jobs
                SET state='interrupted', progress='interrupted by restart',
                    terminal_reason='process_restart', lease_owner=NULL,
                    lease_expires=NULL, updated=?
                WHERE state IN ({marks})
                """,
                (stamp, *ACTIVE_STATES),
            )
            db.execute(
                """
                UPDATE steps
                SET state='interrupted',
                    effect_state=CASE
                      WHEN EXISTS (
                        SELECT 1 FROM idempotency
                        WHERE idempotency.key LIKE steps.job_id || ':%'
                          AND idempotency.state IN
                            ('in_progress','unknown_effect')
                      ) THEN 'unknown'
                      ELSE effect_state
                    END,
                    lease_owner=NULL, lease_expires=NULL,
                    terminal_reason='process_restart', updated=?
                WHERE state IN
                    ('queued','planning','running','verifying','awaiting_confirm')
                """,
                (stamp,),
            )
            # No worker remains to consume a pre-restart decision. Expiring
            # these gates makes the loss visible and, crucially, prevents a
            # stale click from authorizing a future action with the same UI.
            db.execute(
                """
                UPDATE confirmations
                SET state='expired', approved=0, decided=?
                WHERE state='pending'
                """,
                (stamp,),
            )
            db.execute(
                """
                UPDATE computer_sessions
                SET state='awaiting_review', effect_state=CASE
                    WHEN state IN ('acting', 'verifying') THEN 'unknown'
                    ELSE effect_state END,
                    lease_owner=NULL, lease_expires=NULL, updated=?
                WHERE state IN ('active', 'acting', 'verifying')
                """,
                (stamp,),
            )
            db.execute(
                """
                UPDATE activity_spans
                SET status='interrupted', revision=revision+1,
                    summary=CASE
                        WHEN summary='' THEN 'Interrupted by process restart'
                        ELSE summary END,
                    updated=?, ended=?
                WHERE status IN ('queued','running','awaiting_confirm')
                """,
                (stamp, stamp),
            )
            return int(cur.rowcount)

    @staticmethod
    def _job_row(row: sqlite3.Row) -> Dict[str, Any]:
        value = dict(row)
        value["plan"] = _object(value.pop("plan_json", "{}"), {})
        value["budget"] = _object(value.pop("budget_json", "{}"), {})
        return value

    @staticmethod
    def _activity_row(row: sqlite3.Row) -> Dict[str, Any]:
        value = dict(row)
        value["details"] = _object(value.pop("details_json", "{}"), {})
        return value

    @staticmethod
    def _step_row(row: sqlite3.Row) -> Dict[str, Any]:
        value = dict(row)
        for key in (
            "capabilities",
            "dependencies",
            "expected_output",
            "expected_evidence",
            "preconditions",
            "result",
            "evidence",
        ):
            default: Any = {} if key in {"result", "expected_output"} else []
            value[key] = _object(value.pop(f"{key}_json", ""), default)
        return value

    @staticmethod
    def arguments_digest(arguments: Any) -> str:
        return hashlib.sha256(_json(arguments).encode("utf-8")).hexdigest()


control_store = ControlStore()
