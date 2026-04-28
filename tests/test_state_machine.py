"""Tests for run-state transitions."""

from __future__ import annotations

import pytest

from mini_llm_eval.core.exceptions import InvalidTransitionError
from mini_llm_eval.models.schemas import RunStatus
from mini_llm_eval.services.state_machine import (
    TERMINAL_RUN_STATUSES,
    can_transition_run_status,
    validate_run_transition,
)


def test_can_transition_run_status_allows_pending_to_running() -> None:
    assert can_transition_run_status(RunStatus.PENDING.value, RunStatus.RUNNING.value) is True


def test_can_transition_run_status_rejects_terminal_to_running() -> None:
    assert can_transition_run_status(RunStatus.SUCCEEDED.value, RunStatus.RUNNING.value) is False


def test_validate_run_transition_raises_for_invalid_transition() -> None:
    with pytest.raises(InvalidTransitionError, match="succeeded -> running"):
        validate_run_transition("run-1", RunStatus.SUCCEEDED.value, RunStatus.RUNNING.value)


def test_terminal_run_statuses_contains_cancelled() -> None:
    assert RunStatus.CANCELLED.value in TERMINAL_RUN_STATUSES
