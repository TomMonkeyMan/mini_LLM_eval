"""Project-specific exception types."""


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


class ProviderTimeoutError(ProviderError):
    """Raised when provider invocation times out."""


class EvaluatorError(EvalRunnerException):
    """Raised when evaluator execution fails."""


class PersistenceError(EvalRunnerException):
    """Raised when database or artifact persistence fails."""


class InvalidTransitionError(EvalRunnerException):
    """Raised when a run state transition is not allowed."""
