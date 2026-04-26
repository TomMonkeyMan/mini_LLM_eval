"""Provider factory helpers."""

from __future__ import annotations

from mini_llm_eval.core.config import ProviderConfig
from mini_llm_eval.core.exceptions import ProviderInitError
from mini_llm_eval.providers.base import BaseProvider


def create_provider(name: str, config: ProviderConfig) -> BaseProvider:
    """Create a provider instance from config."""

    if config.type == "mock":
        from mini_llm_eval.providers.mock import MockProvider

        return MockProvider(name, config)
    if config.type == "plugin":
        from mini_llm_eval.providers.plugin import PluginProvider

        return PluginProvider(name, config)
    if config.type == "openai_compatible":
        from mini_llm_eval.providers.openai_compatible import OpenAICompatibleProvider

        return OpenAICompatibleProvider(name, config)
    raise ProviderInitError(f"Unknown provider type: {config.type}")
