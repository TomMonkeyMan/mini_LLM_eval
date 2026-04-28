"""Provider factory helpers."""

from __future__ import annotations

from mini_llm_eval.core.config import ProviderConfig
from mini_llm_eval.core.exceptions import ProviderInitError
from mini_llm_eval.providers.base import BaseProvider
from mini_llm_eval.providers.rate_limited import RateLimitedProvider


def create_provider(name: str, config: ProviderConfig) -> BaseProvider:
    """Create a provider instance from config."""

    if config.type == "mock":
        from mini_llm_eval.providers.mock import MockProvider

        provider = MockProvider(name, config)
    elif config.type == "plugin":
        from mini_llm_eval.providers.plugin import PluginProvider

        provider = PluginProvider(name, config)
    elif config.type == "openai_compatible":
        from mini_llm_eval.providers.openai_compatible import OpenAICompatibleProvider

        provider = OpenAICompatibleProvider(name, config)
    else:
        raise ProviderInitError(f"Unknown provider type: {config.type}")

    if config.provider_concurrency_limit is None and config.requests_per_second is None:
        return provider

    return RateLimitedProvider(
        provider,
        provider_concurrency_limit=config.provider_concurrency_limit,
        requests_per_second=config.requests_per_second,
    )
