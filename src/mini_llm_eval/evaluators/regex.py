"""Regex evaluator."""

from __future__ import annotations

import re

from mini_llm_eval.core.exceptions import EvaluatorError
from mini_llm_eval.evaluators.base import BaseEvaluator
from mini_llm_eval.evaluators.registry import register
from mini_llm_eval.models.schemas import EvalResult


@register("regex")
class RegexEvaluator(BaseEvaluator):
    """Pass when a regex pattern matches the output."""

    @property
    def name(self) -> str:
        return "regex"

    def evaluate(
        self,
        output: str,
        expected: str,
        case_metadata: dict | None = None,
        config: dict | None = None,
    ) -> EvalResult:
        flags = 0 if (config or {}).get("case_sensitive") else re.IGNORECASE
        try:
            match = re.search(expected, output, flags=flags)
        except re.error as exc:
            raise EvaluatorError(f"Invalid regex pattern: {exc}") from exc

        passed = match is not None
        reason = (
            f"Pattern matched: {match.group(0)!r}"
            if passed
            else "Pattern did not match output"
        )
        return EvalResult(
            passed=passed,
            reason=reason,
            evaluator_type=self.name,
            details={"pattern": expected},
        )
