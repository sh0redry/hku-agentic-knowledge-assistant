from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from agents.models import ActionDraft, AuditEvent, TaskEvent, TaskRecord, TaskStatus, utc_now


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(value: str | None) -> Any:
    return json.loads(value) if value else None


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


class SQLiteStore:
    """Small local task/audit store. A connection is opened per operation."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    capability TEXT NOT NULL,
                    status TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    result_json TEXT,
                    error_json TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    correlation_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL REFERENCES tasks(id),
                    event_type TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_task_events_task_sequence
                    ON task_events(task_id, sequence);
                CREATE TABLE IF NOT EXISTS action_drafts (
                    id TEXT PRIMARY KEY,
                    capability TEXT NOT NULL,
                    status TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    preview_json TEXT NOT NULL,
                    preview_digest TEXT NOT NULL,
                    confirmation_token_hash TEXT,
                    confirmation_expires_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT,
                    capability TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def create_task(self, record: TaskRecord) -> None:
        with self._connection() as db:
            db.execute(
                """INSERT INTO tasks
                (id, capability, status, phase, input_json, result_json, error_json,
                 cancel_requested, correlation_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.id,
                    record.capability,
                    record.status.value,
                    record.phase,
                    _json(record.input),
                    _json(record.result) if record.result is not None else None,
                    _json(record.error) if record.error is not None else None,
                    int(record.cancel_requested),
                    record.correlation_id,
                    record.created_at.isoformat(),
                    record.updated_at.isoformat(),
                ),
            )

    def update_task(
        self,
        task_id: str,
        *,
        status: TaskStatus | None = None,
        phase: str | None = None,
        result: dict | None = None,
        error: dict | None = None,
        cancel_requested: bool | None = None,
    ) -> TaskRecord:
        fields: list[str] = ["updated_at = ?"]
        values: list[Any] = [utc_now().isoformat()]
        for name, value in (("status", status.value if status else None), ("phase", phase)):
            if value is not None:
                fields.append(f"{name} = ?")
                values.append(value)
        if result is not None:
            fields.append("result_json = ?")
            values.append(_json(result))
        if error is not None:
            fields.append("error_json = ?")
            values.append(_json(error))
        if cancel_requested is not None:
            fields.append("cancel_requested = ?")
            values.append(int(cancel_requested))
        values.append(task_id)
        with self._connection() as db:
            cursor = db.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?", values)
            if cursor.rowcount != 1:
                raise KeyError(task_id)
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> TaskRecord:
        with self._connection() as db:
            row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        return self._task_from_row(row)

    def list_tasks(self, limit: int = 50) -> list[TaskRecord]:
        with self._connection() as db:
            rows = db.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._task_from_row(row) for row in rows]

    @staticmethod
    def _task_from_row(row: sqlite3.Row) -> TaskRecord:
        return TaskRecord(
            id=row["id"],
            capability=row["capability"],
            status=TaskStatus(row["status"]),
            phase=row["phase"],
            input=_loads(row["input_json"]) or {},
            result=_loads(row["result_json"]),
            error=_loads(row["error_json"]),
            cancel_requested=bool(row["cancel_requested"]),
            correlation_id=row["correlation_id"],
            created_at=_dt(row["created_at"]),
            updated_at=_dt(row["updated_at"]),
        )

    def add_task_event(self, task_id: str, event_type: str, data: dict) -> TaskEvent:
        created_at = utc_now()
        with self._connection() as db:
            cursor = db.execute(
                "INSERT INTO task_events (task_id, event_type, data_json, created_at) VALUES (?, ?, ?, ?)",
                (task_id, event_type, _json(data), created_at.isoformat()),
            )
            sequence = cursor.lastrowid
        return TaskEvent(
            sequence=sequence,
            task_id=task_id,
            event_type=event_type,
            data=data,
            created_at=created_at,
        )

    def list_task_events(self, task_id: str, after: int = 0) -> list[TaskEvent]:
        with self._connection() as db:
            rows = db.execute(
                "SELECT * FROM task_events WHERE task_id = ? AND sequence > ? ORDER BY sequence",
                (task_id, after),
            ).fetchall()
        return [
            TaskEvent(
                sequence=row["sequence"],
                task_id=row["task_id"],
                event_type=row["event_type"],
                data=_loads(row["data_json"]) or {},
                created_at=_dt(row["created_at"]),
            )
            for row in rows
        ]

    def save_draft(
        self,
        draft: ActionDraft,
        token_hash: str | None = None,
    ) -> None:
        with self._connection() as db:
            db.execute(
                """INSERT OR REPLACE INTO action_drafts
                (id, capability, status, input_json, preview_json, preview_digest,
                 confirmation_token_hash, confirmation_expires_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    draft.id,
                    draft.capability,
                    draft.status.value,
                    _json(draft.input),
                    _json(draft.preview),
                    draft.preview_digest,
                    token_hash,
                    draft.confirmation_expires_at.isoformat() if draft.confirmation_expires_at else None,
                    draft.created_at.isoformat(),
                    draft.updated_at.isoformat(),
                ),
            )

    def get_draft_with_token_hash(self, draft_id: str) -> tuple[ActionDraft, str | None]:
        with self._connection() as db:
            row = db.execute("SELECT * FROM action_drafts WHERE id = ?", (draft_id,)).fetchone()
        if row is None:
            raise KeyError(draft_id)
        draft = ActionDraft(
            id=row["id"],
            capability=row["capability"],
            status=TaskStatus(row["status"]),
            input=_loads(row["input_json"]) or {},
            preview=_loads(row["preview_json"]) or {},
            preview_digest=row["preview_digest"],
            confirmation_expires_at=_dt(row["confirmation_expires_at"])
            if row["confirmation_expires_at"]
            else None,
            created_at=_dt(row["created_at"]),
            updated_at=_dt(row["updated_at"]),
        )
        return draft, row["confirmation_token_hash"]

    def add_audit_event(
        self,
        capability: str,
        event_type: str,
        data: dict,
        task_id: str | None = None,
    ) -> AuditEvent:
        created_at = utc_now()
        with self._connection() as db:
            cursor = db.execute(
                "INSERT INTO audit_events (task_id, capability, event_type, data_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (task_id, capability, event_type, _json(data), created_at.isoformat()),
            )
            event_id = cursor.lastrowid
        return AuditEvent(
            id=event_id,
            task_id=task_id,
            capability=capability,
            event_type=event_type,
            data=data,
            created_at=created_at,
        )

    def list_audit_events(self, limit: int = 100) -> list[AuditEvent]:
        with self._connection() as db:
            rows = db.execute(
                "SELECT * FROM audit_events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            AuditEvent(
                id=row["id"],
                task_id=row["task_id"],
                capability=row["capability"],
                event_type=row["event_type"],
                data=_loads(row["data_json"]) or {},
                created_at=_dt(row["created_at"]),
            )
            for row in rows
        ]
