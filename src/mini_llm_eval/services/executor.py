"""Execution orchestration for a single run."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from mini_llm_eval.core.exceptions import EvaluatorError
from mini_llm_eval.core.logging import get_logger
from mini_llm_eval.models.schemas import (
    CaseResult,
    CaseStatus,
    EvalCase,
    EvalResult,
    ProviderStatus,
)
from mini_llm_eval.providers.base import BaseProvider
from mini_llm_eval.evaluators.base import BaseEvaluator

ResultWriter = Callable[[CaseResult], Awaitable[None]]
logger = get_logger(__name__)


class Executor:
    """Execute a batch of cases with bounded Provider concurrency."""

    def __init__(self, concurrency: int = 4, timeout_ms: int = 30000):
        self.concurrency = concurrency
        self.provider_semaphore = asyncio.Semaphore(concurrency)
        self.timeout_ms = timeout_ms
        self.result_queue: asyncio.Queue[CaseResult | object] = asyncio.Queue()
        self._sentinel = object()

    async def execute_case(
        self,
        run_id: str,
        case: EvalCase,
        provider: BaseProvider,
        evaluators: list[BaseEvaluator],
    ) -> CaseResult:
        """Execute provider and evaluator logic for a single case."""

        try:
            async with self.provider_semaphore:
                provider_response = await asyncio.wait_for(
                    provider.generate(case.query, expected_answer=case.expected_answer),
                    timeout=self.timeout_ms / 1000,
                )
        except asyncio.TimeoutError:
            logger.warning(
                "Provider request timed out during case execution",
                extra={
                    "event": "case_provider_timeout",
                    "run_id": run_id,
                    "case_id": case.case_id,
                    "provider_name": provider.name,
                    "timeout_ms": self.timeout_ms,
                },
            )
            return self._build_error_result(
                run_id=run_id,
                case=case,
                provider_status=ProviderStatus.TIMEOUT,
                error_message="Provider request timed out",
            )
        except Exception as exc:
            logger.warning(
                "Provider request failed during case execution",
                extra={
                    "event": "case_provider_error",
                    "run_id": run_id,
                    "case_id": case.case_id,
                    "provider_name": provider.name,
                    "error": str(exc),
                },
            )
            return self._build_error_result(
                run_id=run_id,
                case=case,
                provider_status=ProviderStatus.ERROR,
                error_message=str(exc),
            )

        eval_results: dict[str, EvalResult] = {}
        had_evaluator_error = False
        for evaluator in evaluators:
            try:
                eval_results[evaluator.name] = evaluator.evaluate(
                    output=provider_response.output,
                    expected=case.expected_answer,
                    case_metadata=case.metadata,
                )
            except Exception as exc:
                had_evaluator_error = True
                logger.warning(
                    "Evaluator raised an exception",
                    extra={
                        "event": "case_evaluator_error",
                        "run_id": run_id,
                        "case_id": case.case_id,
                        "evaluator_name": evaluator.name,
                        "error": str(exc),
                    },
                )
                eval_results[evaluator.name] = EvalResult(
                    passed=False,
                    reason=f"Evaluator raised an exception: {exc}",
                    evaluator_type=evaluator.name,
                    error=str(exc),
                )

        if provider_response.status is not ProviderStatus.SUCCESS:
            case_status = CaseStatus.ERROR
        elif had_evaluator_error:
            case_status = CaseStatus.ERROR
        else:
            case_status = CaseStatus.COMPLETED

        return CaseResult(
            run_id=run_id,
            case_id=case.case_id,
            query=case.query,
            expected=case.expected_answer,
            actual_output=provider_response.output,
            case_status=case_status,
            eval_results=eval_results,
            latency_ms=provider_response.latency_ms,
            provider_status=provider_response.status,
            error_message=provider_response.error,
            retries=0,
            created_at=datetime.now(timezone.utc),
        )

    async def execute_batch(
        self,
        run_id: str,
        cases: list[EvalCase],
        provider: BaseProvider,
        evaluators: dict[str, BaseEvaluator],
        on_result: ResultWriter,
    ) -> list[CaseResult]:
        """Execute cases concurrently and write results through a writer queue."""

        logger.info(
            "Batch execution started",
            extra={
                "event": "batch_execution_started",
                "run_id": run_id,
                "case_count": len(cases),
                "provider_name": provider.name,
                "concurrency": self.concurrency,
            },
        )
        writer_task = asyncio.create_task(self.writer_loop(on_result))
        results: list[CaseResult] = []

        async def run_one(case: EvalCase) -> None:
            try:
                case_evaluators = self._resolve_case_evaluators(case, evaluators)
                result = await self.execute_case(run_id, case, provider, case_evaluators)
            except Exception as exc:
                result = self._build_error_result(
                    run_id=run_id,
                    case=case,
                    provider_status=ProviderStatus.ERROR,
                    error_message=str(exc),
                )
            results.append(result)
            await self.result_queue.put(result)

        tasks = [asyncio.create_task(run_one(case)) for case in cases]
        try:
            await asyncio.gather(*tasks)
        finally:
            await self.result_queue.put(self._sentinel)
            await writer_task

        logger.info(
            "Batch execution completed",
            extra={
                "event": "batch_execution_completed",
                "run_id": run_id,
                "case_count": len(results),
                "provider_name": provider.name,
            },
        )
        return results

    async def writer_loop(self, on_result: ResultWriter) -> None:
        """Serialize writes through a single queue consumer."""

        while True:
            item = await self.result_queue.get()
            if item is self._sentinel:
                self.result_queue.task_done()
                break
            await on_result(item)
            self.result_queue.task_done()

    def _resolve_case_evaluators(
        self,
        case: EvalCase,
        evaluators: dict[str, BaseEvaluator],
    ) -> list[BaseEvaluator]:
        names = case.eval_types
        if names == ["all"]:
            return list(evaluators.values())

        selected: list[BaseEvaluator] = []
        missing: list[str] = []
        for name in names:
            evaluator = evaluators.get(name)
            if evaluator is None:
                missing.append(name)
            else:
                selected.append(evaluator)
        if missing:
            raise EvaluatorError(f"Unknown evaluators for case {case.case_id}: {missing}")
        return selected

    @staticmethod
    def _build_error_result(
        run_id: str,
        case: EvalCase,
        provider_status: ProviderStatus,
        error_message: str,
    ) -> CaseResult:
        return CaseResult(
            run_id=run_id,
            case_id=case.case_id,
            query=case.query,
            expected=case.expected_answer,
            actual_output="",
            case_status=CaseStatus.ERROR,
            eval_results={},
            latency_ms=0.0,
            provider_status=provider_status,
            error_message=error_message,
            retries=0,
            created_at=datetime.now(timezone.utc),
        )
