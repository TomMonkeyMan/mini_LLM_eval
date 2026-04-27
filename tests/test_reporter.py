"""Tests for report rendering."""

from __future__ import annotations

from datetime import datetime, timezone

from mini_llm_eval.db.file_storage import FileStorage
from mini_llm_eval.models.schemas import (
    CaseResult,
    CaseStatus,
    CompareResult,
    CompareSummary,
    EvalResult,
    ProviderStatus,
    RunStatus,
    TagCompareResult,
)
from mini_llm_eval.services.reporter import Reporter


def _sample_case_result(run_id: str, case_id: str, *, passed: bool) -> CaseResult:
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
        latency_ms=10.0 if passed else 20.0,
        provider_status=ProviderStatus.SUCCESS,
        created_at=datetime.now(timezone.utc),
    )


def test_reporter_renders_run_markdown(tmp_path) -> None:
    storage = FileStorage(output_dir=str(tmp_path / "outputs"))
    reporter = Reporter(storage)
    result = _sample_case_result("run-1", "case-1", passed=False)
    storage.append_case_result("run-1", result)
    meta = {
        "run_id": "run-1",
        "dataset_path": "data/eval_cases.jsonl",
        "provider_name": "mock-default",
        "model_config": {},
        "status": "succeeded",
        "summary": {
            "total_cases": 1,
            "passed_cases": 0,
            "failed_cases": 1,
            "error_cases": 0,
            "pass_rate": 0.0,
            "tag_pass_rates": {"knowledge": {"total": 1, "passed": 0, "pass_rate": 0.0}},
            "avg_latency_ms": 20.0,
            "p95_latency_ms": 20.0,
            "error_count": 0,
            "error_distribution": {},
        },
        "created_at": "2026-04-27T00:00:00Z",
        "started_at": "2026-04-27T00:00:01Z",
        "finished_at": "2026-04-27T00:00:02Z",
        "state_logs": [],
        "case_result_count": 1,
    }
    storage.save_meta("run-1", meta)
    loaded_meta, loaded_cases = reporter.load_run_artifacts_from_run_id("run-1")

    markdown = reporter.render_run_report(loaded_meta, loaded_cases, format="markdown")

    assert "# Run Report: run-1" in markdown
    assert "## Summary" in markdown
    assert "Failed Or Errored Cases" in markdown
    assert "case-1" in markdown


def test_reporter_renders_compare_html(tmp_path) -> None:
    reporter = Reporter(FileStorage(output_dir=str(tmp_path / "outputs")))
    result = CompareResult(
        base_run_id="run-base",
        candidate_run_id="run-candidate",
        base_status=RunStatus.SUCCEEDED,
        candidate_status=RunStatus.SUCCEEDED,
        summary=CompareSummary(
            base_pass_rate=1.0,
            candidate_pass_rate=0.5,
            pass_rate_delta=-0.5,
            base_passed_cases=2,
            candidate_passed_cases=1,
            passed_delta=-1,
            base_failed_cases=0,
            candidate_failed_cases=1,
            failed_delta=1,
            base_error_cases=0,
            candidate_error_cases=0,
            error_delta=0,
            base_avg_latency_ms=10.0,
            candidate_avg_latency_ms=12.0,
            avg_latency_delta_ms=2.0,
            base_p95_latency_ms=10.0,
            candidate_p95_latency_ms=14.0,
            p95_latency_delta_ms=4.0,
            shared_case_count=2,
            newly_failed_case_ids=["case-1"],
            fixed_case_ids=[],
            newly_errored_case_ids=[],
            base_only_case_ids=[],
            candidate_only_case_ids=[],
        ),
        tag_results={
            "knowledge": TagCompareResult(
                tag="knowledge",
                base_total=2,
                candidate_total=2,
                base_pass_rate=1.0,
                candidate_pass_rate=0.5,
                pass_rate_delta=-0.5,
            )
        },
    )

    html = reporter.render_compare_report(result, format="html")

    assert "<!DOCTYPE html>" in html
    assert "Compare Report: run-base -&gt; run-candidate" in html
    assert "Tag Changes" in html
    assert "case-1" in html
