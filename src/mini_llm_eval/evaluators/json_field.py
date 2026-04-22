"""JSON field evaluator."""

from __future__ import annotations

import json
from typing import Any

from mini_llm_eval.core.exceptions import EvaluatorError
from mini_llm_eval.evaluators.base import BaseEvaluator
from mini_llm_eval.evaluators.registry import register
from mini_llm_eval.models.schemas import EvalResult


def _resolve_field_path(payload: Any, field_path: str) -> Any:
    current = payload
    for part in field_path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        raise EvaluatorError(f"Field path not found in JSON payload: {field_path}")
    return current


@register("json_field")
class JsonFieldEvaluator(BaseEvaluator):
    """Compare a specific field in a JSON output."""

    @property
    def name(self) -> str:
        return "json_field"

    def evaluate(
        self,
        output: str,
        expected: str,
        case_metadata: dict | None = None,
        config: dict | None = None,
    ) -> EvalResult:
        config = config or {}
        field_path = config.get("field") or (case_metadata or {}).get("json_field")
        if not field_path:
            raise EvaluatorError("json_field evaluator requires config['field'] or case_metadata['json_field']")

        try:
            parsed = json.loads(output)
        except json.JSONDecodeError as exc:
            raise EvaluatorError(f"Output is not valid JSON: {exc}") from exc

        actual_value = _resolve_field_path(parsed, field_path)
        passed = str(actual_value) == expected
        reason = (
            f"Field '{field_path}' matched expected value"
            if passed
            else f"Field '{field_path}' value {actual_value!r} != expected {expected!r}"
        )
        return EvalResult(
            passed=passed,
            reason=reason,
            evaluator_type=self.name,
            details={"field": field_path, "actual": actual_value},
        )
