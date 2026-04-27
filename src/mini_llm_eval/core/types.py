"""Shared runtime record types."""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class RunRecord(TypedDict):
    """Row shape for persisted runs."""

    run_id: str
    dataset_path: str
    provider_name: str
    model_config_json: str
    status: str
    summary_json: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    updated_at: str


class CaseResultRecord(TypedDict):
    """Row shape for persisted case results."""

    id: int
    run_id: str
    case_id: str
    status: str
    output_path: str | None
    eval_results_json: str
    latency_ms: float
    error: str | None
    payload_json: str
    created_at: str


class StateLogRecord(TypedDict):
    """Row shape for persisted state transitions."""

    id: int
    run_id: str
    from_status: str | None
    to_status: str
    event: str
    message: str | None
    created_at: str


class EvalResultPayload(TypedDict):
    """Portable evaluator result payload stored in artifacts."""

    passed: bool
    reason: str
    evaluator_type: str
    details: NotRequired[dict[str, Any] | None]
    error: NotRequired[str | None]


class CaseResultArtifact(TypedDict):
    """Single JSONL row written to case_results.jsonl."""

    run_id: str
    case_id: str
    query: str
    expected: str
    actual_output: str
    case_status: str
    output_path: str | None
    eval_results: dict[str, EvalResultPayload]
    latency_ms: float
    provider_status: str
    error_message: str | None
    retries: int
    created_at: str


class TagPassRatePayload(TypedDict):
    """Portable tag-level pass-rate summary payload."""

    total: int
    passed: int
    pass_rate: float


class RunSummaryPayload(TypedDict):
    """Portable run summary payload stored in DB and meta.json."""

    total_cases: int
    passed_cases: int
    failed_cases: int
    error_cases: int
    pass_rate: float
    tag_pass_rates: dict[str, TagPassRatePayload]
    avg_latency_ms: float
    p95_latency_ms: float
    error_count: int
    error_distribution: dict[str, int]
    fatal_error: NotRequired[str]


class RunMeta(TypedDict):
    """Artifact metadata written for a completed run."""

    run_id: str
    dataset_path: str
    provider_name: str
    model_config: dict[str, Any]
    status: str
    summary: RunSummaryPayload | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    state_logs: list[StateLogRecord]
    case_result_count: int
