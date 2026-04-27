"""OpenAI-compatible provider implementation."""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from mini_llm_eval.core.config import ProviderConfig
from mini_llm_eval.core.exceptions import ProviderError, ProviderInitError, ProviderTimeoutError
from mini_llm_eval.core.logging import get_logger
from mini_llm_eval.models.schemas import ProviderResponse, ProviderStatus, TokenUsage
from mini_llm_eval.providers.base import BaseProvider
from mini_llm_eval.providers.retry import with_retry

logger = get_logger(__name__)
MAX_RESPONSE_PREVIEW_CHARS = 500


class OpenAICompatibleProvider(BaseProvider):
    """Async client for OpenAI-compatible chat completion APIs."""

    def __init__(
        self,
        name: str,
        config: ProviderConfig,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not config.base_url:
            raise ProviderInitError("openai_compatible provider requires base_url")
        if not config.model:
            raise ProviderInitError("openai_compatible provider requires model")

        self._name = name
        self._config = config
        self._owns_client = client is None
        self._client = client or self._build_client()
        self._client.headers.update(self._build_headers())
        logger.info(
            "Initialized OpenAI-compatible provider",
            extra={
                "event": "provider_initialized",
                "provider_name": self._name,
                "provider_type": "openai_compatible",
                "base_url": self._config.base_url,
                "model_name": self._config.model,
            },
        )

    @property
    def name(self) -> str:
        return self._name

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._config.api_key_env:
            api_key = os.getenv(self._config.api_key_env)
            if not api_key:
                raise ProviderInitError(
                    f"Missing API key environment variable: {self._config.api_key_env}"
                )
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def _build_client(self) -> httpx.AsyncClient:
        timeout_ms = self._config.timeout_ms or 30000

        return httpx.AsyncClient(
            base_url=self._config.base_url.rstrip("/"),
            timeout=timeout_ms / 1000,
        )

    async def generate(self, query: str, **kwargs) -> ProviderResponse:
        messages = kwargs.get("messages") or [{"role": "user", "content": query}]
        max_retries = self._config.max_retries or 3

        async def send_request() -> ProviderResponse:
            start = time.perf_counter()
            try:
                response = await self._client.post(
                    "/chat/completions",
                    json={
                        "model": self._config.model,
                        "messages": messages,
                        **kwargs.get("request_overrides", {}),
                    },
                )
            except httpx.TimeoutException as exc:
                raise ProviderTimeoutError("timeout") from exc
            except httpx.ConnectError as exc:
                raise ProviderError("connection_error") from exc
            except httpx.HTTPError as exc:
                raise ProviderError("connection_error") from exc

            latency_ms = (time.perf_counter() - start) * 1000
            return self._parse_response(response, latency_ms)

        try:
            return await with_retry(
                send_request,
                max_retries=max_retries,
                provider_name=self._name,
            )
        except ProviderTimeoutError:
            logger.warning(
                "Provider request timed out",
                extra={
                    "event": "provider_timeout",
                    "provider_name": self._name,
                    "model_name": self._config.model,
                },
            )
            return ProviderResponse(
                output="",
                latency_ms=0,
                status=ProviderStatus.TIMEOUT,
                error="Provider request timed out",
                model_name=self._config.model,
            )
        except ProviderError as exc:
            logger.warning(
                "Provider request failed",
                extra={
                    "event": "provider_error",
                    "provider_name": self._name,
                    "model_name": self._config.model,
                    "error_code": exc.code,
                    "http_status": exc.http_status,
                    "request_id": exc.request_id,
                    "response_preview": exc.response_preview,
                },
            )
            return ProviderResponse(
                output="",
                latency_ms=0,
                status=ProviderStatus.ERROR,
                error=exc.code,
                model_name=self._config.model,
            )

    def _parse_response(self, response: httpx.Response, latency_ms: float) -> ProviderResponse:
        request_id = response.headers.get("x-request-id")
        if response.status_code == 429:
            raise ProviderError(
                "rate_limit",
                http_status=response.status_code,
                request_id=request_id,
                response_preview=self._response_preview(response),
            )
        if 500 <= response.status_code <= 599:
            raise ProviderError(
                "server_error",
                http_status=response.status_code,
                request_id=request_id,
                response_preview=self._response_preview(response),
            )
        if response.status_code >= 400:
            raise ProviderError(
                "bad_request",
                http_status=response.status_code,
                request_id=request_id,
                response_preview=self._response_preview(response),
            )

        try:
            payload = response.json()
            message = payload["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                "invalid_response",
                http_status=response.status_code,
                request_id=request_id,
                response_preview=self._response_preview(response),
            ) from exc

        usage_payload = payload.get("usage")
        token_usage = None
        if isinstance(usage_payload, dict):
            token_usage = TokenUsage(
                prompt_tokens=int(usage_payload.get("prompt_tokens", 0)),
                completion_tokens=int(usage_payload.get("completion_tokens", 0)),
                total_tokens=int(usage_payload.get("total_tokens", 0)),
            )

        return ProviderResponse(
            output=str(message),
            latency_ms=latency_ms,
            status=ProviderStatus.SUCCESS,
            error=None,
            token_usage=token_usage,
            model_name=payload.get("model", self._config.model),
            request_id=request_id,
        )

    @staticmethod
    def _response_preview(response: httpx.Response) -> str | None:
        body = response.text.strip()
        if not body:
            return None
        if len(body) <= MAX_RESPONSE_PREVIEW_CHARS:
            return body
        return f"{body[:MAX_RESPONSE_PREVIEW_CHARS]}..."

    async def health_check(self) -> bool:
        try:
            response = await self._client.get("/models")
            return response.status_code < 500
        except httpx.HTTPError:
            return False

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
