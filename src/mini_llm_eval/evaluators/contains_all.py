"""Contains-all evaluator."""

from __future__ import annotations

from mini_llm_eval.evaluators.base import BaseEvaluator
from mini_llm_eval.evaluators.registry import register
from mini_llm_eval.models.schemas import EvalResult


@register("contains_all")
class ContainsAllEvaluator(BaseEvaluator):
    """Pass when all required keywords appear in the output."""

    @property
    def name(self) -> str:
        return "contains_all"

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
        missing = [keyword for keyword in keywords if keyword not in matched]
        passed = len(keywords) > 0 and len(missing) == 0
        reason = (
            f"All required keywords matched: {matched}"
            if passed
            else f"Missing required keywords: {missing}"
        )
        return EvalResult(
            passed=passed,
            reason=reason,
            evaluator_type=self.name,
            details={"keywords": keywords, "matched": matched, "missing": missing},
        )
