"""Tests for dataset loading."""

from __future__ import annotations

import json

import pytest

from mini_llm_eval.core.exceptions import DatasetLoadError
from mini_llm_eval.services.dataset import load_dataset


def test_load_dataset_supports_jsonl(tmp_path) -> None:
    dataset_path = tmp_path / "cases.jsonl"
    dataset_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "case_id": "case-1",
                        "query": "hello",
                        "expected_answer": "world",
                        "eval_type": "contains",
                    }
                ),
                json.dumps(
                    {
                        "case_id": "case-2",
                        "query": "foo",
                        "expected_answer": "bar",
                        "eval_types": ["exact_match"],
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    cases = load_dataset(str(dataset_path))

    assert len(cases) == 2
    assert cases[0].eval_types == ["contains"]
    assert cases[1].eval_types == ["exact_match"]


def test_load_dataset_supports_json_array(tmp_path) -> None:
    dataset_path = tmp_path / "cases.json"
    dataset_path.write_text(
        json.dumps(
            [
                {
                    "case_id": "case-1",
                    "query": "hello",
                    "expected_answer": "world",
                    "eval_type": "contains",
                }
            ]
        ),
        encoding="utf-8",
    )

    cases = load_dataset(str(dataset_path))

    assert len(cases) == 1
    assert cases[0].case_id == "case-1"


def test_load_dataset_rejects_invalid_eval_type_shape(tmp_path) -> None:
    dataset_path = tmp_path / "cases.jsonl"
    dataset_path.write_text(
        json.dumps(
            {
                "case_id": "case-1",
                "query": "hello",
                "expected_answer": "world",
                "eval_type": 1,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(DatasetLoadError):
        load_dataset(str(dataset_path))


def test_load_dataset_rejects_missing_required_fields(tmp_path) -> None:
    dataset_path = tmp_path / "cases.json"
    dataset_path.write_text(json.dumps([{"case_id": "case-1"}]), encoding="utf-8")

    with pytest.raises(DatasetLoadError):
        load_dataset(str(dataset_path))


def test_load_dataset_rejects_unsupported_suffix(tmp_path) -> None:
    dataset_path = tmp_path / "cases.txt"
    dataset_path.write_text("{}", encoding="utf-8")

    with pytest.raises(DatasetLoadError):
        load_dataset(str(dataset_path))
