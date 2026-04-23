"""Retry helpers for provider calls."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from mini_llm_eval.core.exceptions import ProviderError

T = TypeVar("T")

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
) -> T:
    """Run an async function with bounded retries for retryable provider errors."""

    attempt = 0
    while True:
        try:
            return await func()
        except ProviderError as exc:
            attempt += 1
            if exc.args and exc.args[0] not in RETRYABLE_ERROR_CODES:
                raise
            if attempt > max_retries:
                raise
            delay = retry_delays[min(attempt - 1, len(retry_delays) - 1)]
            await asyncio.sleep(delay)
