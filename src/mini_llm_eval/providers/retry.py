"""Retry helpers for provider calls."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from mini_llm_eval.core.exceptions import ProviderError
from mini_llm_eval.core.logging import get_logger

T = TypeVar("T")
logger = get_logger(__name__)

RETRY_DELAYS = (1.0, 2.0, 4.0)
RETRYABLE_ERROR_CODES = {
    "timeout",
    "connection_error",
    "rate_limit",
    "server_error",
}


async def with_retry(
    func: Callable[[], Awaitable[T]],
    max_retries: int = 3,
    retry_delays: tuple[float, ...] = RETRY_DELAYS,
    provider_name: str | None = None,
) -> T:
    """Run an async function with bounded retries for retryable provider errors."""

    attempt = 0
    while True:
        try:
            return await func()
        except ProviderError as exc:
            attempt += 1
            if exc.code not in RETRYABLE_ERROR_CODES:
                raise
            if attempt > max_retries:
                logger.warning(
                    "Provider retry budget exhausted",
                    extra={
                        "event": "provider_retry_exhausted",
                        "provider_name": provider_name,
                        "attempt": attempt,
                        "error_code": exc.code,
                    },
                )
                raise
            delay = retry_delays[min(attempt - 1, len(retry_delays) - 1)]
            logger.warning(
                "Retrying provider request",
                extra={
                    "event": "provider_retry_scheduled",
                    "provider_name": provider_name,
                    "attempt": attempt,
                    "delay_seconds": delay,
                    "error_code": exc.code,
                },
            )
            await asyncio.sleep(delay)
