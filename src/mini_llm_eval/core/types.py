"""Shared runtime record types."""

from __future__ import annotations

from typing import Any, TypedDict


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


class RunMeta(TypedDict):
    """Artifact metadata written for a completed run."""

    run_id: str
    dataset_path: str
    provider_name: str
    model_config: dict[str, Any]
    status: str
    summary: dict[str, Any] | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    state_logs: list[StateLogRecord]
    case_result_count: int
