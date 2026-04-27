"""Tests for SQLite persistence and file artifacts."""

from __future__ import annotations

import json

import aiosqlite
import pytest

from mini_llm_eval.core.exceptions import PersistenceError
from mini_llm_eval.db.database import Database
from mini_llm_eval.db.file_storage import FileStorage
from mini_llm_eval.models.schemas import (
    CaseResult,
    CaseStatus,
    EvalResult,
    RunConfig,
    RunStatus,
    ProviderStatus,
)


@pytest.mark.asyncio
async def test_database_create_claim_complete_and_logs(tmp_path) -> None:
    db = Database(str(tmp_path / "eval.db"))
    await db.init()

    run_config = RunConfig(
        run_id="run-1",
        dataset_path="data/eval_cases.jsonl",
        provider_name="mock-default",
    )
    await db.create_run(run_config)

    claimed = await db.claim_pending_run()
    assert claimed == "run-1"

    await db.complete_run("run-1", success=True, summary={"pass_rate": 1.0})
    run_record = await db.get_run("run-1")
    logs = await db.get_state_logs("run-1")

    assert run_record["status"] == RunStatus.SUCCEEDED.value
    assert json.loads(run_record["summary_json"])["pass_rate"] == 1.0
    assert [entry["to_status"] for entry in logs] == ["pending", "running", "succeeded"]


@pytest.mark.asyncio
async def test_database_saves_case_results_and_completed_cases(tmp_path) -> None:
    db = Database(str(tmp_path / "eval.db"))
    await db.init()
    await db.create_run(
        RunConfig(
            run_id="run-1",
            dataset_path="data/eval_cases.jsonl",
            provider_name="mock-default",
        )
    )

    result = CaseResult(
        run_id="run-1",
        case_id="case-1",
        query="hello",
        expected="world",
        actual_output="world",
        case_status=CaseStatus.COMPLETED,
        eval_results={
            "exact_match": EvalResult(
                passed=True,
                reason="ok",
                evaluator_type="exact_match",
            )
        },
        latency_ms=1.5,
        provider_status=ProviderStatus.SUCCESS,
    )
    await db.save_case_result(result)

    completed = await db.get_completed_cases("run-1")
    rows = await db.get_case_results("run-1")

    assert completed == {"case-1"}
    assert rows[0]["status"] == CaseStatus.COMPLETED.value
    assert json.loads(rows[0]["payload_json"])["actual_output"] == "world"


def test_file_storage_writes_case_results_and_meta(tmp_path) -> None:
    storage = FileStorage(output_dir=str(tmp_path / "outputs"))
    result = CaseResult(
        run_id="run-1",
        case_id="case-1",
        query="hello",
        expected="world",
        actual_output="world",
        case_status=CaseStatus.COMPLETED,
        eval_results={},
        latency_ms=1.0,
        provider_status=ProviderStatus.SUCCESS,
    )

    case_path = storage.append_case_result("run-1", result)
    meta_path = storage.save_meta(
        "run-1",
        {
            "run_id": "run-1",
            "dataset_path": "data/eval_cases.jsonl",
            "provider_name": "mock-default",
            "model_config": {},
            "status": "succeeded",
            "summary": None,
            "created_at": "2026-04-27T00:00:00Z",
            "started_at": "2026-04-27T00:00:01Z",
            "finished_at": "2026-04-27T00:00:02Z",
            "state_logs": [],
            "case_result_count": 1,
        },
    )

    case_rows = storage.read_json_lines(case_path)
    meta = storage.read_json(meta_path)

    assert case_rows[0]["case_id"] == "case-1"
    assert set(case_rows[0]) == {
        "run_id",
        "case_id",
        "query",
        "expected",
        "actual_output",
        "case_status",
        "output_path",
        "eval_results",
        "latency_ms",
        "provider_status",
        "error_message",
        "retries",
        "created_at",
    }
    assert meta["status"] == "succeeded"
    assert set(meta) == {
        "run_id",
        "dataset_path",
        "provider_name",
        "model_config",
        "status",
        "summary",
        "created_at",
        "started_at",
        "finished_at",
        "state_logs",
        "case_result_count",
    }


def test_file_storage_falls_back_when_output_dir_is_not_writable(tmp_path) -> None:
    blocking_path = tmp_path / "not-a-directory"
    blocking_path.write_text("occupied", encoding="utf-8")
    fallback_dir = tmp_path / "fallback"

    storage = FileStorage(output_dir=str(blocking_path), fallback_dir=str(fallback_dir))
    result = CaseResult(
        run_id="run-1",
        case_id="case-1",
        query="hello",
        expected="world",
        actual_output="world",
        case_status=CaseStatus.COMPLETED,
        eval_results={},
        latency_ms=1.0,
        provider_status=ProviderStatus.SUCCESS,
    )

    case_path = storage.append_case_result("run-1", result)
    meta_path = storage.save_meta("run-1", {"run_id": "run-1"})

    assert str(fallback_dir) in case_path
    assert str(fallback_dir) in meta_path


@pytest.mark.asyncio
async def test_database_save_case_result_wraps_sqlite_errors(tmp_path, monkeypatch) -> None:
    db = Database(str(tmp_path / "eval.db"))
    result = CaseResult(
        run_id="run-1",
        case_id="case-1",
        query="hello",
        expected="world",
        actual_output="world",
        case_status=CaseStatus.COMPLETED,
        eval_results={},
        latency_ms=1.0,
        provider_status=ProviderStatus.SUCCESS,
    )

    class BrokenConnection:
        async def __aenter__(self):
            raise aiosqlite.Error("boom")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(aiosqlite, "connect", lambda *args, **kwargs: BrokenConnection())

    with pytest.raises(PersistenceError, match="Failed to save case result run-1/case-1: boom"):
        await db.save_case_result(result)
