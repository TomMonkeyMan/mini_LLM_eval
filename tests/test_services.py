"""Tests for executor and run service orchestration."""

from __future__ import annotations

import json

import pytest

from mini_llm_eval.core.config import Config, ProviderConfig
from mini_llm_eval.db.database import Database
from mini_llm_eval.db.file_storage import FileStorage
from mini_llm_eval.evaluators.contains import ContainsEvaluator
from mini_llm_eval.models.schemas import EvalCase, RunConfig, RunStatus
from mini_llm_eval.providers.base import BaseProvider
from mini_llm_eval.providers.mock import MockProvider
from mini_llm_eval.services.executor import Executor
from mini_llm_eval.services.run_service import RunService


@pytest.mark.asyncio
async def test_executor_processes_cases_and_writes_results(tmp_path) -> None:
    provider = MockProvider(
        "mock-default",
        ProviderConfig.from_mapping(
            {
                "type": "mock",
                "fallback": {"enabled": True, "success_rate": 1.0},
            }
        ),
    )
    executor = Executor(concurrency=2, timeout_ms=5000)
    written = []

    async def writer(result):
        written.append(result.case_id)

    cases = [
        EvalCase(case_id="case-1", query="q1", expected_answer="ans", eval_types=["contains"]),
        EvalCase(case_id="case-2", query="q2", expected_answer="ans", eval_types=["contains"]),
    ]

    results = await executor.execute_batch(
        run_id="run-1",
        cases=cases,
        provider=provider,
        evaluators={"contains": ContainsEvaluator()},
        on_result=writer,
    )

    assert len(results) == 2
    assert set(written) == {"case-1", "case-2"}


@pytest.mark.asyncio
async def test_run_service_start_run_completes_and_writes_meta(tmp_path) -> None:
    mapping_path = tmp_path / "mock_mapping.json"
    mapping_path.write_text(
        json.dumps(
            {
                "Question A": "expected-a",
                "Question B": "expected-b",
            }
        ),
        encoding="utf-8",
    )
    dataset_path = tmp_path / "dataset.jsonl"
    dataset_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "case_id": "case-a",
                        "query": "Question A",
                        "expected_answer": "expected-a",
                        "eval_type": "contains",
                        "tags": ["knowledge"],
                    }
                ),
                json.dumps(
                    {
                        "case_id": "case-b",
                        "query": "Question B",
                        "expected_answer": "expected-b",
                        "eval_type": "contains",
                        "tags": ["knowledge", "secondary"],
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    db = Database(str(tmp_path / "eval.db"))
    storage = FileStorage(output_dir=str(tmp_path / "outputs"))
    service = RunService(
        db=db,
        file_storage=storage,
        providers={
            "mock-default": ProviderConfig.from_mapping(
                {
                    "type": "mock",
                    "mapping_file": str(mapping_path),
                }
            )
        },
        config=Config(concurrency=2, timeout_ms=5000),
    )

    run_id = await service.start_run(
        RunConfig(
            run_id="run-1",
            dataset_path=str(dataset_path),
            provider_name="mock-default",
            concurrency=2,
            timeout_ms=5000,
        )
    )

    run_record = await db.get_run(run_id)
    meta = storage.read_json(str(tmp_path / "outputs" / run_id / "meta.json"))
    case_rows = storage.read_json_lines(str(tmp_path / "outputs" / run_id / "case_results.jsonl"))

    assert run_record["status"] == RunStatus.SUCCEEDED.value
    assert meta["status"] == RunStatus.SUCCEEDED.value
    assert len(case_rows) == 2
    assert meta["summary"]["passed_cases"] == 2


@pytest.mark.asyncio
async def test_run_service_resume_skips_completed_cases(tmp_path) -> None:
    mapping_path = tmp_path / "mock_mapping.json"
    mapping_path.write_text(
        json.dumps(
            {
                "Question A": "expected-a",
                "Question B": "expected-b",
            }
        ),
        encoding="utf-8",
    )
    dataset_path = tmp_path / "dataset.jsonl"
    dataset_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "case_id": "case-a",
                        "query": "Question A",
                        "expected_answer": "expected-a",
                        "eval_type": "contains",
                        "tags": ["knowledge"],
                    }
                ),
                json.dumps(
                    {
                        "case_id": "case-b",
                        "query": "Question B",
                        "expected_answer": "expected-b",
                        "eval_type": "contains",
                        "tags": ["knowledge"],
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    db = Database(str(tmp_path / "eval.db"))
    await db.init()
    storage = FileStorage(output_dir=str(tmp_path / "outputs"))
    providers = {
        "mock-default": ProviderConfig.from_mapping(
            {
                "type": "mock",
                "mapping_file": str(mapping_path),
            }
        )
    }
    service = RunService(
        db=db,
        file_storage=storage,
        providers=providers,
        config=Config(concurrency=2, timeout_ms=5000),
    )
    run_config = RunConfig(
        run_id="run-1",
        dataset_path=str(dataset_path),
        provider_name="mock-default",
        concurrency=2,
        timeout_ms=5000,
    )
    await db.create_run(run_config)
    await db.update_run_status("run-1", RunStatus.RUNNING.value, event="run_started")

    from mini_llm_eval.models.schemas import CaseResult, CaseStatus, EvalResult, ProviderStatus

    await db.save_case_result(
        CaseResult(
            run_id="run-1",
            case_id="case-a",
            query="Question A",
            expected="expected-a",
            actual_output="expected-a",
            case_status=CaseStatus.COMPLETED,
            eval_results={
                "contains": EvalResult(
                    passed=True,
                    reason="ok",
                    evaluator_type="contains",
                )
            },
            latency_ms=1.0,
            provider_status=ProviderStatus.SUCCESS,
        )
    )

    resumed_run_id = await service.resume_run("run-1")
    meta = storage.read_json(str(tmp_path / "outputs" / resumed_run_id / "meta.json"))
    rows = await db.get_case_results("run-1")

    assert resumed_run_id == "run-1"
    assert len(rows) == 2
    assert meta["summary"]["passed_cases"] == 2


@pytest.mark.asyncio
async def test_run_service_closes_provider_on_failure(tmp_path) -> None:
    dataset_path = tmp_path / "dataset.jsonl"
    dataset_path.write_text(
        json.dumps(
            {
                "case_id": "case-a",
                "query": "Question A",
                "expected_answer": "expected-a",
                "eval_type": "contains",
                "tags": ["knowledge"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    class CloseTrackingProvider(MockProvider):
        def __init__(self) -> None:
            super().__init__(
                "mock-default",
                ProviderConfig.from_mapping(
                    {
                        "type": "mock",
                        "fallback": {"enabled": True, "success_rate": 1.0},
                    }
                ),
            )
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    class TestRunService(RunService):
        def __init__(self, *args, provider: BaseProvider, **kwargs):
            super().__init__(*args, **kwargs)
            self._provider = provider

        def _create_provider(self, provider_name: str):
            return self._provider

        async def _persist_result(self, result):
            raise RuntimeError("boom")

    provider = CloseTrackingProvider()
    db = Database(str(tmp_path / "eval.db"))
    storage = FileStorage(output_dir=str(tmp_path / "outputs"))
    service = TestRunService(
        db=db,
        file_storage=storage,
        providers={"mock-default": ProviderConfig(type="mock")},
        config=Config(concurrency=1, timeout_ms=5000),
        provider=provider,
    )

    with pytest.raises(RuntimeError, match="boom"):
        await service.start_run(
            RunConfig(
                run_id="run-1",
                dataset_path=str(dataset_path),
                provider_name="mock-default",
                concurrency=1,
                timeout_ms=5000,
            )
        )

    assert provider.closed is True
