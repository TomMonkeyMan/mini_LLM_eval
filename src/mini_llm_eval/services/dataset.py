"""Dataset loading and validation helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from mini_llm_eval.core.exceptions import DatasetLoadError
from mini_llm_eval.models.schemas import EvalCase


def _normalize_case_payload(payload: dict[str, Any], line_no: int | None = None) -> dict[str, Any]:
    data = dict(payload)

    if "eval_types" not in data and "eval_type" in data:
        eval_type = data.pop("eval_type")
        if isinstance(eval_type, str):
            data["eval_types"] = [eval_type]
        elif isinstance(eval_type, list):
            data["eval_types"] = eval_type
        else:
            raise DatasetLoadError(
                f"Invalid eval_type at line {line_no}: expected string or list, got {type(eval_type).__name__}"
            )

    return data


def _parse_jsonl(path: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []

    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                content = line.strip()
                if not content:
                    continue
                try:
                    payload = json.loads(content)
                except json.JSONDecodeError as exc:
                    raise DatasetLoadError(
                        f"Invalid JSONL at {path}:{line_no}: {exc.msg}"
                    ) from exc
                if not isinstance(payload, dict):
                    raise DatasetLoadError(
                        f"Invalid dataset item at {path}:{line_no}: each record must be an object"
                    )
                try:
                    cases.append(EvalCase.model_validate(_normalize_case_payload(payload, line_no=line_no)))
                except ValidationError as exc:
                    raise DatasetLoadError(
                        f"Invalid dataset item at {path}:{line_no}: {exc}"
                    ) from exc
    except OSError as exc:
        raise DatasetLoadError(f"Failed to read dataset {path}: {exc}") from exc

    return cases


def _parse_json(path: Path) -> list[EvalCase]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise DatasetLoadError(f"Invalid JSON dataset {path}: {exc.msg}") from exc
    except OSError as exc:
        raise DatasetLoadError(f"Failed to read dataset {path}: {exc}") from exc

    if not isinstance(payload, list):
        raise DatasetLoadError(f"JSON dataset must be a list of objects: {path}")

    cases: list[EvalCase] = []
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise DatasetLoadError(f"Invalid dataset item at index {index}: each record must be an object")
        try:
            cases.append(EvalCase.model_validate(_normalize_case_payload(item, line_no=index)))
        except ValidationError as exc:
            raise DatasetLoadError(f"Invalid dataset item at index {index}: {exc}") from exc
    return cases


def load_dataset(path: str) -> list[EvalCase]:
    """Load a dataset from JSONL or JSON."""

    dataset_path = Path(path).expanduser()
    if not dataset_path.exists():
        raise DatasetLoadError(f"Dataset file not found: {dataset_path}")
    if not dataset_path.is_file():
        raise DatasetLoadError(f"Dataset path is not a file: {dataset_path}")

    suffix = dataset_path.suffix.lower()
    if suffix == ".jsonl":
        cases = _parse_jsonl(dataset_path)
    elif suffix == ".json":
        cases = _parse_json(dataset_path)
    else:
        raise DatasetLoadError(
            f"Unsupported dataset format for {dataset_path}. Expected .jsonl or .json"
        )

    if not cases:
        raise DatasetLoadError(f"Dataset is empty: {dataset_path}")

    return cases
