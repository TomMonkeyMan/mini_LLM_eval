"""Tests for shared schemas."""

from __future__ import annotations

from mini_llm_eval.models.schemas import (
    CaseResult,
    CaseStatus,
    EvalCase,
    EvalResult,
    ProviderResponse,
    ProviderStatus,
    RunConfig,
    RunStatus,
)


def test_eval_case_uses_independent_default_collections() -> None:
    first = EvalCase(case_id="1", query="q1", expected_answer="a1")
    second = EvalCase(case_id="2", query="q2", expected_answer="a2")

    first.tags.append("knowledge")
    first.metadata["locale"] = "zh-CN"
    first.eval_types.append("regex")

    assert second.tags == []
    assert second.metadata == {}
    assert second.eval_types == ["contains"]


def test_provider_response_serializes_enum_values() -> None:
    response = ProviderResponse(
        output="answer",
        latency_ms=12.5,
        status=ProviderStatus.SUCCESS,
    )

    payload = response.model_dump(mode="json")

    assert payload["status"] == "success"


def test_case_result_captures_status_and_eval_results() -> None:
    case_result = CaseResult(
        run_id="run-1",
        case_id="case-1",
        query="what",
        expected="that",
        actual_output="that",
        case_status=CaseStatus.COMPLETED,
        eval_results={
            "contains": EvalResult(
                passed=True,
                reason="matched",
                evaluator_type="contains",
            )
        },
        latency_ms=10.0,
        provider_status=ProviderStatus.SUCCESS,
    )

    assert case_result.case_status is CaseStatus.COMPLETED
    assert case_result.eval_results["contains"].passed is True


def test_run_config_and_status_enums_are_stable() -> None:
    config = RunConfig(
        run_id="run-1",
        dataset_path="data/eval_cases.jsonl",
        provider_name="mock-default",
    )

    assert config.max_retries == 3
    assert RunStatus.SUCCEEDED.value == "succeeded"
