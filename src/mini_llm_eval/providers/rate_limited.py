"""Provider wrapper for optional concurrency and rate limiting."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from mini_llm_eval.core.logging import get_logger
from mini_llm_eval.models.schemas import ProviderResponse
from mini_llm_eval.providers.base import BaseProvider

logger = get_logger(__name__)


class ProviderRateLimiter:
    """Simple request-start rate limiter based on requests per second."""

    def __init__(
        self,
        requests_per_second: float,
        *,
        monotonic: Callable[[], float] | None = None,
        sleeper: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be > 0")
        self._interval_seconds = 1.0 / requests_per_second
        self._monotonic = monotonic or time.monotonic
        self._sleeper = sleeper or asyncio.sleep
        self._lock = asyncio.Lock()
        self._next_available_at = 0.0

    async def acquire(self) -> float:
        """Wait until the next request slot is available."""

        async with self._lock:
            now = self._monotonic()
            scheduled_at = max(now, self._next_available_at)
            self._next_available_at = scheduled_at + self._interval_seconds
            wait_seconds = max(0.0, scheduled_at - now)

        if wait_seconds > 0:
            await self._sleeper(wait_seconds)
        return wait_seconds


class RateLimitedProvider(BaseProvider):
    """Wrap a provider with optional concurrency and request-rate controls."""

    def __init__(
        self,
        provider: BaseProvider,
        *,
        provider_concurrency_limit: int | None = None,
        requests_per_second: float | None = None,
        rate_limiter: ProviderRateLimiter | None = None,
    ) -> None:
        self._provider = provider
        self._provider_semaphore = (
            asyncio.Semaphore(provider_concurrency_limit)
            if provider_concurrency_limit is not None
            else None
        )
        self._rate_limiter = rate_limiter
        if self._rate_limiter is None and requests_per_second is not None:
            self._rate_limiter = ProviderRateLimiter(requests_per_second)

    @property
    def name(self) -> str:
        return self._provider.name

    async def generate(self, query: str, **kwargs) -> ProviderResponse:
        if self._rate_limiter is not None:
            wait_seconds = await self._rate_limiter.acquire()
            if wait_seconds > 0:
                logger.info(
                    "Provider rate limiter delayed request",
                    extra={
                        "event": "provider_rate_limit_wait",
                        "provider_name": self.name,
                        "wait_seconds": round(wait_seconds, 6),
                    },
                )

        if self._provider_semaphore is None:
            return await self._provider.generate(query, **kwargs)

        async with self._provider_semaphore:
            return await self._provider.generate(query, **kwargs)

    async def health_check(self) -> bool:
        return await self._provider.health_check()

    async def close(self) -> None:
        await self._provider.close()
