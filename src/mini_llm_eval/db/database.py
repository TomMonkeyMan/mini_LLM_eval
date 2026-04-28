"""SQLite persistence layer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aiosqlite

from mini_llm_eval.core.exceptions import PersistenceError
from mini_llm_eval.core.types import CaseResultRecord, RunRecord, StateLogRecord
from mini_llm_eval.models.schemas import CaseResult, RunConfig, RunStatus
from mini_llm_eval.services.state_machine import validate_run_transition

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    dataset_path TEXT NOT NULL,
    provider_name TEXT NOT NULL,
    model_config_json TEXT NOT NULL,
    status TEXT NOT NULL,
    summary_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    finished_at TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS case_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    status TEXT NOT NULL,
    output_path TEXT,
    eval_results_json TEXT NOT NULL,
    latency_ms REAL NOT NULL,
    error TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(run_id, case_id),
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS state_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    event TEXT NOT NULL,
    message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_case_results_run_id ON case_results(run_id);
CREATE INDEX IF NOT EXISTS idx_case_results_status ON case_results(status);
CREATE INDEX IF NOT EXISTS idx_state_logs_run_id ON state_logs(run_id);
"""

class Database:
    """Thin SQLite wrapper for run metadata and case result indexes."""

    def __init__(self, db_path: str = "eval.db") -> None:
        self.db_path = Path(db_path)

    async def init(self) -> None:
        """Initialize the database schema."""

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.executescript(SCHEMA)
                await db.commit()
        except aiosqlite.Error as exc:
            raise PersistenceError(f"Failed to initialize database {self.db_path}: {exc}") from exc

    async def create_run(self, run_config: RunConfig) -> str:
        """Create a new run in PENDING state."""

        payload = run_config.model_dump(mode="json", by_alias=True)
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    """
                    INSERT INTO runs (run_id, dataset_path, provider_name, model_config_json, status)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        run_config.run_id,
                        run_config.dataset_path,
                        run_config.provider_name,
                        json.dumps(payload["model_config"]),
                        RunStatus.PENDING.value,
                    ),
                )
                await db.execute(
                    """
                    INSERT INTO state_logs (run_id, from_status, to_status, event, message)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        run_config.run_id,
                        None,
                        RunStatus.PENDING.value,
                        "run_created",
                        "Run record created",
                    ),
                )
                await db.commit()
        except aiosqlite.Error as exc:
            raise PersistenceError(f"Failed to create run {run_config.run_id}: {exc}") from exc
        return run_config.run_id

    async def claim_pending_run(self) -> str | None:
        """Claim the oldest pending run and transition it to RUNNING."""

        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """
                    SELECT run_id FROM runs
                    WHERE status = ?
                    ORDER BY created_at ASC
                    LIMIT 1
                    """,
                    (RunStatus.PENDING.value,),
                )
                row = await cursor.fetchone()
                if row is None:
                    return None

                run_id = row["run_id"]
                await self._update_run_status_in_tx(
                    db,
                    run_id=run_id,
                    new_status=RunStatus.RUNNING.value,
                    event="run_claimed",
                    message="Run claimed for execution",
                    set_started=True,
                )
                await db.commit()
                return run_id
        except aiosqlite.Error as exc:
            raise PersistenceError(f"Failed to claim pending run: {exc}") from exc

    async def complete_run(
        self,
        run_id: str,
        success: bool,
        summary: dict[str, Any] | None = None,
    ) -> None:
        """Mark a running run as SUCCEEDED or FAILED."""

        status = RunStatus.SUCCEEDED.value if success else RunStatus.FAILED.value
        message = "Run finished successfully" if success else "Run finished with fatal failure"
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await self._update_run_status_in_tx(
                    db,
                    run_id=run_id,
                    new_status=status,
                    event="run_completed",
                    message=message,
                    summary=summary,
                    set_finished=True,
                )
                await db.commit()
        except aiosqlite.Error as exc:
            raise PersistenceError(f"Failed to complete run {run_id}: {exc}") from exc

    async def cancel_run(self, run_id: str, message: str = "Run cancelled") -> None:
        """Cancel a pending or running run."""

        try:
            async with aiosqlite.connect(self.db_path) as db:
                await self._update_run_status_in_tx(
                    db,
                    run_id=run_id,
                    new_status=RunStatus.CANCELLED.value,
                    event="run_cancelled",
                    message=message,
                    set_finished=True,
                )
                await db.commit()
        except aiosqlite.Error as exc:
            raise PersistenceError(f"Failed to cancel run {run_id}: {exc}") from exc

    async def update_run_status(
        self,
        run_id: str,
        status: str,
        event: str = "status_updated",
        message: str | None = None,
    ) -> None:
        """Update run status with transition validation."""

        set_started = status == RunStatus.RUNNING.value
        set_finished = status in {
            RunStatus.SUCCEEDED.value,
            RunStatus.FAILED.value,
            RunStatus.CANCELLED.value,
        }
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await self._update_run_status_in_tx(
                    db,
                    run_id=run_id,
                    new_status=status,
                    event=event,
                    message=message,
                    set_started=set_started,
                    set_finished=set_finished,
                )
                await db.commit()
        except aiosqlite.Error as exc:
            raise PersistenceError(f"Failed to update run status for {run_id}: {exc}") from exc

    async def save_case_result(self, result: CaseResult) -> None:
        """Insert or replace a case result."""

        payload = result.model_dump(mode="json")
        eval_results_json = json.dumps(payload["eval_results"], ensure_ascii=False)
        payload_json = json.dumps(payload, ensure_ascii=False)

        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    """
                    INSERT INTO case_results (
                        run_id, case_id, status, output_path, eval_results_json,
                        latency_ms, error, payload_json, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id, case_id) DO UPDATE SET
                        status = excluded.status,
                        output_path = excluded.output_path,
                        eval_results_json = excluded.eval_results_json,
                        latency_ms = excluded.latency_ms,
                        error = excluded.error,
                        payload_json = excluded.payload_json,
                        created_at = excluded.created_at
                    """,
                    (
                        result.run_id,
                        result.case_id,
                        result.case_status.value,
                        result.output_path,
                        eval_results_json,
                        result.latency_ms,
                        result.error_message,
                        payload_json,
                        result.created_at.isoformat(),
                    ),
                )
                await db.commit()
        except aiosqlite.Error as exc:
            raise PersistenceError(
                f"Failed to save case result {result.run_id}/{result.case_id}: {exc}"
            ) from exc

    async def get_completed_cases(self, run_id: str) -> set[str]:
        """Return all completed case ids for resume logic."""

        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(
                    """
                    SELECT case_id FROM case_results
                    WHERE run_id = ? AND status = ?
                    """,
                    (run_id, "completed"),
                )
                rows = await cursor.fetchall()
        except aiosqlite.Error as exc:
            raise PersistenceError(f"Failed to query completed cases for {run_id}: {exc}") from exc

        return {row[0] for row in rows}

    async def get_run(self, run_id: str) -> RunRecord | None:
        """Return a run record as a plain dict."""

        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
                row = await cursor.fetchone()
        except aiosqlite.Error as exc:
            raise PersistenceError(f"Failed to query run {run_id}: {exc}") from exc

        return RunRecord(**dict(row)) if row else None

    async def list_runs(self, limit: int = 10) -> list[RunRecord]:
        """Return recent runs ordered by last update."""

        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """
                    SELECT * FROM runs
                    ORDER BY updated_at DESC, created_at DESC, run_id DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
                rows = await cursor.fetchall()
        except aiosqlite.Error as exc:
            raise PersistenceError(f"Failed to list runs: {exc}") from exc

        return [RunRecord(**dict(row)) for row in rows]

    async def get_case_results(self, run_id: str) -> list[CaseResultRecord]:
        """Return stored case result records for a run."""

        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT * FROM case_results WHERE run_id = ? ORDER BY id ASC",
                    (run_id,),
                )
                rows = await cursor.fetchall()
        except aiosqlite.Error as exc:
            raise PersistenceError(f"Failed to query case results for {run_id}: {exc}") from exc

        return [CaseResultRecord(**dict(row)) for row in rows]

    async def get_state_logs(self, run_id: str) -> list[StateLogRecord]:
        """Return state transition logs for a run."""

        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT * FROM state_logs WHERE run_id = ? ORDER BY id ASC",
                    (run_id,),
                )
                rows = await cursor.fetchall()
        except aiosqlite.Error as exc:
            raise PersistenceError(f"Failed to query state logs for {run_id}: {exc}") from exc

        return [StateLogRecord(**dict(row)) for row in rows]

    async def _get_current_status(self, db: aiosqlite.Connection, run_id: str) -> str:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,))
        row = await cursor.fetchone()
        if row is None:
            raise PersistenceError(f"Run not found: {run_id}")
        return str(row["status"])

    async def _update_run_status_in_tx(
        self,
        db: aiosqlite.Connection,
        run_id: str,
        new_status: str,
        event: str,
        message: str | None = None,
        summary: dict[str, Any] | None = None,
        set_started: bool = False,
        set_finished: bool = False,
    ) -> None:
        current_status = await self._get_current_status(db, run_id)
        validate_run_transition(run_id, current_status, new_status)

        assignments = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
        params: list[Any] = [new_status]

        if summary is not None:
            assignments.append("summary_json = ?")
            params.append(json.dumps(summary, ensure_ascii=False))
        if set_started:
            assignments.append("started_at = CURRENT_TIMESTAMP")
        if set_finished:
            assignments.append("finished_at = CURRENT_TIMESTAMP")

        params.append(run_id)
        await db.execute(
            f"UPDATE runs SET {', '.join(assignments)} WHERE run_id = ?",
            params,
        )
        await db.execute(
            """
            INSERT INTO state_logs (run_id, from_status, to_status, event, message)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, current_status, new_status, event, message),
        )
