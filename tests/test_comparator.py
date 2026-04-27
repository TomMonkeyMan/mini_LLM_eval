"""Tests for artifact-based run comparison."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from mini_llm_eval.core.exceptions import ComparisonError
from mini_llm_eval.db.file_storage import FileStorage
from mini_llm_eval.models.schemas import CaseResult, CaseStatus, EvalResult, ProviderStatus
from mini_llm_eval.services.comparator import Comparator


def _write_run_artifacts(
    storage: FileStorage,
    run_id: str,
    case_results: list[CaseResult],
    *,
    pass_rate: float,
    passed_cases: int,
    failed_cases: int,
    error_cases: int,
    avg_latency_ms: float,
    p95_latency_ms: float,
    tag_pass_rates: dict,
) -> None:
    for result in case_results:
        storage.append_case_result(run_id, result)

    storage.save_meta(
        run_id,
        {
            "run_id": run_id,
            "dataset_path": "data/eval_cases.jsonl",
            "provider_name": "mock-default",
            "model_config": {},
            "status": "succeeded",
            "summary": {
                "total_cases": len(case_results),
                "passed_cases": passed_cases,
                "failed_cases": failed_cases,
                "error_cases": error_cases,
                "pass_rate": pass_rate,
                "tag_pass_rates": tag_pass_rates,
                "avg_latency_ms": avg_latency_ms,
                "p95_latency_ms": p95_latency_ms,
                "error_count": error_cases,
                "error_distribution": {},
            },
            "created_at": "2026-04-27T00:00:00Z",
            "started_at": "2026-04-27T00:00:01Z",
            "finished_at": "2026-04-27T00:00:02Z",
            "state_logs": [],
            "case_result_count": len(case_results),
        },
    )


def _build_case_result(
    run_id: str,
    case_id: str,
    *,
    passed: bool,
    latency_ms: float = 1.0,
) -> CaseResult:
    return CaseResult(
        run_id=run_id,
        case_id=case_id,
        query=f"query-{case_id}",
        expected="expected",
        actual_output="expected" if passed else "wrong",
        case_status=CaseStatus.COMPLETED,
        eval_results={
            "contains": EvalResult(
                passed=passed,
                reason="ok" if passed else "failed",
                evaluator_type="contains",
            )
        },
        latency_ms=latency_ms,
        provider_status=ProviderStatus.SUCCESS,
        created_at=datetime.now(timezone.utc),
    )


def test_comparator_reports_summary_and_case_deltas(tmp_path) -> None:
    storage = FileStorage(output_dir=str(tmp_path / "outputs"))
    comparator = Comparator(storage)

    _write_run_artifacts(
        storage,
        "run-base",
        [
            _build_case_result("run-base", "case-1", passed=True, latency_ms=10),
            _build_case_result("run-base", "case-2", passed=True, latency_ms=20),
        ],
        pass_rate=1.0,
        passed_cases=2,
        failed_cases=0,
        error_cases=0,
        avg_latency_ms=15.0,
        p95_latency_ms=20.0,
        tag_pass_rates={"knowledge": {"total": 2, "passed": 2, "pass_rate": 1.0}},
    )
    _write_run_artifacts(
        storage,
        "run-candidate",
        [
            _build_case_result("run-candidate", "case-1", passed=False, latency_ms=15),
            _build_case_result("run-candidate", "case-2", passed=True, latency_ms=25),
        ],
        pass_rate=0.5,
        passed_cases=1,
        failed_cases=1,
        error_cases=0,
        avg_latency_ms=20.0,
        p95_latency_ms=25.0,
        tag_pass_rates={"knowledge": {"total": 2, "passed": 1, "pass_rate": 0.5}},
    )

    result = comparator.compare_runs("run-base", "run-candidate")

    assert result.base_run_id == "run-base"
    assert result.candidate_run_id == "run-candidate"
    assert result.summary.pass_rate_delta == -0.5
    assert result.summary.newly_failed_case_ids == ["case-1"]
    assert result.summary.fixed_case_ids == []
    assert result.summary.shared_case_count == 2
    assert result.tag_results["knowledge"].pass_rate_delta == -0.5


def test_comparator_tracks_fixed_and_missing_cases(tmp_path) -> None:
    storage = FileStorage(output_dir=str(tmp_path / "outputs"))
    comparator = Comparator(storage)

    _write_run_artifacts(
        storage,
        "run-base",
        [
            _build_case_result("run-base", "case-1", passed=False),
            _build_case_result("run-base", "case-2", passed=True),
        ],
        pass_rate=0.5,
        passed_cases=1,
        failed_cases=1,
        error_cases=0,
        avg_latency_ms=1.0,
        p95_latency_ms=1.0,
        tag_pass_rates={"knowledge": {"total": 2, "passed": 1, "pass_rate": 0.5}},
    )
    _write_run_artifacts(
        storage,
        "run-candidate",
        [
            _build_case_result("run-candidate", "case-1", passed=True),
            _build_case_result("run-candidate", "case-3", passed=True),
        ],
        pass_rate=1.0,
        passed_cases=2,
        failed_cases=0,
        error_cases=0,
        avg_latency_ms=1.0,
        p95_latency_ms=1.0,
        tag_pass_rates={"knowledge": {"total": 2, "passed": 2, "pass_rate": 1.0}},
    )

    result = comparator.compare_runs("run-base", "run-candidate")

    assert result.summary.fixed_case_ids == ["case-1"]
    assert result.summary.base_only_case_ids == ["case-2"]
    assert result.summary.candidate_only_case_ids == ["case-3"]


def test_comparator_can_compare_explicit_run_directories(tmp_path) -> None:
    storage = FileStorage(output_dir=str(tmp_path / "outputs"))
    comparator = Comparator(storage)

    _write_run_artifacts(
        storage,
        "run-base",
        [_build_case_result("run-base", "case-1", passed=True)],
        pass_rate=1.0,
        passed_cases=1,
        failed_cases=0,
        error_cases=0,
        avg_latency_ms=1.0,
        p95_latency_ms=1.0,
        tag_pass_rates={"knowledge": {"total": 1, "passed": 1, "pass_rate": 1.0}},
    )
    _write_run_artifacts(
        storage,
        "run-candidate",
        [_build_case_result("run-candidate", "case-1", passed=False)],
        pass_rate=0.0,
        passed_cases=0,
        failed_cases=1,
        error_cases=0,
        avg_latency_ms=2.0,
        p95_latency_ms=2.0,
        tag_pass_rates={"knowledge": {"total": 1, "passed": 0, "pass_rate": 0.0}},
    )

    result = comparator.compare_run_dirs(
        tmp_path / "outputs" / "run-base",
        tmp_path / "outputs" / "run-candidate",
    )

    assert result.base_run_id == "run-base"
    assert result.candidate_run_id == "run-candidate"
    assert result.summary.newly_failed_case_ids == ["case-1"]


def test_comparator_raises_for_missing_summary(tmp_path) -> None:
    storage = FileStorage(output_dir=str(tmp_path / "outputs"))
    comparator = Comparator(storage)

    storage.save_meta(
        "run-base",
        {
            "run_id": "run-base",
            "dataset_path": "data/eval_cases.jsonl",
            "provider_name": "mock-default",
            "model_config": {},
            "status": "succeeded",
            "summary": None,
            "created_at": "2026-04-27T00:00:00Z",
            "started_at": "2026-04-27T00:00:01Z",
            "finished_at": "2026-04-27T00:00:02Z",
            "state_logs": [],
            "case_result_count": 0,
        },
    )
    storage.save_meta(
        "run-candidate",
        {
            "run_id": "run-candidate",
            "dataset_path": "data/eval_cases.jsonl",
            "provider_name": "mock-default",
            "model_config": {},
            "status": "succeeded",
            "summary": None,
            "created_at": "2026-04-27T00:00:00Z",
            "started_at": "2026-04-27T00:00:01Z",
            "finished_at": "2026-04-27T00:00:02Z",
            "state_logs": [],
            "case_result_count": 0,
        },
    )
    (tmp_path / "outputs" / "run-base" / "case_results.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "outputs" / "run-candidate" / "case_results.jsonl").write_text("", encoding="utf-8")

    with pytest.raises(ComparisonError, match="has no summary"):
        comparator.compare_runs("run-base", "run-candidate")
