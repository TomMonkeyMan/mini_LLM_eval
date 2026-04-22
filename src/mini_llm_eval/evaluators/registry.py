"""Evaluator registration and discovery."""

from __future__ import annotations

import importlib
import pkgutil
import sys
from typing import Type

from mini_llm_eval.core.config import get_config
from mini_llm_eval.core.exceptions import EvaluatorError
from mini_llm_eval.evaluators.base import BaseEvaluator

_EVALUATORS: dict[str, Type[BaseEvaluator]] = {}


def register(name: str):
    """Register an evaluator class under a stable name."""

    def decorator(cls: Type[BaseEvaluator]) -> Type[BaseEvaluator]:
        if name in _EVALUATORS:
            raise EvaluatorError(f"Evaluator '{name}' is already registered")
        _EVALUATORS[name] = cls
        return cls

    return decorator


def get(name: str) -> BaseEvaluator:
    """Instantiate a registered evaluator by name."""

    try:
        evaluator_cls = _EVALUATORS[name]
    except KeyError as exc:
        raise EvaluatorError(f"Unknown evaluator: {name}") from exc
    return evaluator_cls()


def list_all() -> list[str]:
    """List all registered evaluator names in sorted order."""

    return sorted(_EVALUATORS)


def auto_discover(package_name: str | None = None) -> None:
    """Import all evaluator modules inside a package."""

    target_package = package_name or get_config().evaluators_package
    package = importlib.import_module(target_package)

    if not hasattr(package, "__path__"):
        raise EvaluatorError(f"Evaluator package is not importable as a package: {target_package}")

    for _, module_name, _ in pkgutil.iter_modules(package.__path__):
        if module_name.startswith("_") or module_name in {"base", "registry"}:
            continue
        qualified_name = f"{target_package}.{module_name}"
        if qualified_name not in sys.modules:
            importlib.import_module(qualified_name)


def clear_registry(package_name: str = "mini_llm_eval.evaluators") -> None:
    """Reset the in-memory registry and evaluator module cache for tests."""

    _EVALUATORS.clear()
    prefix = f"{package_name}."
    for module_name in list(sys.modules):
        if module_name.startswith(prefix) and module_name.split(".")[-1] not in {"base", "registry"}:
            sys.modules.pop(module_name, None)
