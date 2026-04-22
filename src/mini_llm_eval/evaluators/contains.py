"""Contains evaluator."""

from __future__ import annotations

from mini_llm_eval.evaluators.base import BaseEvaluator
from mini_llm_eval.evaluators.registry import register
from mini_llm_eval.models.schemas import EvalResult


@register("contains")
class ContainsEvaluator(BaseEvaluator):
    """Pass when at least one keyword is present in the output."""

    @property
    def name(self) -> str:
        return "contains"

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
        passed = len(matched) > 0
        reason = (
            f"Matched keywords: {matched}"
            if passed
            else f"No keyword matched from: {keywords}"
        )
        return EvalResult(
            passed=passed,
            reason=reason,
            evaluator_type=self.name,
            details={"keywords": keywords, "matched": matched},
        )
