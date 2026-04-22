"""Exact-match evaluator."""

from __future__ import annotations

from mini_llm_eval.evaluators.base import BaseEvaluator
from mini_llm_eval.evaluators.registry import register
from mini_llm_eval.models.schemas import EvalResult


@register("exact_match")
class ExactMatchEvaluator(BaseEvaluator):
    """Pass only when output and expected are equal after trimming."""

    @property
    def name(self) -> str:
        return "exact_match"

    def evaluate(
        self,
        output: str,
        expected: str,
        case_metadata: dict | None = None,
        config: dict | None = None,
    ) -> EvalResult:
        normalized_output = output.strip()
        normalized_expected = expected.strip()
        passed = normalized_output == normalized_expected
        reason = "Exact match" if passed else "Output does not exactly match expected"
        return EvalResult(passed=passed, reason=reason, evaluator_type=self.name)
