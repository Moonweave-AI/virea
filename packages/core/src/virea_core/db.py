from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from virea_contracts.job import JobRequest, JobState

from .ids import new_ulid
from .jobs import validate_job_transition
from .paths import VireaPaths

_SCHEMA_VERSION = 2
_SQLITE_BUSY_TIMEOUT_MS = 30_000
_SQLITE_RETRY_DEADLINE_SECONDS = 30.0

_MIGRATION_V1 = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS machine_reports (
    id TEXT PRIMARY KEY,
    recorded_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS registry_sources (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    locator TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS model_definitions (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_versions (
    id TEXT PRIMARY KEY,
    model_id TEXT NOT NULL REFERENCES model_definitions(id),
    plugin_version TEXT NOT NULL,
    upstream_revision TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE(model_id, plugin_version, upstream_revision)
);
CREATE TABLE IF NOT EXISTS model_aliases (
    model_id TEXT NOT NULL REFERENCES model_definitions(id),
    alias TEXT NOT NULL,
    model_version_id TEXT NOT NULL REFERENCES model_versions(id),
    PRIMARY KEY(model_id, alias)
);
CREATE TABLE IF NOT EXISTS artifact_manifests (
    id TEXT PRIMARY KEY,
    source_revision TEXT NOT NULL,
    locator TEXT NOT NULL,
    byte_length INTEGER,
    payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runtime_specs (
    id TEXT PRIMARY KEY,
    backend TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runtime_installations (
    id TEXT PRIMARY KEY,
    runtime_spec_id TEXT NOT NULL REFERENCES runtime_specs(id),
    state TEXT NOT NULL,
    locator TEXT,
    diagnostics_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS model_installations (
    id TEXT PRIMARY KEY,
    model_version_id TEXT NOT NULL REFERENCES model_versions(id),
    runtime_installation_id TEXT NOT NULL REFERENCES runtime_installations(id),
    artifact_manifest_id TEXT REFERENCES artifact_manifests(id),
    state TEXT NOT NULL,
    diagnostics_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(model_version_id, runtime_installation_id, artifact_manifest_id)
);
CREATE TABLE IF NOT EXISTS license_facts (
    id TEXT PRIMARY KEY,
    model_id TEXT,
    license_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS license_acceptances (
    id TEXT PRIMARY KEY,
    license_fact_id TEXT NOT NULL REFERENCES license_facts(id),
    accepted_at TEXT NOT NULL,
    scope TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS worker_instances (
    id TEXT PRIMARY KEY,
    model_installation_id TEXT,
    pid INTEGER,
    state TEXT NOT NULL,
    started_at TEXT NOT NULL,
    stopped_at TEXT,
    diagnostics_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS avatars (
    id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL,
    locator TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS avatar_calibrations (
    id TEXT PRIMARY KEY,
    avatar_id TEXT NOT NULL REFERENCES avatars(id),
    policy_id TEXT NOT NULL,
    locator TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    model_id TEXT NOT NULL,
    task TEXT NOT NULL,
    idempotency_key TEXT UNIQUE,
    request_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    error_code TEXT,
    error_message TEXT
);
CREATE TABLE IF NOT EXISTS job_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    sequence INTEGER NOT NULL,
    state TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(job_id, sequence)
);
CREATE TABLE IF NOT EXISTS results (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL UNIQUE REFERENCES jobs(id),
    schema_version TEXT NOT NULL,
    locator TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS result_artifacts (
    result_id TEXT NOT NULL REFERENCES results(id),
    name TEXT NOT NULL,
    media_type TEXT NOT NULL,
    locator TEXT NOT NULL,
    byte_length INTEGER,
    PRIMARY KEY(result_id, name)
);
CREATE TABLE IF NOT EXISTS transactions (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    state TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS locks (
    name TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    expires_at TEXT
);
CREATE TRIGGER IF NOT EXISTS job_events_no_update
BEFORE UPDATE ON job_events BEGIN SELECT RAISE(ABORT, 'job_events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS job_events_no_delete
BEFORE DELETE ON job_events BEGIN SELECT RAISE(ABORT, 'job_events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS results_no_update
BEFORE UPDATE ON results BEGIN SELECT RAISE(ABORT, 'results are immutable'); END;
CREATE TRIGGER IF NOT EXISTS results_no_delete
BEFORE DELETE ON results BEGIN SELECT RAISE(ABORT, 'results are immutable'); END;
CREATE TRIGGER IF NOT EXISTS result_artifacts_no_update
BEFORE UPDATE ON result_artifacts BEGIN SELECT RAISE(ABORT, 'result_artifacts are immutable'); END;
CREATE TRIGGER IF NOT EXISTS result_artifacts_no_delete
BEFORE DELETE ON result_artifacts BEGIN SELECT RAISE(ABORT, 'result_artifacts are immutable'); END;
"""

_MIGRATION_V2_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS transactions_integrity_policy_no_update
BEFORE UPDATE OF integrity_policy ON transactions
WHEN OLD.integrity_policy IS NOT NEW.integrity_policy
BEGIN SELECT RAISE(ABORT, 'transaction integrity policy is immutable'); END;
CREATE TRIGGER IF NOT EXISTS transactions_integrity_identity_no_update
BEFORE UPDATE OF id, kind ON transactions
WHEN OLD.integrity_policy IS NOT NULL
 AND (OLD.id IS NOT NEW.id OR OLD.kind IS NOT NEW.kind)
BEGIN SELECT RAISE(ABORT, 'transaction integrity policy is immutable'); END;
CREATE TRIGGER IF NOT EXISTS transactions_integrity_policy_no_delete
BEFORE DELETE ON transactions
WHEN OLD.integrity_policy IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'transaction integrity policy is immutable'); END;
CREATE TRIGGER IF NOT EXISTS transactions_integrity_policy_no_replace
BEFORE INSERT ON transactions
WHEN EXISTS (
    SELECT 1 FROM transactions
    WHERE id = NEW.id AND integrity_policy IS NOT NULL
)
BEGIN SELECT RAISE(ABORT, 'transaction integrity policy is immutable'); END;
CREATE TRIGGER IF NOT EXISTS results_no_replace
BEFORE INSERT ON results
WHEN EXISTS (SELECT 1 FROM results WHERE id = NEW.id OR job_id = NEW.job_id)
BEGIN SELECT RAISE(ABORT, 'results are immutable'); END;
CREATE TRIGGER IF NOT EXISTS result_artifacts_no_replace
BEFORE INSERT ON result_artifacts
WHEN EXISTS (
    SELECT 1 FROM result_artifacts
    WHERE result_id = NEW.result_id AND name = NEW.name
)
BEGIN SELECT RAISE(ABORT, 'result_artifacts are immutable'); END;
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sqlite_statements(script: str) -> tuple[str, ...]:
    """Split a trusted migration script without breaking trigger bodies."""

    statements: list[str] = []
    pending = ""
    for line in script.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            statement = pending.strip()
            if statement:
                statements.append(statement)
            pending = ""
    if pending.strip():
        raise ValueError("incomplete SQLite migration statement")
    return tuple(statements)


def _is_sqlite_lock_error(error: sqlite3.OperationalError) -> bool:
    code = getattr(error, "sqlite_errorcode", None)
    return code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED} or "locked" in str(
        error
    ).lower()


def _result_artifact_digest(path: Path) -> tuple[int, str]:
    """Hash one ordinary file while rejecting path or handle replacement."""

    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(f"result artifact is not an ordinary file: {path}")
    snapshot = (
        int(before.st_dev),
        int(before.st_ino),
        int(before.st_mode),
        int(before.st_size),
        int(before.st_mtime_ns),
    )
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    digest = hashlib.sha256()
    observed_bytes = 0
    with os.fdopen(descriptor, "rb") as handle:
        opened = os.fstat(handle.fileno())
        opened_snapshot = (
            int(opened.st_dev),
            int(opened.st_ino),
            int(opened.st_mode),
            int(opened.st_size),
            int(opened.st_mtime_ns),
        )
        if opened_snapshot != snapshot:
            raise OSError(f"result artifact changed while hashing: {path}")
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            observed_bytes += len(chunk)
        closed = os.fstat(handle.fileno())
        closed_snapshot = (
            int(closed.st_dev),
            int(closed.st_ino),
            int(closed.st_mode),
            int(closed.st_size),
            int(closed.st_mtime_ns),
        )
    after = path.lstat()
    after_snapshot = (
        int(after.st_dev),
        int(after.st_ino),
        int(after.st_mode),
        int(after.st_size),
        int(after.st_mtime_ns),
    )
    if (
        opened_snapshot != snapshot
        or closed_snapshot != snapshot
        or after_snapshot != snapshot
        or observed_bytes != snapshot[3]
    ):
        raise OSError(f"result artifact changed while hashing: {path}")
    return observed_bytes, digest.hexdigest()


class IdempotencyConflict(ValueError):
    """The same idempotency identity was reused for a different request."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(
            f"idempotency key {key!r} is already bound to a different JobRequest"
        )


class StateStore:
    def __init__(self, paths: VireaPaths | str | Path) -> None:
        self.paths = paths if isinstance(paths, VireaPaths) else VireaPaths(Path(paths))
        self.paths.ensure_layout()
        self.database = self.paths.database
        self.migrate()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        deadline = time.monotonic() + _SQLITE_RETRY_DEADLINE_SECONDS
        delay = 0.01
        connection: sqlite3.Connection | None = None
        while connection is None:
            candidate = sqlite3.connect(
                self.database,
                timeout=_SQLITE_BUSY_TIMEOUT_MS / 1000,
            )
            try:
                candidate.row_factory = sqlite3.Row
                candidate.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
                candidate.execute("PRAGMA foreign_keys=ON")
                current_mode = candidate.execute("PRAGMA journal_mode").fetchone()
                if current_mode is None or str(current_mode[0]).lower() != "wal":
                    candidate.execute("PRAGMA journal_mode=WAL")
                candidate.execute("PRAGMA synchronous=NORMAL")
            except sqlite3.OperationalError as exc:
                candidate.close()
                if not _is_sqlite_lock_error(exc) or time.monotonic() >= deadline:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 0.5)
            else:
                connection = candidate
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            yield connection

    def migrate(self) -> None:
        deadline = time.monotonic() + _SQLITE_RETRY_DEADLINE_SECONDS
        delay = 0.01
        while True:
            try:
                with self.connect() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    for statement in _sqlite_statements(_MIGRATION_V1):
                        connection.execute(statement)
                    connection.execute(
                        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) "
                        "VALUES (?, ?)",
                        (1, _now()),
                    )
                    transaction_columns = {
                        str(row["name"])
                        for row in connection.execute("PRAGMA table_info(transactions)")
                    }
                    if "integrity_policy" not in transaction_columns:
                        connection.execute(
                            "ALTER TABLE transactions ADD COLUMN integrity_policy TEXT"
                        )
                    result_artifact_columns = {
                        str(row["name"])
                        for row in connection.execute(
                            "PRAGMA table_info(result_artifacts)"
                        )
                    }
                    if "sha256" not in result_artifact_columns:
                        connection.execute(
                            "ALTER TABLE result_artifacts ADD COLUMN sha256 TEXT"
                        )
                    for statement in _sqlite_statements(_MIGRATION_V2_TRIGGERS):
                        connection.execute(statement)
                    connection.execute(
                        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) "
                        "VALUES (?, ?)",
                        (_SCHEMA_VERSION, _now()),
                    )
                return
            except sqlite3.OperationalError as exc:
                if not _is_sqlite_lock_error(exc) or time.monotonic() >= deadline:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 0.5)

    def journal_mode(self) -> str:
        with self.connect() as connection:
            row = connection.execute("PRAGMA journal_mode").fetchone()
            return str(row[0]).lower()

    def state_revision(self) -> dict[str, str]:
        """Return a cheap cross-process revision for browser reconciliation.

        CLI commands and the API can own separate ``StateStore`` instances that
        point at the same persistent home.  A browser therefore cannot rely on
        in-process events alone.  These aggregate clocks let the API notice
        committed SQLite changes without loading model artifacts or running
        machine detection on every heartbeat.
        """

        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    (SELECT printf('%d:%s', COUNT(*), COALESCE(MAX(updated_at), ''))
                     FROM jobs) AS jobs,
                    (SELECT printf('%d:%s', COUNT(*), COALESCE(MAX(created_at), ''))
                     FROM results) AS results,
                    (SELECT printf('%d:%s', COUNT(*), COALESCE(MAX(updated_at), ''))
                     FROM transactions) AS installations,
                    (SELECT printf('%d:%s', COUNT(*), COALESCE(MAX(updated_at), ''))
                     FROM model_definitions) AS models,
                    (SELECT printf(
                        '%d:%s:%s',
                        COUNT(*),
                        COALESCE(MAX(started_at), ''),
                        COALESCE(MAX(stopped_at), '')
                     ) FROM worker_instances) AS workers
                """
            ).fetchone()
            assert row is not None
            return {name: str(row[name]) for name in row.keys()}

    def try_acquire_locks(
        self,
        names: tuple[str, ...],
        *,
        owner_id: str,
        acquired_at: str | None = None,
    ) -> bool:
        """Atomically acquire every named non-expiring lock.

        Existing rows owned by ``owner_id`` are idempotent.  If any requested
        name belongs to another owner, the transaction inserts nothing.
        Long-running work must never hold the SQLite transaction itself; these
        rows are the durable lease boundary.
        """

        normalized = tuple(dict.fromkeys(names))
        if not normalized or len(normalized) != len(names):
            raise ValueError("lock names must be non-empty and unique")
        if any(not isinstance(name, str) or not name.strip() for name in normalized):
            raise ValueError("lock names must be non-empty strings")
        if not owner_id:
            raise ValueError("lock owner_id must not be empty")
        placeholders = ",".join("?" for _ in normalized)
        when = acquired_at or _now()
        with self.transaction() as connection:
            rows = connection.execute(
                f"SELECT name, owner_id FROM locks WHERE name IN ({placeholders})",
                normalized,
            ).fetchall()
            if any(str(row["owner_id"]) != owner_id for row in rows):
                return False
            existing = {str(row["name"]) for row in rows}
            connection.executemany(
                """
                INSERT INTO locks(name, owner_id, acquired_at, expires_at)
                VALUES (?, ?, ?, NULL)
                """,
                ((name, owner_id, when) for name in normalized if name not in existing),
            )
            return True

    def compare_and_swap_lock(
        self,
        name: str,
        *,
        expected_owner_id: str | None,
        owner_id: str,
        acquired_at: str | None = None,
    ) -> bool:
        """Acquire or replace one lock only if its observed owner is unchanged."""

        if not name:
            raise ValueError("lock name must not be empty")
        if not owner_id:
            raise ValueError("lock owner_id must not be empty")
        when = acquired_at or _now()
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT owner_id FROM locks WHERE name = ?", (name,)
            ).fetchone()
            current = str(row["owner_id"]) if row is not None else None
            if current != expected_owner_id:
                return False
            if row is None:
                connection.execute(
                    """
                    INSERT INTO locks(name, owner_id, acquired_at, expires_at)
                    VALUES (?, ?, ?, NULL)
                    """,
                    (name, owner_id, when),
                )
            else:
                connection.execute(
                    """
                    UPDATE locks
                    SET owner_id = ?, acquired_at = ?, expires_at = NULL
                    WHERE name = ? AND owner_id = ?
                    """,
                    (owner_id, when, name, expected_owner_id),
                )
            return True

    def release_locks(self, names: tuple[str, ...], *, owner_id: str) -> int:
        """Release only rows that still belong to the exact caller owner."""

        normalized = tuple(dict.fromkeys(names))
        if not normalized:
            return 0
        if len(normalized) != len(names):
            raise ValueError("lock names must be unique")
        if not owner_id:
            raise ValueError("lock owner_id must not be empty")
        placeholders = ",".join("?" for _ in normalized)
        with self.transaction() as connection:
            cursor = connection.execute(
                f"DELETE FROM locks WHERE owner_id = ? AND name IN ({placeholders})",
                (owner_id, *normalized),
            )
            return int(cursor.rowcount)

    def list_locks(self, *, prefix: str | None = None) -> list[dict[str, Any]]:
        """Return durable coordination rows without treating expiry as authority."""

        with self.connect() as connection:
            if prefix is None:
                rows = connection.execute(
                    "SELECT * FROM locks ORDER BY name"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM locks WHERE substr(name, 1, ?) = ? ORDER BY name",
                    (len(prefix), prefix),
                ).fetchall()
            return [dict(row) for row in rows]

    def create_job(
        self, request: JobRequest, job_id: str | None = None
    ) -> dict[str, Any]:
        row, _ = self.create_job_once(request, job_id=job_id)
        return row

    def create_job_once(
        self, request: JobRequest, job_id: str | None = None
    ) -> tuple[dict[str, Any], bool]:
        """Atomically create one Job for an idempotency key.

        The boolean is true only for the caller that inserted the row.  Returning
        this creation identity together with the row prevents a retry that sees
        an existing QUEUED Job from starting a second in-process runner.
        """

        identifier = job_id or new_ulid()
        now = _now()
        payload = request.model_dump(mode="json")
        request_json = _json(payload)
        with self.transaction() as connection:
            if request.idempotency_key:
                existing = connection.execute(
                    "SELECT * FROM jobs WHERE idempotency_key = ?",
                    (request.idempotency_key,),
                ).fetchone()
                if existing is not None:
                    if str(existing["request_json"]) != request_json:
                        raise IdempotencyConflict(request.idempotency_key)
                    return dict(existing), False
            connection.execute(
                """
                INSERT INTO jobs(
                    id, state, model_id, task, idempotency_key,
                    request_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identifier,
                    JobState.QUEUED.value,
                    request.model_id,
                    request.task,
                    request.idempotency_key,
                    request_json,
                    now,
                    now,
                ),
            )
            self._append_event(
                connection,
                identifier,
                JobState.QUEUED,
                "job.created",
                {"request": payload},
                now,
            )
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (identifier,)
            ).fetchone()
            assert row is not None
            return dict(row), True

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            return dict(row) if row is not None else None

    def transition_job(
        self,
        job_id: str,
        target: JobState | str,
        *,
        event_type: str = "job.state_changed",
        payload: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        next_state = JobState(target)
        now = _now()
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown job: {job_id}")
            validate_job_transition(row["state"], next_state)
            connection.execute(
                """
                UPDATE jobs
                SET state = ?, updated_at = ?, error_code = ?, error_message = ?
                WHERE id = ?
                """,
                (next_state.value, now, error_code, error_message, job_id),
            )
            self._append_event(
                connection,
                job_id,
                next_state,
                event_type,
                payload or {},
                now,
            )
            updated = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            assert updated is not None
            return dict(updated)

    def _append_event(
        self,
        connection: sqlite3.Connection,
        job_id: str,
        state: JobState,
        event_type: str,
        payload: dict[str, Any],
        created_at: str,
    ) -> None:
        row = connection.execute(
            "SELECT COALESCE(MAX(sequence), -1) + 1 FROM job_events WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        sequence = int(row[0])
        connection.execute(
            """
            INSERT INTO job_events(job_id, sequence, state, event_type, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (job_id, sequence, state.value, event_type, _json(payload), created_at),
        )

    def job_events(self, job_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM job_events WHERE job_id = ? ORDER BY sequence",
                (job_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_jobs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if limit < 1 or limit > 10_000:
            raise ValueError("limit must be in [1, 10000]")
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def active_jobs(self) -> list[dict[str, Any]]:
        terminal = (
            JobState.SUCCEEDED.value,
            JobState.CANCELLED.value,
            JobState.FAILED.value,
            JobState.TIMED_OUT.value,
            JobState.REJECTED.value,
        )
        placeholders = ",".join("?" for _ in terminal)
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM jobs WHERE state NOT IN ({placeholders}) ORDER BY created_at",
                terminal,
            ).fetchall()
            return [dict(row) for row in rows]

    def create_worker_instance(
        self,
        *,
        instance_id: str,
        pid: int,
        state: str,
        started_at: str,
        diagnostics: dict[str, Any],
        model_installation_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist a Worker immediately after the operating-system spawn.

        Process identity and launch-contract fields intentionally live in the
        versioned diagnostics document.  This keeps existing v1 databases
        readable while allowing recovery to add stronger identity evidence
        without a destructive table migration.
        """

        if pid <= 0:
            raise ValueError("worker pid must be positive")
        if not instance_id:
            raise ValueError("worker instance_id must not be empty")
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO worker_instances(
                    id, model_installation_id, pid, state, started_at,
                    stopped_at, diagnostics_json
                ) VALUES (?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    instance_id,
                    model_installation_id,
                    pid,
                    state,
                    started_at,
                    _json(diagnostics),
                ),
            )
            row = connection.execute(
                "SELECT * FROM worker_instances WHERE id = ?", (instance_id,)
            ).fetchone()
            assert row is not None
            return dict(row)

    def worker_instance(self, instance_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM worker_instances WHERE id = ?", (instance_id,)
            ).fetchone()
            return dict(row) if row is not None else None

    def worker_instances(
        self, *, states: tuple[str, ...] | None = None
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            if states is None:
                rows = connection.execute(
                    "SELECT * FROM worker_instances ORDER BY started_at, id"
                ).fetchall()
            elif not states:
                return []
            else:
                placeholders = ",".join("?" for _ in states)
                rows = connection.execute(
                    f"""
                    SELECT * FROM worker_instances
                    WHERE state IN ({placeholders})
                    ORDER BY started_at, id
                    """,
                    states,
                ).fetchall()
            return [dict(row) for row in rows]

    def update_worker_instance(
        self,
        instance_id: str,
        *,
        state: str | None = None,
        diagnostics: dict[str, Any] | None = None,
        stopped_at: str | None = None,
    ) -> dict[str, Any]:
        """Update lifecycle state while retaining prior diagnostic evidence."""

        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM worker_instances WHERE id = ?", (instance_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown worker instance: {instance_id}")
            try:
                document = json.loads(row["diagnostics_json"])
            except (TypeError, json.JSONDecodeError):
                document = {"previous_diagnostics_unreadable": True}
            if not isinstance(document, dict):
                document = {"previous_diagnostics_unreadable": True}
            if diagnostics:
                document.update(diagnostics)
            next_state = state if state is not None else str(row["state"])
            next_stopped_at = (
                stopped_at if stopped_at is not None else row["stopped_at"]
            )
            connection.execute(
                """
                UPDATE worker_instances
                SET state = ?, stopped_at = ?, diagnostics_json = ?
                WHERE id = ?
                """,
                (next_state, next_stopped_at, _json(document), instance_id),
            )
            updated = connection.execute(
                "SELECT * FROM worker_instances WHERE id = ?", (instance_id,)
            ).fetchone()
            assert updated is not None
            return dict(updated)

    def delete_worker_instance(self, instance_id: str) -> bool:
        """Delete an explicit terminal history row.

        Production lifecycle code never calls this automatically; it exists so
        administrative cleanup is deliberate and the persistence API is a full
        CRUD surface.
        """

        with self.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM worker_instances WHERE id = ?", (instance_id,)
            )
            return cursor.rowcount == 1

    def save_result(
        self,
        job_id: str,
        *,
        schema_version: str,
        locator: str,
        payload: dict[str, Any],
        result_id: str | None = None,
    ) -> dict[str, Any]:
        identifier = result_id or new_ulid()
        with self.transaction() as connection:
            job = connection.execute(
                "SELECT state FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if job is None:
                raise KeyError(f"unknown job: {job_id}")
            connection.execute(
                """
                INSERT INTO results(id, job_id, schema_version, locator, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (identifier, job_id, schema_version, locator, _json(payload), _now()),
            )
            row = connection.execute(
                "SELECT * FROM results WHERE id = ?", (identifier,)
            ).fetchone()
            assert row is not None
            return dict(row)

    def finalize_success(
        self,
        job_id: str,
        *,
        result_id: str,
        schema_version: str,
        locator: str,
        payload: dict[str, Any],
        artifacts: tuple[dict[str, Any], ...] = (),
    ) -> dict[str, Any]:
        """Atomically publish a result and move its job to ``SUCCEEDED``.

        Cancellation and finalization serialize on ``BEGIN IMMEDIATE``.  If
        cancellation commits first, transition validation fails before any
        result row is inserted.  If finalization commits first, callers see
        the terminal job, immutable result, artifact index, and success event
        together.
        """

        if not result_id:
            raise ValueError("result_id must not be empty")
        if payload.get("result_id") != result_id:
            raise ValueError("result payload result_id does not match")
        if payload.get("job_id") != job_id:
            raise ValueError("result payload job_id does not match")
        if payload.get("schema_version") != schema_version:
            raise ValueError("result payload schema_version does not match")
        normalized_artifacts = tuple(dict(item) for item in artifacts)
        names: set[str] = set()
        for artifact in normalized_artifacts:
            required = {"name", "media_type", "locator", "byte_length"}
            missing = required - artifact.keys()
            if missing:
                raise ValueError(
                    "result artifact is missing fields: " + ", ".join(sorted(missing))
                )
            name = artifact["name"]
            if not isinstance(name, str) or not name:
                raise ValueError("result artifact name must not be empty")
            if name in names:
                raise ValueError(f"duplicate result artifact name: {name}")
            names.add(name)
            for field in ("media_type", "locator"):
                value = artifact[field]
                if not isinstance(value, str) or not value:
                    raise ValueError(f"result artifact {field} must not be empty")
            byte_length = artifact["byte_length"]
            if byte_length is not None and (
                isinstance(byte_length, bool)
                or not isinstance(byte_length, int)
                or byte_length < 0
            ):
                raise ValueError(
                    "result artifact byte_length must be a non-negative integer"
                )

        with self.connect() as connection:
            job = connection.execute(
                "SELECT state FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if job is None:
            raise KeyError(f"unknown job: {job_id}")
        validate_job_transition(job["state"], JobState.SUCCEEDED)

        result_root = self.paths.result_directory(result_id).resolve(strict=True)
        for artifact in normalized_artifacts:
            artifact_path = self.paths.resolve_locator(artifact["locator"]).resolve(
                strict=True
            )
            try:
                artifact_path.relative_to(result_root)
            except ValueError as exc:
                raise ValueError(
                    f"result artifact is outside its result directory: {artifact['name']}"
                ) from exc
            observed_bytes, sha256 = _result_artifact_digest(artifact_path)
            if (
                artifact["byte_length"] is not None
                and artifact["byte_length"] != observed_bytes
            ):
                raise ValueError(
                    f"result artifact byte_length differs: {artifact['name']}"
                )
            artifact["byte_length"] = observed_bytes
            artifact["sha256"] = sha256

        now = _now()
        with self.transaction() as connection:
            job = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if job is None:
                raise KeyError(f"unknown job: {job_id}")
            validate_job_transition(job["state"], JobState.SUCCEEDED)
            connection.execute(
                """
                INSERT INTO results(
                    id, job_id, schema_version, locator, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    result_id,
                    job_id,
                    schema_version,
                    locator,
                    _json(payload),
                    now,
                ),
            )
            for artifact in normalized_artifacts:
                connection.execute(
                    """
                    INSERT INTO result_artifacts(
                        result_id, name, media_type, locator, byte_length, sha256
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result_id,
                        artifact["name"],
                        artifact["media_type"],
                        artifact["locator"],
                        artifact["byte_length"],
                        artifact["sha256"],
                    ),
                )
            connection.execute(
                """
                UPDATE jobs
                SET state = ?, updated_at = ?, error_code = NULL,
                    error_message = NULL
                WHERE id = ?
                """,
                (JobState.SUCCEEDED.value, now, job_id),
            )
            self._append_event(
                connection,
                job_id,
                JobState.SUCCEEDED,
                "job.succeeded",
                {"result_id": result_id},
                now,
            )
            result = connection.execute(
                "SELECT * FROM results WHERE id = ?", (result_id,)
            ).fetchone()
            updated_job = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            artifact_rows = connection.execute(
                """
                SELECT * FROM result_artifacts
                WHERE result_id = ? ORDER BY name
                """,
                (result_id,),
            ).fetchall()
            assert result is not None and updated_job is not None
            return {
                "job": dict(updated_job),
                "result": dict(result),
                "artifacts": [dict(row) for row in artifact_rows],
            }

    def get_result(self, result_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT results.* FROM results
                JOIN jobs ON jobs.id = results.job_id
                WHERE results.id = ? AND jobs.state = ?
                """,
                (result_id, JobState.SUCCEEDED.value),
            ).fetchone()
            return dict(row) if row is not None else None

    def result_for_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT results.* FROM results
                JOIN jobs ON jobs.id = results.job_id
                WHERE results.job_id = ? AND jobs.state = ?
                """,
                (job_id, JobState.SUCCEEDED.value),
            ).fetchone()
            return dict(row) if row is not None else None

    def result_artifacts(self, result_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM result_artifacts
                WHERE result_id = ? ORDER BY name
                """,
                (result_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def inconsistent_results(self) -> list[dict[str, Any]]:
        """Return immutable legacy rows whose jobs never reached success."""

        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT results.*, jobs.state AS job_state,
                       jobs.error_code AS job_error_code
                FROM results
                JOIN jobs ON jobs.id = results.job_id
                WHERE jobs.state <> ?
                ORDER BY results.created_at, results.id
                """,
                (JobState.SUCCEEDED.value,),
            ).fetchall()
            return [dict(row) for row in rows]

    def untracked_result_directories(self) -> list[str]:
        """Detect filesystem result directories with no immutable DB row."""

        with self.connect() as connection:
            referenced = {
                str(row["id"])
                for row in connection.execute("SELECT id FROM results").fetchall()
            }
        if not self.paths.results.is_dir():
            return []
        return [
            self.paths.relative_locator(path)
            for path in sorted(self.paths.results.iterdir(), key=lambda item: item.name)
            if path.is_dir() and path.name not in referenced
        ]

    def model_definitions(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM model_definitions ORDER BY id"
            ).fetchall()
            return [dict(row) for row in rows]

    def model_definition(self, model_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM model_definitions WHERE id = ?", (model_id,)
            ).fetchone()
            return dict(row) if row is not None else None

    def create_installation_transaction(
        self,
        *,
        installation_id: str,
        state: str,
        payload: dict[str, Any],
        integrity_policy: str | None = None,
    ) -> dict[str, Any]:
        if integrity_policy is not None and not integrity_policy.strip():
            raise ValueError("transaction integrity policy must not be empty")
        now = _now()
        document = {
            **payload,
            "events": [
                {
                    "sequence": 0,
                    "state": state,
                    "event_type": "installation.created",
                    "created_at": now,
                    "payload": {},
                }
            ],
        }
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO transactions(
                    id, kind, state, payload_json, created_at, updated_at, integrity_policy
                )
                VALUES (?, 'model_installation', ?, ?, ?, ?, ?)
                """,
                (
                    installation_id,
                    state,
                    _json(document),
                    now,
                    now,
                    integrity_policy,
                ),
            )
            row = connection.execute(
                "SELECT * FROM transactions WHERE id = ?", (installation_id,)
            ).fetchone()
            assert row is not None
            return dict(row)

    def transition_installation_transaction(
        self,
        installation_id: str,
        *,
        state: str,
        event_type: str = "installation.state_changed",
        payload: dict[str, Any] | None = None,
        fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = _now()
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM transactions WHERE id = ? AND kind = 'model_installation'",
                (installation_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown installation transaction: {installation_id}")
            document = json.loads(row["payload_json"])
            document.update(fields or {})
            events = list(document.get("events", []))
            events.append(
                {
                    "sequence": len(events),
                    "state": state,
                    "event_type": event_type,
                    "created_at": now,
                    "payload": payload or {},
                }
            )
            document["events"] = events
            connection.execute(
                """
                UPDATE transactions SET state = ?, payload_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (state, _json(document), now, installation_id),
            )
            updated = connection.execute(
                "SELECT * FROM transactions WHERE id = ?", (installation_id,)
            ).fetchone()
            assert updated is not None
            return dict(updated)

    def compare_and_swap_installation_transaction(
        self,
        installation_id: str,
        *,
        expected_state: str,
        state: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        fields: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Atomically transition only from the caller's exact observed state.

        A state mismatch returns ``None`` without changing state, payload fields,
        diagnostics, locator, or event history. ``BEGIN IMMEDIATE`` serializes
        this claim across threads and processes sharing the SQLite store.
        """

        if not expected_state or not state or not event_type:
            raise ValueError("installation CAS states and event type must be non-empty")
        now = _now()
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM transactions WHERE id = ? AND kind = 'model_installation'",
                (installation_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown installation transaction: {installation_id}")
            if str(row["state"]) != expected_state:
                return None
            document = json.loads(row["payload_json"])
            document.update(fields or {})
            events = list(document.get("events", []))
            events.append(
                {
                    "sequence": len(events),
                    "state": state,
                    "event_type": event_type,
                    "created_at": now,
                    "payload": payload or {},
                }
            )
            document["events"] = events
            cursor = connection.execute(
                """
                UPDATE transactions SET state = ?, payload_json = ?, updated_at = ?
                WHERE id = ? AND kind = 'model_installation' AND state = ?
                """,
                (
                    state,
                    _json(document),
                    now,
                    installation_id,
                    expected_state,
                ),
            )
            if cursor.rowcount != 1:
                return None
            updated = connection.execute(
                "SELECT * FROM transactions WHERE id = ?", (installation_id,)
            ).fetchone()
            assert updated is not None
            return dict(updated)

    def installation_transaction(self, installation_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM transactions WHERE id = ? AND kind = 'model_installation'",
                (installation_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def installation_transactions(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM transactions WHERE kind = 'model_installation'
                ORDER BY created_at
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def upsert_model_definition(self, payload: dict[str, Any]) -> None:
        required = ("id", "display_name", "status")
        missing = [name for name in required if name not in payload]
        if missing:
            raise ValueError(f"model definition missing fields: {missing}")
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO model_definitions(id, display_name, status, payload_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    display_name=excluded.display_name,
                    status=excluded.status,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (
                    payload["id"],
                    payload["display_name"],
                    payload["status"],
                    _json(payload),
                    _now(),
                ),
            )
