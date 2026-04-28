"""Project-specific exception types."""

from __future__ import annotations


class EvalRunnerException(Exception):
    """Base exception for the project."""


class ConfigError(EvalRunnerException):
    """Raised when configuration loading or validation fails."""


class DatasetLoadError(EvalRunnerException):
    """Raised when dataset loading fails in a fatal way."""


class ProviderInitError(EvalRunnerException):
    """Raised when provider initialization fails before execution starts."""


class ProviderError(EvalRunnerException):
    """Raised when provider invocation fails."""

    def __init__(
        self,
        code: str,
        *,
        http_status: int | None = None,
        request_id: str | None = None,
        response_preview: str | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.http_status = http_status
        self.request_id = request_id
        self.response_preview = response_preview


class ProviderTimeoutError(ProviderError):
    """Raised when provider invocation times out."""


class EvaluatorError(EvalRunnerException):
    """Raised when evaluator execution fails."""


class ComparisonError(EvalRunnerException):
    """Raised when run artifact comparison fails."""


class ReportError(EvalRunnerException):
    """Raised when report rendering or export fails."""


class PersistenceError(EvalRunnerException):
    """Raised when database or artifact persistence fails."""


class InvalidTransitionError(EvalRunnerException):
    """Raised when a run state transition is not allowed."""
