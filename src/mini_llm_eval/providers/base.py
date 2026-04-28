"""Base provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from mini_llm_eval.models.schemas import ProviderResponse


class BaseProvider(ABC):
    """Base contract for model providers."""

    @abstractmethod
    async def generate(self, query: str, **kwargs) -> ProviderResponse:
        """Generate a provider response for a single query."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable provider name."""

    async def health_check(self) -> bool:
        """Optional provider health check."""

        return True

    async def close(self) -> None:
        """Optional resource cleanup."""
