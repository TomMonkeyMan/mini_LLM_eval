"""Tests for evaluator registry and built-in evaluators."""

from __future__ import annotations

import importlib

import pytest

from mini_llm_eval.core.exceptions import EvaluatorError
from mini_llm_eval.evaluators.registry import auto_discover, clear_registry, get, list_all


def setup_function() -> None:
    clear_registry()


def teardown_function() -> None:
    clear_registry()


def test_auto_discover_registers_builtin_evaluators() -> None:
    auto_discover("mini_llm_eval.evaluators")

    assert list_all() == [
        "contains",
        "contains_all",
        "exact_match",
        "json_field",
        "length_range",
        "not_contains",
        "numeric_tolerance",
        "regex",
    ]


def test_get_returns_registered_evaluator_instance() -> None:
    auto_discover("mini_llm_eval.evaluators")

    evaluator = get("contains")

    assert evaluator.name == "contains"


def test_exact_match_evaluator() -> None:
    clear_registry()
    module = importlib.import_module("mini_llm_eval.evaluators.exact_match")
    evaluator = module.ExactMatchEvaluator()

    result = evaluator.evaluate(" answer ", "answer")

    assert result.passed is True


def test_contains_evaluator_supports_pipe_delimited_keywords() -> None:
    clear_registry()
    module = importlib.import_module("mini_llm_eval.evaluators.contains")
    evaluator = module.ContainsEvaluator()

    result = evaluator.evaluate("The HVIL loop is open", "battery|hvil|connector")

    assert result.passed is True
    assert result.details["matched"] == ["hvil"]


def test_regex_evaluator_matches_patterns() -> None:
    clear_registry()
    module = importlib.import_module("mini_llm_eval.evaluators.regex")
    evaluator = module.RegexEvaluator()

    result = evaluator.evaluate("Voltage: 384V", r"\d+V")

    assert result.passed is True


def test_not_contains_evaluator_rejects_forbidden_keywords() -> None:
    clear_registry()
    module = importlib.import_module("mini_llm_eval.evaluators.not_contains")
    evaluator = module.NotContainsEvaluator()

    result = evaluator.evaluate("The answer leaked a token value", "password|token|secret")

    assert result.passed is False
    assert result.details["matched"] == ["token"]


def test_contains_all_evaluator_requires_all_keywords() -> None:
    clear_registry()
    module = importlib.import_module("mini_llm_eval.evaluators.contains_all")
    evaluator = module.ContainsAllEvaluator()

    result = evaluator.evaluate(
        "机器学习依赖训练数据和模型设计",
        "机器学习|训练数据|模型",
    )

    assert result.passed is True
    assert result.details["missing"] == []


def test_length_range_evaluator_uses_case_metadata_bounds() -> None:
    clear_registry()
    module = importlib.import_module("mini_llm_eval.evaluators.length_range")
    evaluator = module.LengthRangeEvaluator()

    result = evaluator.evaluate(
        "sufficiently detailed answer",
        "",
        case_metadata={"min_length": 10, "max_length": 50},
    )

    assert result.passed is True
    assert result.details["length"] == len("sufficiently detailed answer")


def test_json_field_evaluator_uses_field_config() -> None:
    clear_registry()
    module = importlib.import_module("mini_llm_eval.evaluators.json_field")
    evaluator = module.JsonFieldEvaluator()

    result = evaluator.evaluate(
        '{"tool": {"name": "sql_query"}}',
        "sql_query",
        config={"field": "tool.name"},
    )

    assert result.passed is True


def test_numeric_tolerance_evaluator_supports_percentage_tolerance() -> None:
    clear_registry()
    module = importlib.import_module("mini_llm_eval.evaluators.numeric_tolerance")
    evaluator = module.NumericToleranceEvaluator()

    result = evaluator.evaluate("104", "100", config={"percentage": 0.05})

    assert result.passed is True


def test_numeric_tolerance_evaluator_raises_for_non_numeric_values() -> None:
    clear_registry()
    module = importlib.import_module("mini_llm_eval.evaluators.numeric_tolerance")
    evaluator = module.NumericToleranceEvaluator()

    with pytest.raises(EvaluatorError):
        evaluator.evaluate("not-a-number", "100")


def test_unknown_evaluator_raises_error() -> None:
    with pytest.raises(EvaluatorError):
        get("missing")
