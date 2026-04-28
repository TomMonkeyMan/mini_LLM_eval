"""Numeric tolerance evaluator."""

from __future__ import annotations

from mini_llm_eval.core.exceptions import EvaluatorError
from mini_llm_eval.evaluators.base import BaseEvaluator
from mini_llm_eval.evaluators.registry import register
from mini_llm_eval.models.schemas import EvalResult


@register("numeric_tolerance")
class NumericToleranceEvaluator(BaseEvaluator):
    """Compare numbers with an absolute or percentage tolerance."""

    @property
    def name(self) -> str:
        return "numeric_tolerance"

    def evaluate(
        self,
        output: str,
        expected: str,
        case_metadata: dict | None = None,
        config: dict | None = None,
    ) -> EvalResult:
        config = config or {}
        try:
            actual = float(output.strip())
            expected_value = float(expected.strip())
        except ValueError as exc:
            raise EvaluatorError("numeric_tolerance evaluator requires numeric output and expected values") from exc

        if "absolute_tolerance" in config:
            tolerance = float(config["absolute_tolerance"])
        else:
            percentage = float(config.get("percentage", 0.05))
            tolerance = abs(expected_value) * percentage

        difference = abs(actual - expected_value)
        passed = difference <= tolerance
        reason = (
            f"Difference {difference} within tolerance {tolerance}"
            if passed
            else f"Difference {difference} exceeds tolerance {tolerance}"
        )
        return EvalResult(
            passed=passed,
            reason=reason,
            evaluator_type=self.name,
            details={
                "actual": actual,
                "expected": expected_value,
                "difference": difference,
                "tolerance": tolerance,
            },
        )
