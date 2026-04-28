"""Not-contains evaluator."""

from __future__ import annotations

from mini_llm_eval.evaluators.base import BaseEvaluator
from mini_llm_eval.evaluators.registry import register
from mini_llm_eval.models.schemas import EvalResult


@register("not_contains")
class NotContainsEvaluator(BaseEvaluator):
    """Pass when none of the forbidden keywords appear in the output."""

    @property
    def name(self) -> str:
        return "not_contains"

    def evaluate(
        self,
        output: str,
        expected: str,
        case_metadata: dict | None = None,
        config: dict | None = None,
    ) -> EvalResult:
        case_sensitive = bool((config or {}).get("case_sensitive", False))
        keywords = [item.strip() for item in expected.split("|") if item.strip()]

        haystack = output if case_sensitive else output.lower()
        lookup = keywords if case_sensitive else [item.lower() for item in keywords]
        matched = [keyword for keyword, probe in zip(keywords, lookup) if probe in haystack]
        passed = len(matched) == 0
        reason = (
            f"No forbidden keywords matched from: {keywords}"
            if passed
            else f"Forbidden keywords matched: {matched}"
        )
        return EvalResult(
            passed=passed,
            reason=reason,
            evaluator_type=self.name,
            details={"keywords": keywords, "matched": matched},
        )
