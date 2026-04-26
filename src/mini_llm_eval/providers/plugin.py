"""Plugin-backed provider implementation."""

from __future__ import annotations

import importlib.util
import inspect
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from mini_llm_eval.core.config import ProviderConfig
from mini_llm_eval.core.exceptions import ProviderInitError
from mini_llm_eval.core.logging import get_logger
from mini_llm_eval.models.schemas import ProviderResponse, ProviderStatus, TokenUsage
from mini_llm_eval.providers.base import BaseProvider

PluginGenerateFn = Callable[..., Awaitable[dict[str, Any]]]
logger = get_logger(__name__)


class PluginProvider(BaseProvider):
    """Load a user-supplied provider implementation from a Python file."""

    def __init__(self, name: str, config: ProviderConfig) -> None:
        self._name = name
        self._config = config
        self._generate_fn = self._load_plugin()

    @property
    def name(self) -> str:
        return self._name

    def _resolve_plugin_path(self) -> Path:
        plugin_name = self._config.plugin or self._config.extra.get("plugin")
        if not plugin_name:
            raise ProviderInitError("plugin provider requires 'plugin' configuration")

        plugins_dir = self._config.plugins_dir or self._config.extra.get("plugins_dir", "./plugins")
        base_dir = Path(plugins_dir).expanduser()

        plugin_path = Path(plugin_name)
        if plugin_path.suffix == ".py" and plugin_path.is_absolute():
            resolved = plugin_path
        elif plugin_path.suffix == ".py":
            resolved = (base_dir / plugin_path).resolve()
        else:
            resolved = (base_dir / f"{plugin_name}.py").resolve()

        if not resolved.exists():
            raise ProviderInitError(f"Plugin provider file not found: {resolved}")
        return resolved

    def _load_plugin(self) -> PluginGenerateFn:
        plugin_path = self._resolve_plugin_path()
        module_name = f"mini_llm_eval_plugin_{plugin_path.stem}_{abs(hash(plugin_path))}"
        spec = importlib.util.spec_from_file_location(module_name, plugin_path)
        if spec is None or spec.loader is None:
            raise ProviderInitError(f"Failed to load plugin module spec: {plugin_path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        generate_fn = getattr(module, "generate", None)
        if generate_fn is None:
            raise ProviderInitError(f"Plugin provider must define async generate(): {plugin_path}")
        if not inspect.iscoroutinefunction(generate_fn):
            raise ProviderInitError(f"Plugin provider generate() must be async: {plugin_path}")
        logger.info(
            "Loaded plugin provider",
            extra={
                "event": "provider_initialized",
                "provider_name": self._name,
                "provider_type": "plugin",
                "plugin_path": str(plugin_path),
            },
        )
        return generate_fn

    async def generate(self, query: str, **kwargs) -> ProviderResponse:
        start = time.perf_counter()
        result = await self._generate_fn(query, self._config.extra, **kwargs)
        latency_ms = (time.perf_counter() - start) * 1000

        if not isinstance(result, dict):
            raise RuntimeError(f"Plugin provider generate() must return a mapping, got {type(result).__name__}")
        if "output" not in result:
            raise RuntimeError("Plugin provider generate() must return an 'output' field")

        usage = result.get("token_usage")
        token_usage = None
        if isinstance(usage, dict):
            token_usage = TokenUsage(
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=int(usage.get("completion_tokens", 0)),
                total_tokens=int(usage.get("total_tokens", 0)),
            )

        status_value = result.get("status", ProviderStatus.SUCCESS.value)
        status = ProviderStatus(status_value)

        return ProviderResponse(
            output=str(result["output"]),
            latency_ms=float(result.get("latency_ms", latency_ms)),
            status=status,
            error=result.get("error"),
            token_usage=token_usage,
            cost=result.get("cost"),
            model_name=result.get("model_name", self._name),
            request_id=result.get("request_id"),
        )
