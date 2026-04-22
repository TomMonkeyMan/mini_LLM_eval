"""Base evaluator interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from mini_llm_eval.models.schemas import EvalResult


class BaseEvaluator(ABC):
    """Base contract for all rule evaluators."""

    @abstractmethod
    def evaluate(
        self,
        output: str,
        expected: str,
        case_metadata: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
    ) -> EvalResult:
        """Evaluate a model output against the expected value."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable evaluator identifier."""
