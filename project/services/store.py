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
                CREATE TABLE IF NOT EXISTS library_shadow_rules (
                    id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    encrypted_payload BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    next_run_at TEXT,
                    expires_at TEXT NOT NULL,
                    run_count INTEGER NOT NULL DEFAULT 0,
                    max_runs INTEGER NOT NULL,
                    version INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_library_shadow_rules_due
                    ON library_shadow_rules(state, next_run_at);
                CREATE TABLE IF NOT EXISTS library_shadow_runs (
                    id TEXT PRIMARY KEY,
                    rule_id TEXT NOT NULL REFERENCES library_shadow_rules(id),
                    occurrence_key TEXT NOT NULL,
                    scheduled_at TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    outcome TEXT NOT NULL,
                    candidate_count INTEGER NOT NULL DEFAULT 0,
                    encrypted_payload BLOB NOT NULL,
                    feedback_state TEXT NOT NULL DEFAULT 'pending',
                    choice_agreement INTEGER,
                    UNIQUE(rule_id, occurrence_key)
                );
                CREATE INDEX IF NOT EXISTS idx_library_shadow_runs_rule
                    ON library_shadow_runs(rule_id, scheduled_at);
                CREATE TABLE IF NOT EXISTS library_autobook_drafts (
                    id TEXT PRIMARY KEY,
                    state TEXT NOT NULL CHECK (state IN ('held_non_authorizing', 'revoked')),
                    encrypted_payload BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    version INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS library_autobook_authorizations (
                    id TEXT PRIMARY KEY,
                    state TEXT NOT NULL CHECK (state IN
                        ('pending_executor', 'paused', 'revoked', 'completed', 'outcome_unknown', 'expired')),
                    encrypted_payload BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    execution_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    success_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS library_autobook_attempts (
                    id TEXT PRIMARY KEY,
                    authorization_id TEXT NOT NULL REFERENCES library_autobook_authorizations(id),
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(authorization_id)
                );
                CREATE TABLE IF NOT EXISTS library_autobook_runtime (
                    authorization_id TEXT PRIMARY KEY REFERENCES library_autobook_authorizations(id),
                    armed INTEGER NOT NULL DEFAULT 0,
                    dry_run INTEGER NOT NULL DEFAULT 1,
                    phase TEXT NOT NULL DEFAULT 'not_armed',
                    date_check_count INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT,
                    updated_at TEXT NOT NULL
                );
                """
            )
            # Older local F4 development databases had no execution bound.
            # Leave those authorizations non-executable until explicitly replaced.
            columns = {row["name"] for row in db.execute("PRAGMA table_info(library_autobook_authorizations)")}
            if "execution_at" not in columns:
                db.execute("ALTER TABLE library_autobook_authorizations ADD COLUMN execution_at TEXT")
            runtime_columns = {row["name"] for row in db.execute("PRAGMA table_info(library_autobook_runtime)")}
            for column in ("started_at", "completed_at", "execution_result_json", "diagnostics_json"):
                if column not in runtime_columns:
                    db.execute(f"ALTER TABLE library_autobook_runtime ADD COLUMN {column} TEXT")

    def create_library_autobook_draft(self, record: dict) -> None:
        with self._connection() as db:
            db.execute(
                """INSERT INTO library_autobook_drafts
                (id, state, encrypted_payload, created_at, updated_at, expires_at, version)
                VALUES (?, 'held_non_authorizing', ?, ?, ?, ?, 1)""",
                (record["id"], record["encrypted_payload"], record["created_at"],
                 record["updated_at"], record["expires_at"]),
            )

    def list_library_autobook_drafts(self, limit: int = 100) -> list[dict]:
        with self._connection() as db:
            rows = db.execute(
                "SELECT * FROM library_autobook_drafts ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def revoke_library_autobook_draft(self, draft_id: str, updated_at: str) -> dict:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM library_autobook_drafts WHERE id = ?", (draft_id,)
            ).fetchone()
            if row is None:
                raise KeyError(draft_id)
            if row["state"] == "held_non_authorizing":
                db.execute(
                    "UPDATE library_autobook_drafts SET state = 'revoked', updated_at = ? WHERE id = ?",
                    (updated_at, draft_id),
                )
        result = dict(row)
        result["_changed"] = row["state"] == "held_non_authorizing"
        result["state"] = "revoked"
        result["updated_at"] = updated_at if row["state"] != "revoked" else row["updated_at"]
        return result

    def create_library_autobook_authorization(self, record: dict, *, max_pending: int = 5) -> None:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            count = db.execute(
                "SELECT COUNT(*) FROM library_autobook_authorizations WHERE state IN ('pending_executor', 'paused')"
            ).fetchone()[0]
            if count >= max_pending:
                raise ValueError(f"At most {max_pending} pending F4 authorizations are allowed.")
            db.execute(
                """INSERT INTO library_autobook_authorizations
                (id, state, encrypted_payload, created_at, updated_at, execution_at, expires_at, version)
                VALUES (?, 'pending_executor', ?, ?, ?, ?, ?, 1)""",
                (record["id"], record["encrypted_payload"], record["created_at"],
                 record["updated_at"], record["execution_at"], record["expires_at"]),
            )

    def list_library_autobook_authorizations(self, limit: int = 100) -> list[dict]:
        with self._connection() as db:
            rows = db.execute(
                "SELECT * FROM library_autobook_authorizations ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_autobook_authorization(self, authorization_id: str) -> dict:
        with self._connection() as db:
            row = db.execute("SELECT * FROM library_autobook_authorizations WHERE id = ?", (authorization_id,)).fetchone()
        if row is None:
            raise KeyError(authorization_id)
        return dict(row)

    def armed_autobook_authorizations(self) -> list[dict]:
        with self._connection() as db:
            rows = db.execute("""SELECT a.* FROM library_autobook_authorizations a
                JOIN library_autobook_runtime r ON r.authorization_id = a.id WHERE r.armed = 1""").fetchall()
        return [dict(row) for row in rows]

    def expire_library_autobook_authorizations(self, now: str) -> list[str]:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                """SELECT id FROM library_autobook_authorizations
                WHERE state IN ('pending_executor', 'paused') AND expires_at <= ?""",
                (now,),
            ).fetchall()
            if rows:
                db.execute(
                    """UPDATE library_autobook_authorizations
                    SET state = 'expired', updated_at = ?
                    WHERE state IN ('pending_executor', 'paused') AND expires_at <= ?""",
                    (now, now),
                )
                db.executemany("""UPDATE library_autobook_runtime SET armed = 0,
                    phase = CASE WHEN phase IN ('not_armed', 'armed', 'paused') THEN 'expired' ELSE phase END,
                    updated_at = ?
                    WHERE authorization_id = ?""", [(now, row["id"]) for row in rows])
        return [row["id"] for row in rows]

    def change_library_autobook_authorization_state(
        self, authorization_id: str, action: str, updated_at: str
    ) -> dict:
        transitions = {
            ("pending_executor", "pause"): "paused",
            ("pending_executor", "revoke"): "revoked",
            ("paused", "revoke"): "revoked",
        }
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM library_autobook_authorizations WHERE id = ?", (authorization_id,)
            ).fetchone()
            if row is None:
                raise KeyError(authorization_id)
            new_state = transitions.get((row["state"], action))
            if new_state is None:
                raise ValueError("This F4 authorization cannot make that state transition.")
            db.execute(
                "UPDATE library_autobook_authorizations SET state = ?, updated_at = ? WHERE id = ?",
                (new_state, updated_at, authorization_id),
            )
        result = dict(row)
        result.update(state=new_state, updated_at=updated_at)
        return result

    def claim_library_autobook_attempt(
        self, authorization_id: str, attempt_id: str, now: str, *, require_armed: bool = False
    ) -> bool:
        """Single-use claim for a future executor; claim means no automatic retry."""
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT state, execution_at, expires_at, attempt_count FROM library_autobook_authorizations WHERE id = ?",
                (authorization_id,),
            ).fetchone()
            if (row is None or row["state"] != "pending_executor"
                    or not row["execution_at"] or now < row["execution_at"] or row["expires_at"] <= now
                    or row["attempt_count"] != 0):
                return False
            if require_armed:
                runtime = db.execute("SELECT armed, phase FROM library_autobook_runtime WHERE authorization_id = ?",
                                     (authorization_id,)).fetchone()
                if runtime is None or not runtime["armed"] or runtime["phase"] not in {"preparing", "preparing_booking_form"}:
                    return False
            db.execute(
                """INSERT INTO library_autobook_attempts
                (id, authorization_id, state, created_at, updated_at)
                VALUES (?, ?, 'outcome_unknown', ?, ?)""",
                (attempt_id, authorization_id, now, now),
            )
            db.execute(
                """UPDATE library_autobook_authorizations
                SET state = 'outcome_unknown', attempt_count = 1, updated_at = ? WHERE id = ?""",
                (now, authorization_id),
            )
            return True

    def autobook_runtime(self, authorization_id: str) -> dict:
        with self._connection() as db:
            row = db.execute("SELECT * FROM library_autobook_runtime WHERE authorization_id = ?",
                             (authorization_id,)).fetchone()
        return dict(row) if row else {"armed": 0, "phase": "not_armed", "date_check_count": 0, "error_code": None}

    def arm_autobook(self, authorization_id: str, now: str, *, dry_run: bool = True) -> None:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT COUNT(*) FROM library_autobook_runtime WHERE armed = 1 AND authorization_id != ?",
                          (authorization_id,)).fetchone()[0]:
                raise ValueError("The F4 pilot permits only one armed authorization.")
            row = db.execute("SELECT * FROM library_autobook_authorizations WHERE id = ?", (authorization_id,)).fetchone()
            if row is None:
                raise KeyError(authorization_id)
            if row["state"] not in {"pending_executor", "paused"} or row["attempt_count"] or row["expires_at"] <= now:
                raise ValueError("Authorization is no longer armable.")
            runtime = db.execute("SELECT phase FROM library_autobook_runtime WHERE authorization_id = ?",
                                 (authorization_id,)).fetchone()
            if runtime and runtime["phase"] not in {"not_armed", "armed", "paused"}:
                raise ValueError("A started occurrence cannot be rearmed.")
            db.execute("UPDATE library_autobook_authorizations SET state = 'pending_executor', updated_at = ? WHERE id = ?",
                       (now, authorization_id))
            db.execute("""INSERT INTO library_autobook_runtime (authorization_id, armed, dry_run, phase, updated_at)
                VALUES (?, 1, ?, 'armed', ?) ON CONFLICT(authorization_id) DO UPDATE
                SET armed = 1, dry_run = excluded.dry_run, phase = 'armed', error_code = NULL, updated_at = excluded.updated_at""",
                (authorization_id, int(dry_run), now))

    def begin_autobook(self, authorization_id: str, now: str) -> bool:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute("""UPDATE library_autobook_runtime SET phase = 'preparing', updated_at = ?, started_at = ?
                WHERE authorization_id = ? AND armed = 1 AND phase = 'armed'
                AND EXISTS (SELECT 1 FROM library_autobook_authorizations a WHERE a.id = authorization_id
                            AND a.state = 'pending_executor' AND a.attempt_count = 0 AND a.expires_at > ?)""",
                (now, now, authorization_id, now))
            return cursor.rowcount == 1

    def record_autobook_diagnostic(self, authorization_id: str, now: str, stage: str, facts: dict) -> None:
        # Only caller-built booleans/counts/stable codes; never raw DOM/targets/secrets.
        with self._connection() as db:
            row = db.execute("SELECT diagnostics_json FROM library_autobook_runtime WHERE authorization_id = ?", (authorization_id,)).fetchone()
            if not row:
                return
            entries = json.loads(row[0] or "[]")
            entries.append({"stage": stage, "observed_at": now, **facts})
            db.execute("UPDATE library_autobook_runtime SET diagnostics_json = ? WHERE authorization_id = ?",
                       (_json(entries[-40:]), authorization_id))

    def finish_autobook(self, authorization_id: str, now: str, phase: str, error_code: str | None) -> None:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            result = {"phase": phase, "error_code": error_code, "completed_at": now, "source": "executor"}
            db.execute("""UPDATE library_autobook_runtime SET phase = ?, armed = 0, error_code = ?,
                completed_at = ?, execution_result_json = ?, updated_at = ? WHERE authorization_id = ?""",
                (phase, error_code, now, _json(result), now, authorization_id))

    def autobook_execution_details(self, authorization_id: str) -> dict:
        runtime = self.autobook_runtime(authorization_id)
        result = json.loads(runtime.get("execution_result_json") or "null")
        if result is None:
            # Recover old terminal results overwritten by expiry, without changing authority.
            with self._connection() as db:
                rows = db.execute("""SELECT event_type, data_json, created_at FROM audit_events
                    WHERE capability = 'library.autobook.attempt' AND json_extract(data_json, '$.authorization_id') = ?
                    ORDER BY id DESC LIMIT 1""", (authorization_id,)).fetchall()
            if rows and rows[0]["event_type"] in {"dry_run_ready_no_submission", "failed_before_submit", "outcome_unknown", "booking_record_verified"}:
                row = rows[0]
                result = {"phase": row["event_type"], "error_code": json.loads(row["data_json"]).get("error_code"),
                          "completed_at": row["created_at"], "source": "legacy_audit"}
        return {"execution_result": result, "started_at": runtime.get("started_at"),
                "completed_at": result.get("completed_at") if result else runtime.get("completed_at"),
                "diagnostics": json.loads(runtime.get("diagnostics_json") or "[]")}

    def update_autobook_runtime(self, authorization_id: str, now: str, *, phase: str | None = None,
                               armed: bool | None = None, checks: int | None = None, error_code: str | None = None) -> None:
        fields, values = ["updated_at = ?"], [now]
        for name, value in (("phase", phase), ("armed", int(armed) if armed is not None else None),
                            ("date_check_count", checks), ("error_code", error_code)):
            if value is not None:
                fields.append(name + " = ?")
                values.append(value)
        values.append(authorization_id)
        with self._connection() as db:
            db.execute("UPDATE library_autobook_runtime SET " + ", ".join(fields) + " WHERE authorization_id = ?", values)

    def recover_autobook_preparation(self, now: str) -> None:
        # No Submit was claimed for these occurrences, but do not replay them.
        with self._connection() as db:
            db.execute("""UPDATE library_autobook_runtime SET armed = 0,
                phase = CASE WHEN EXISTS (SELECT 1 FROM library_autobook_authorizations a
                    WHERE a.id = authorization_id AND a.attempt_count > 0) THEN 'outcome_unknown' ELSE 'interrupted' END,
                error_code = 'CORE_RESTARTED', updated_at = ? WHERE phase IN
                ('preparing', 'waiting_for_release', 'checking_date', 'checking_availability',
                 'checking_account_records', 'preparing_booking_form', 'outcome_unknown') AND armed = 1""", (now,))

    def confirm_library_autobook_attempt(
        self, authorization_id: str, attempt_id: str, now: str,
        *, record_match_count: int,
    ) -> bool:
        """Only exactly one authoritative record can resolve an attempt as success."""
        if record_match_count != 1:
            return False
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """SELECT a.state, a.success_count, t.id AS attempt_id
                FROM library_autobook_authorizations a
                JOIN library_autobook_attempts t ON t.authorization_id = a.id
                WHERE a.id = ?""",
                (authorization_id,),
            ).fetchone()
            if (row is None or row["state"] != "outcome_unknown"
                    or row["attempt_id"] != attempt_id or row["success_count"] != 0):
                return False
            db.execute(
                """UPDATE library_autobook_authorizations
                SET state = 'completed', success_count = 1, updated_at = ? WHERE id = ?""",
                (now, authorization_id),
            )
            db.execute(
                "UPDATE library_autobook_attempts SET state = 'confirmed', updated_at = ? WHERE id = ?",
                (now, attempt_id),
            )
            return True

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
        persisted_preview: dict | None = None,
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
                    _json(draft.preview if persisted_preview is None else persisted_preview),
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

    def create_library_shadow_rule(self, rule: dict, *, max_active: int = 5) -> None:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            active_count = db.execute(
                "SELECT COUNT(*) FROM library_shadow_rules WHERE state = 'active'"
            ).fetchone()[0]
            if active_count >= max_active:
                raise ValueError(f"At most {max_active} active F3 shadow rules are allowed.")
            db.execute(
                """INSERT INTO library_shadow_rules
                (id, state, encrypted_payload, created_at, updated_at, next_run_at,
                 expires_at, run_count, max_runs, version)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
                (
                    rule["id"], rule["state"], rule["encrypted_payload"],
                    rule["created_at"], rule["updated_at"], rule["next_run_at"],
                    rule["expires_at"], rule["max_runs"], rule["version"],
                ),
            )

    def get_library_shadow_rule(self, rule_id: str) -> dict:
        with self._connection() as db:
            row = db.execute(
                "SELECT * FROM library_shadow_rules WHERE id = ?", (rule_id,)
            ).fetchone()
        if row is None:
            raise KeyError(rule_id)
        return dict(row)

    def list_library_shadow_rules(self, limit: int = 100) -> list[dict]:
        with self._connection() as db:
            rows = db.execute(
                "SELECT * FROM library_shadow_rules ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_due_library_shadow_rules(self, now: str, limit: int = 20) -> list[dict]:
        with self._connection() as db:
            rows = db.execute(
                """SELECT * FROM library_shadow_rules
                WHERE state = 'active' AND next_run_at IS NOT NULL
                  AND next_run_at <= ? AND expires_at > ? AND run_count < max_runs
                ORDER BY next_run_at LIMIT ?""",
                (now, now, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_active_library_shadow_rules(self) -> list[dict]:
        with self._connection() as db:
            rows = db.execute(
                "SELECT * FROM library_shadow_rules WHERE state = 'active' "
                "ORDER BY next_run_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def claim_library_shadow_occurrence(
        self,
        *,
        rule_id: str,
        run_id: str,
        occurrence_key: str,
        scheduled_at: str,
        next_run_at: str | None,
        started_at: str,
        encrypted_payload: bytes,
    ) -> bool:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            rule = db.execute(
                "SELECT state, next_run_at, expires_at, run_count, max_runs "
                "FROM library_shadow_rules WHERE id = ?", (rule_id,),
            ).fetchone()
            if (rule is None or rule["state"] != "active"
                    or rule["next_run_at"] is None or rule["next_run_at"] > started_at
                    or rule["expires_at"] <= started_at or rule["run_count"] >= rule["max_runs"]):
                return False
            existing = db.execute(
                "SELECT 1 FROM library_shadow_runs WHERE rule_id = ? AND occurrence_key = ?",
                (rule_id, occurrence_key),
            ).fetchone()
            if existing is not None:
                return False
            db.execute(
                """INSERT INTO library_shadow_runs
                (id, rule_id, occurrence_key, scheduled_at, started_at, outcome,
                 encrypted_payload)
                VALUES (?, ?, ?, ?, ?, 'running', ?)""",
                (run_id, rule_id, occurrence_key, scheduled_at, started_at, encrypted_payload),
            )
            db.execute(
                """UPDATE library_shadow_rules
                SET run_count = run_count + 1, next_run_at = ?, updated_at = ?
                WHERE id = ?""",
                (next_run_at, started_at, rule_id),
            )
            return True

    def update_library_shadow_progress(self, run_id: str, encrypted_payload: bytes) -> None:
        with self._connection() as db:
            db.execute(
                "UPDATE library_shadow_runs SET encrypted_payload = ? WHERE id = ? AND outcome = 'running'",
                (encrypted_payload, run_id),
            )

    def complete_library_shadow_run(
        self, run_id: str, *, outcome: str, candidate_count: int,
        encrypted_payload: bytes, completed_at: str,
    ) -> dict:
        with self._connection() as db:
            cursor = db.execute(
                """UPDATE library_shadow_runs
                SET outcome = ?, candidate_count = ?, encrypted_payload = ?, completed_at = ?
                WHERE id = ?""",
                (outcome, candidate_count, encrypted_payload, completed_at, run_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(run_id)
            row = db.execute(
                "SELECT * FROM library_shadow_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return dict(row)

    def fail_running_library_shadow_runs_for_rule(
        self, rule_id: str, completed_at: str,
    ) -> list[str]:
        with self._connection() as db:
            rows = db.execute(
                "SELECT id FROM library_shadow_runs "
                "WHERE rule_id = ? AND outcome = 'running'", (rule_id,),
            ).fetchall()
            identifiers = [row["id"] for row in rows]
            db.execute(
                "UPDATE library_shadow_runs SET outcome = 'internal_error', "
                "completed_at = ?, feedback_state = 'not_comparable' "
                "WHERE rule_id = ? AND outcome = 'running'",
                (completed_at, rule_id),
            )
        return identifiers

    def list_library_shadow_runs(self, rule_id: str | None = None, limit: int = 100) -> list[dict]:
        with self._connection() as db:
            if rule_id:
                rows = db.execute(
                    """SELECT * FROM library_shadow_runs WHERE rule_id = ?
                    ORDER BY scheduled_at DESC LIMIT ?""", (rule_id, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM library_shadow_runs ORDER BY scheduled_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    def get_library_shadow_run(self, run_id: str) -> dict:
        with self._connection() as db:
            row = db.execute(
                "SELECT * FROM library_shadow_runs WHERE id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return dict(row)

    def update_library_shadow_run_feedback(
        self, run_id: str, *, encrypted_payload: bytes,
        feedback_state: str, choice_agreement: bool,
    ) -> dict:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT feedback_state FROM library_shadow_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            if row["feedback_state"] != "pending":
                raise ValueError("Feedback for this shadow run has already been recorded.")
            db.execute(
                """UPDATE library_shadow_runs
                SET encrypted_payload = ?, feedback_state = ?, choice_agreement = ?
                WHERE id = ?""",
                (encrypted_payload, feedback_state, int(choice_agreement), run_id),
            )
            updated = db.execute(
                "SELECT * FROM library_shadow_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return dict(updated)

    def set_library_shadow_rule_state(
        self, rule_id: str, state: str, updated_at: str,
        encrypted_payload: bytes | None = None,
        next_run_at: str | None = None,
    ) -> dict:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT state, encrypted_payload FROM library_shadow_rules WHERE id = ?",
                (rule_id,),
            ).fetchone()
            if row is None:
                raise KeyError(rule_id)
            if row["state"] in {"revoked", "expired", "policy_changed", "completed"}:
                raise ValueError(f"A {row['state']} shadow rule cannot be reactivated.")
            if row["state"] == "migration_required" and state not in {"migration_required", "revoked"}:
                raise ValueError("A migrated shadow rule cannot be resumed; review and create a new rule.")
            db.execute(
                """UPDATE library_shadow_rules SET state = ?, updated_at = ?,
                encrypted_payload = COALESCE(?, encrypted_payload), next_run_at = ?
                WHERE id = ?""",
                (state, updated_at, encrypted_payload, next_run_at, rule_id),
            )
            updated = db.execute(
                "SELECT * FROM library_shadow_rules WHERE id = ?", (rule_id,)
            ).fetchone()
        return dict(updated)

    def expire_library_shadow_rules(self, now: str) -> list[str]:
        with self._connection() as db:
            rows = db.execute(
                "SELECT id FROM library_shadow_rules WHERE state = 'active' AND expires_at <= ?",
                (now,),
            ).fetchall()
            identifiers = [row["id"] for row in rows]
            db.execute(
                """UPDATE library_shadow_rules SET state = 'expired', updated_at = ?
                WHERE state = 'active' AND expires_at <= ?""", (now, now),
            )
        return identifiers

    def mark_interrupted_library_shadow_runs(self, completed_at: str) -> list[dict]:
        with self._connection() as db:
            rows = db.execute(
                "SELECT * FROM library_shadow_runs WHERE outcome = 'running'"
            ).fetchall()
            db.execute(
                """UPDATE library_shadow_runs SET outcome = 'interrupted_after_restart',
                completed_at = ?, feedback_state = 'not_comparable'
                WHERE outcome = 'running'""", (completed_at,),
            )
        return [dict(row) for row in rows]

    def complete_exhausted_library_shadow_rules(self, updated_at: str) -> list[str]:
        with self._connection() as db:
            rows = db.execute(
                "SELECT id FROM library_shadow_rules "
                "WHERE state = 'active' AND run_count >= max_runs"
            ).fetchall()
            identifiers = [row["id"] for row in rows]
            db.execute(
                "UPDATE library_shadow_rules SET state = 'completed', updated_at = ?, "
                "next_run_at = NULL WHERE state = 'active' AND run_count >= max_runs",
                (updated_at,),
            )
        return identifiers
