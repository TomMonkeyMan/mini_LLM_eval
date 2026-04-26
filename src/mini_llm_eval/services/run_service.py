"""Run orchestration service."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from statistics import mean
from typing import Any

from mini_llm_eval.core.config import Config, ProviderConfig, get_config, get_providers
from mini_llm_eval.core.exceptions import DatasetLoadError, PersistenceError, ProviderInitError
from mini_llm_eval.db.database import Database
from mini_llm_eval.db.file_storage import FileStorage
from mini_llm_eval.evaluators import registry as evaluator_registry
from mini_llm_eval.models.schemas import (
    CaseResult,
    CaseStatus,
    EvalCase,
    RunConfig,
    RunStatus,
    TagPassRate,
)
from mini_llm_eval.providers.factory import create_provider
from mini_llm_eval.services.dataset import load_dataset
from mini_llm_eval.services.executor import Executor


class RunService:
    """Coordinate dataset loading, provider execution, persistence, and artifacts."""

    def __init__(
        self,
        db: Database,
        file_storage: FileStorage,
        providers: dict[str, ProviderConfig] | None = None,
        config: Config | None = None,
    ) -> None:
        self.db = db
        self.file_storage = file_storage
        self.providers = providers
        self.config = config

    async def start_run(self, run_config: RunConfig) -> str:
        """Create and execute a new run end to end."""

        await self.db.init()
        await self.db.create_run(run_config)
        await self.db.update_run_status(
            run_config.run_id,
            RunStatus.RUNNING.value,
            event="run_started",
            message="Run execution started",
        )
        provider = None

        try:
            cases = load_dataset(run_config.dataset_path)
            evaluator_map = self._load_evaluators(cases)
            provider = self._create_provider(run_config.provider_name)

            executor = Executor(
                concurrency=run_config.concurrency,
                timeout_ms=run_config.timeout_ms,
            )
            results = await executor.execute_batch(
                run_id=run_config.run_id,
                cases=cases,
                provider=provider,
                evaluators=evaluator_map,
                on_result=self._persist_result,
            )

            summary = self._build_summary(cases, results)
            await self.db.complete_run(run_config.run_id, success=True, summary=summary)
            meta = await self._build_meta(run_config.run_id)
            self.file_storage.save_meta(run_config.run_id, meta)
            return run_config.run_id
        except Exception as exc:
            await self.db.complete_run(
                run_config.run_id,
                success=False,
                summary={"fatal_error": str(exc)},
            )
            meta = await self._build_meta(run_config.run_id)
            self.file_storage.save_meta(run_config.run_id, meta)
            raise
        finally:
            if provider is not None:
                await provider.close()

    async def resume_run(self, run_id: str) -> str:
        """Resume a previously started run by skipping completed cases."""

        await self.db.init()
        run_record = await self.db.get_run(run_id)
        if run_record is None:
            raise PersistenceError(f"Run not found: {run_id}")

        if run_record["status"] == RunStatus.SUCCEEDED.value:
            return run_id
        if run_record["status"] == RunStatus.PENDING.value:
            await self.db.update_run_status(
                run_id,
                RunStatus.RUNNING.value,
                event="run_resumed",
                message="Run resumed from pending state",
            )
        elif run_record["status"] not in {RunStatus.RUNNING.value}:
            raise PersistenceError(f"Run {run_id} is not resumable from status {run_record['status']}")

        dataset_path = run_record["dataset_path"]
        provider_name = run_record["provider_name"]
        cases = load_dataset(dataset_path)
        completed_case_ids = await self.db.get_completed_cases(run_id)
        remaining_cases = [case for case in cases if case.case_id not in completed_case_ids]

        evaluator_map = self._load_evaluators(remaining_cases or cases)
        provider = None
        config = self.config or get_config()
        run_config = RunConfig(
            run_id=run_id,
            dataset_path=dataset_path,
            provider_name=provider_name,
            model_config=json.loads(run_record["model_config_json"]),
            concurrency=config.concurrency,
            timeout_ms=config.timeout_ms,
            max_retries=config.max_retries,
        )

        try:
            provider = self._create_provider(provider_name)
            executor = Executor(
                concurrency=run_config.concurrency,
                timeout_ms=run_config.timeout_ms,
            )
            new_results = await executor.execute_batch(
                run_id=run_id,
                cases=remaining_cases,
                provider=provider,
                evaluators=evaluator_map,
                on_result=self._persist_result,
            )
            stored_results = await self._load_stored_case_results(run_id)
            summary = self._build_summary(cases, stored_results)
            await self.db.complete_run(run_id, success=True, summary=summary)
            meta = await self._build_meta(run_id)
            self.file_storage.save_meta(run_id, meta)
            return run_id
        except Exception as exc:
            await self.db.complete_run(run_id, success=False, summary={"fatal_error": str(exc)})
            meta = await self._build_meta(run_id)
            self.file_storage.save_meta(run_id, meta)
            raise
        finally:
            if provider is not None:
                await provider.close()

    async def _persist_result(self, result: CaseResult) -> None:
        artifact_path = self.file_storage.append_case_result(result.run_id, result)
        persisted_result = result.model_copy(update={"output_path": artifact_path})
        await self.db.save_case_result(persisted_result)

    async def _build_meta(self, run_id: str) -> dict[str, Any]:
        run_record = await self.db.get_run(run_id)
        state_logs = await self.db.get_state_logs(run_id)
        case_results = await self.db.get_case_results(run_id)

        if run_record is None:
            raise PersistenceError(f"Run not found while building meta: {run_id}")

        return {
            "run_id": run_record["run_id"],
            "dataset_path": run_record["dataset_path"],
            "provider_name": run_record["provider_name"],
            "model_config": json.loads(run_record["model_config_json"]),
            "status": run_record["status"],
            "summary": json.loads(run_record["summary_json"]) if run_record["summary_json"] else None,
            "created_at": run_record["created_at"],
            "started_at": run_record["started_at"],
            "finished_at": run_record["finished_at"],
            "state_logs": state_logs,
            "case_result_count": len(case_results),
        }

    async def _load_stored_case_results(self, run_id: str) -> list[CaseResult]:
        rows = await self.db.get_case_results(run_id)
        return [CaseResult.model_validate_json(row["payload_json"]) for row in rows]

    def _load_evaluators(self, cases: list[EvalCase]) -> dict[str, Any]:
        evaluator_registry.auto_discover()
        requested = set()
        for case in cases:
            if case.eval_types == ["all"]:
                for name in evaluator_registry.list_all():
                    requested.add(name)
            else:
                requested.update(case.eval_types)
        return {name: evaluator_registry.get(name) for name in requested}

    def _create_provider(self, provider_name: str):
        providers = self.providers or get_providers()
        provider_config = providers.get(provider_name)
        if provider_config is None:
            raise ProviderInitError(f"Unknown provider configured for run: {provider_name}")
        return create_provider(provider_name, provider_config)

    def _build_summary(
        self,
        cases: list[EvalCase],
        results: list[CaseResult],
    ) -> dict[str, Any]:
        case_lookup = {case.case_id: case for case in cases}
        total_cases = len(cases)
        error_cases = 0
        passed_cases = 0
        failed_cases = 0
        latencies: list[float] = []
        tag_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "passed": 0})
        error_distribution: Counter[str] = Counter()

        for result in results:
            case = case_lookup.get(result.case_id)
            tags = case.tags if case is not None else []
            is_error = result.case_status is CaseStatus.ERROR
            is_passed = (
                not is_error
                and bool(result.eval_results)
                and all(item.passed and not item.error for item in result.eval_results.values())
            )

            if is_error:
                error_cases += 1
                error_distribution[result.error_message or "case_error"] += 1
                for eval_result in result.eval_results.values():
                    if eval_result.error:
                        error_distribution[f"evaluator:{eval_result.evaluator_type}"] += 1
            elif is_passed:
                passed_cases += 1
            else:
                failed_cases += 1

            latencies.append(result.latency_ms)
            for tag in tags:
                tag_counts[tag]["total"] += 1
                if is_passed:
                    tag_counts[tag]["passed"] += 1

        pass_rate = passed_cases / total_cases if total_cases else 0.0
        sorted_latencies = sorted(latencies)
        p95_latency = self._percentile(sorted_latencies, 0.95)
        avg_latency = mean(latencies) if latencies else 0.0

        return {
            "total_cases": total_cases,
            "passed_cases": passed_cases,
            "failed_cases": failed_cases,
            "error_cases": error_cases,
            "pass_rate": pass_rate,
            "tag_pass_rates": {
                tag: TagPassRate(
                    total=counts["total"],
                    passed=counts["passed"],
                    pass_rate=(counts["passed"] / counts["total"]) if counts["total"] else 0.0,
                ).model_dump(mode="json")
                for tag, counts in tag_counts.items()
            },
            "avg_latency_ms": avg_latency,
            "p95_latency_ms": p95_latency,
            "error_count": sum(error_distribution.values()),
            "error_distribution": dict(error_distribution),
        }

    @staticmethod
    def _percentile(sorted_values: list[float], percentile: float) -> float:
        if not sorted_values:
            return 0.0
        index = max(0, min(len(sorted_values) - 1, int((len(sorted_values) - 1) * percentile)))
        return sorted_values[index]
