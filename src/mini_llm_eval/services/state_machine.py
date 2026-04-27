"""Run-state transition rules."""

from __future__ import annotations

from mini_llm_eval.core.exceptions import InvalidTransitionError
from mini_llm_eval.models.schemas import RunStatus

ALLOWED_RUN_TRANSITIONS: dict[str, set[str]] = {
    RunStatus.PENDING.value: {RunStatus.RUNNING.value, RunStatus.CANCELLED.value},
    RunStatus.RUNNING.value: {
        RunStatus.SUCCEEDED.value,
        RunStatus.FAILED.value,
        RunStatus.CANCELLED.value,
    },
    RunStatus.SUCCEEDED.value: set(),
    RunStatus.FAILED.value: set(),
    RunStatus.CANCELLED.value: set(),
}

TERMINAL_RUN_STATUSES = {
    RunStatus.SUCCEEDED.value,
    RunStatus.FAILED.value,
    RunStatus.CANCELLED.value,
}


def can_transition_run_status(from_status: str, to_status: str) -> bool:
    """Return whether a run status transition is allowed."""

    return to_status in ALLOWED_RUN_TRANSITIONS.get(from_status, set())


def validate_run_transition(run_id: str, from_status: str, to_status: str) -> None:
    """Raise when a run status transition is not allowed."""

    if not can_transition_run_status(from_status, to_status):
        raise InvalidTransitionError(
            f"Invalid run status transition for {run_id}: {from_status} -> {to_status}"
        )
