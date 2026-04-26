"""Length-range evaluator."""

from __future__ import annotations

from mini_llm_eval.core.exceptions import EvaluatorError
from mini_llm_eval.evaluators.base import BaseEvaluator
from mini_llm_eval.evaluators.registry import register
from mini_llm_eval.models.schemas import EvalResult


@register("length_range")
class LengthRangeEvaluator(BaseEvaluator):
    """Pass when output length falls within configured bounds."""

    @property
    def name(self) -> str:
        return "length_range"

    def evaluate(
        self,
        output: str,
        expected: str,
        case_metadata: dict | None = None,
        config: dict | None = None,
    ) -> EvalResult:
        settings = dict(case_metadata or {})
        settings.update(config or {})

        if "min_length" not in settings and "max_length" not in settings:
            raise EvaluatorError(
                "length_range evaluator requires case_metadata/config with min_length or max_length"
            )

        min_length = int(settings["min_length"]) if "min_length" in settings else None
        max_length = int(settings["max_length"]) if "max_length" in settings else None
        length = len(output)

        if min_length is not None and length < min_length:
            passed = False
            reason = f"Output length {length} is shorter than minimum {min_length}"
        elif max_length is not None and length > max_length:
            passed = False
            reason = f"Output length {length} exceeds maximum {max_length}"
        else:
            passed = True
            reason = f"Output length {length} is within configured range"

        return EvalResult(
            passed=passed,
            reason=reason,
            evaluator_type=self.name,
            details={
                "length": length,
                "min_length": min_length,
                "max_length": max_length,
            },
        )
