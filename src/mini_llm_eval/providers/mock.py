"""Mock provider implementation."""

from __future__ import annotations

import asyncio
import json
import random
import time
from pathlib import Path
from typing import Any

from mini_llm_eval.core.config import ProviderConfig
from mini_llm_eval.core.exceptions import ProviderInitError
from mini_llm_eval.models.schemas import ProviderResponse, ProviderStatus
from mini_llm_eval.providers.base import BaseProvider


class MockProvider(BaseProvider):
    """Simple mock provider for offline development and tests."""

    def __init__(
        self,
        name: str,
        config: ProviderConfig,
        rng: random.Random | None = None,
    ) -> None:
        self._name = name
        self._config = config
        self._rng = rng or random.Random()
        self._mapping = self._load_mapping()

    @property
    def name(self) -> str:
        return self._name

    def _load_mapping(self) -> dict[str, str]:
        mapping_file = self._config.mapping_file
        if not mapping_file:
            return {}

        path = Path(mapping_file).expanduser()
        if not path.exists():
            raise ProviderInitError(f"Mock provider mapping file not found: {path}")

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ProviderInitError(f"Invalid mock mapping JSON: {exc}") from exc
        except OSError as exc:
            raise ProviderInitError(f"Failed to read mock mapping file {path}: {exc}") from exc

        if isinstance(payload, dict):
            return {str(key): str(value) for key, value in payload.items()}
        if isinstance(payload, list):
            result: dict[str, str] = {}
            for item in payload:
                if not isinstance(item, dict) or "query" not in item or "output" not in item:
                    raise ProviderInitError("Mock mapping list items must contain 'query' and 'output'")
                result[str(item["query"])] = str(item["output"])
            return result
        raise ProviderInitError("Mock mapping file must contain a JSON object or list")

    def _fallback_config(self) -> dict[str, Any]:
        fallback = self._config.extra.get("fallback", {})
        return fallback if isinstance(fallback, dict) else {}

    def _latency_bounds(self) -> tuple[int, int]:
        latency = self._config.extra.get("latency", {})
        if not isinstance(latency, dict):
            return (0, 0)
        min_ms = int(latency.get("min_ms", 0))
        max_ms = int(latency.get("max_ms", min_ms))
        return (min_ms, max(min_ms, max_ms))

    async def generate(self, query: str, **kwargs) -> ProviderResponse:
        start = time.perf_counter()
        min_ms, max_ms = self._latency_bounds()
        if max_ms > 0:
            await asyncio.sleep(self._rng.uniform(min_ms, max_ms) / 1000)

        if query in self._mapping:
            output = self._mapping[query]
            status = ProviderStatus.SUCCESS
            error = None
        else:
            fallback = self._fallback_config()
            if fallback.get("enabled", True):
                success_rate = float(fallback.get("success_rate", 1.0))
                default_response = str(fallback.get("default_response", query))
                expected_answer = kwargs.get("expected_answer")
                if expected_answer is not None and self._rng.random() <= success_rate:
                    output = str(expected_answer)
                else:
                    output = default_response
                status = ProviderStatus.SUCCESS
                error = None
            else:
                output = ""
                status = ProviderStatus.ERROR
                error = f"No mock response configured for query: {query}"

        latency_ms = (time.perf_counter() - start) * 1000
        return ProviderResponse(
            output=output,
            latency_ms=latency_ms,
            status=status,
            error=error,
            model_name=self._name,
        )
