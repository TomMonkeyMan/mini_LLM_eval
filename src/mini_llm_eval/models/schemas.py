"""Shared Pydantic schemas and enums."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProviderStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CaseStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    ERROR = "error"


class TokenUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ProviderResponse(BaseModel):
    output: str
    latency_ms: float
    status: ProviderStatus
    error: str | None = None
    token_usage: TokenUsage | None = None
    cost: float | None = None
    model_name: str | None = None
    request_id: str | None = None


class EvalResult(BaseModel):
    passed: bool
    reason: str
    evaluator_type: str
    details: dict[str, Any] | None = None
    error: str | None = None


class EvalCase(BaseModel):
    case_id: str
    query: str
    expected_answer: str
    tags: list[str] = Field(default_factory=list)
    difficulty: str = "medium"
    eval_types: list[str] = Field(default_factory=lambda: ["contains"])
    metadata: dict[str, Any] = Field(default_factory=dict)


class CaseResult(BaseModel):
    run_id: str
    case_id: str
    query: str
    expected: str
    actual_output: str
    case_status: CaseStatus
    output_path: str | None = None
    eval_results: dict[str, EvalResult] = Field(default_factory=dict)
    latency_ms: float
    provider_status: ProviderStatus
    error_message: str | None = None
    retries: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RunConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    run_id: str
    dataset_path: str
    provider_name: str
    provider_model_config: dict[str, Any] = Field(
        default_factory=dict,
        alias="model_config",
        serialization_alias="model_config",
    )
    concurrency: int = 4
    timeout_ms: int = 30000
    max_retries: int = 3


class TagPassRate(BaseModel):
    total: int
    passed: int
    pass_rate: float


class RunSummary(BaseModel):
    total_cases: int
    passed_cases: int
    failed_cases: int
    error_cases: int
    pass_rate: float
    tag_pass_rates: dict[str, TagPassRate] = Field(default_factory=dict)
    avg_latency_ms: float
    p95_latency_ms: float
    error_count: int
    error_distribution: dict[str, int] = Field(default_factory=dict)


class RunResult(BaseModel):
    run_id: str
    dataset_path: str
    provider_name: str
    status: RunStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
    summary: RunSummary | None = None
