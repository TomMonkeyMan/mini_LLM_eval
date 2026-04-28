"""Tests for provider implementations."""

from __future__ import annotations

import json
import logging
import random

import httpx
import pytest

from mini_llm_eval.core.config import ProviderConfig
from mini_llm_eval.core.exceptions import ProviderInitError
from mini_llm_eval.models.schemas import ProviderStatus
from mini_llm_eval.providers.factory import create_provider
from mini_llm_eval.providers.mock import MockProvider
from mini_llm_eval.providers.openai_compatible import OpenAICompatibleProvider
from mini_llm_eval.providers.plugin import PluginProvider
from mini_llm_eval.providers.rate_limited import ProviderRateLimiter, RateLimitedProvider
from mini_llm_eval.providers.retry import with_retry


@pytest.mark.asyncio
async def test_mock_provider_returns_mapping_response(tmp_path) -> None:
    mapping_path = tmp_path / "mock.json"
    mapping_path.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
    provider = MockProvider(
        "mock-default",
        ProviderConfig(type="mock", mapping_file=str(mapping_path)),
        rng=random.Random(0),
    )

    response = await provider.generate("hello")

    assert response.status is ProviderStatus.SUCCESS
    assert response.output == "world"


@pytest.mark.asyncio
async def test_mock_provider_fallback_can_use_expected_answer(tmp_path) -> None:
    mapping_path = tmp_path / "mock.json"
    mapping_path.write_text("{}", encoding="utf-8")
    provider = MockProvider(
        "mock-default",
        ProviderConfig.from_mapping(
            {
                "type": "mock",
                "mapping_file": str(mapping_path),
                "fallback": {
                    "enabled": True,
                    "success_rate": 1.0,
                    "default_response": "fallback",
                },
            }
        ),
        rng=random.Random(0),
    )

    response = await provider.generate("missing", expected_answer="expected-value")

    assert response.output == "expected-value"
    assert response.status is ProviderStatus.SUCCESS


def test_factory_creates_known_provider_types() -> None:
    provider = create_provider("mock-default", ProviderConfig(type="mock"))

    assert provider.name == "mock-default"


def test_factory_wraps_provider_when_rate_limit_is_configured() -> None:
    provider = create_provider(
        "mock-default",
        ProviderConfig(
            type="mock",
            provider_concurrency_limit=2,
            requests_per_second=1.0,
        ),
    )

    assert isinstance(provider, RateLimitedProvider)


@pytest.mark.asyncio
async def test_rate_limited_provider_enforces_provider_concurrency_limit() -> None:
    import asyncio

    class TrackingProvider(MockProvider):
        def __init__(self) -> None:
            super().__init__("mock-default", ProviderConfig(type="mock"), rng=random.Random(0))
            self.in_flight = 0
            self.max_in_flight = 0

        async def generate(self, query: str, **kwargs):
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            try:
                await asyncio.sleep(0.01)
                return await super().generate(query, **kwargs)
            finally:
                self.in_flight -= 1

    provider = TrackingProvider()
    wrapped = RateLimitedProvider(provider, provider_concurrency_limit=2)

    await asyncio.gather(*(wrapped.generate(f"q-{idx}") for idx in range(6)))

    assert provider.max_in_flight == 2


@pytest.mark.asyncio
async def test_provider_rate_limiter_spaces_requests_without_real_sleep() -> None:
    class FakeClock:
        def __init__(self) -> None:
            self.now = 0.0
            self.sleeps: list[float] = []

        def monotonic(self) -> float:
            return self.now

        async def sleep(self, seconds: float) -> None:
            self.sleeps.append(seconds)
            self.now += seconds

    fake_clock = FakeClock()
    limiter = ProviderRateLimiter(
        2.0,
        monotonic=fake_clock.monotonic,
        sleeper=fake_clock.sleep,
    )

    first_wait = await limiter.acquire()
    second_wait = await limiter.acquire()
    third_wait = await limiter.acquire()

    assert first_wait == 0.0
    assert second_wait == 0.5
    assert third_wait == 0.5
    assert fake_clock.sleeps == [0.5, 0.5]


@pytest.mark.asyncio
async def test_plugin_provider_loads_async_generate_function(tmp_path) -> None:
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    plugin_path = plugins_dir / "demo_plugin.py"
    plugin_path.write_text(
        "\n".join(
            [
                "async def generate(query, config, **kwargs):",
                "    return {",
                '        "output": f"{config[\'prefix\']}:{query}",',
                '        "request_id": "plugin-req",',
                "    }",
            ]
        ),
        encoding="utf-8",
    )

    provider = PluginProvider(
        "custom-demo",
        ProviderConfig.from_mapping(
            {
                "type": "plugin",
                "plugin": "demo_plugin",
                "plugins_dir": str(plugins_dir),
                "prefix": "ok",
            }
        ),
    )

    response = await provider.generate("hello")

    assert response.status is ProviderStatus.SUCCESS
    assert response.output == "ok:hello"
    assert response.request_id == "plugin-req"


def test_plugin_provider_rejects_non_async_generate(tmp_path) -> None:
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    plugin_path = plugins_dir / "bad_plugin.py"
    plugin_path.write_text(
        "\n".join(
            [
                "def generate(query, config, **kwargs):",
                '    return {"output": "bad"}',
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ProviderInitError):
        PluginProvider(
            "custom-demo",
            ProviderConfig.from_mapping(
                {
                    "type": "plugin",
                    "plugin": "bad_plugin",
                    "plugins_dir": str(plugins_dir),
                }
            ),
        )


@pytest.mark.asyncio
async def test_plugin_provider_rejects_missing_output_field(tmp_path) -> None:
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    plugin_path = plugins_dir / "bad_output.py"
    plugin_path.write_text(
        "\n".join(
            [
                "async def generate(query, config, **kwargs):",
                '    return {"status": "success"}',
            ]
        ),
        encoding="utf-8",
    )

    provider = PluginProvider(
        "custom-demo",
        ProviderConfig.from_mapping(
            {
                "type": "plugin",
                "plugin": "bad_output",
                "plugins_dir": str(plugins_dir),
            }
        ),
    )

    with pytest.raises(RuntimeError, match="must return an 'output' field"):
        await provider.generate("hello")


@pytest.mark.asyncio
async def test_openai_provider_parses_success_response(monkeypatch) -> None:
    monkeypatch.setenv("TEST_API_KEY", "secret")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer secret"
        return httpx.Response(
            200,
            json={
                "model": "demo-model",
                "choices": [{"message": {"content": "hello back"}}],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 2,
                    "total_tokens": 3,
                },
            },
            headers={"x-request-id": "req-123"},
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://example.test",
    )
    provider = OpenAICompatibleProvider(
        "remote",
        ProviderConfig(
            type="openai_compatible",
            base_url="https://example.test",
            model="demo-model",
            api_key_env="TEST_API_KEY",
        ),
        client=client,
    )

    response = await provider.generate("hello")
    await provider.close()

    assert response.status is ProviderStatus.SUCCESS
    assert response.output == "hello back"
    assert response.token_usage.total_tokens == 3
    assert response.request_id == "req-123"


@pytest.mark.asyncio
async def test_openai_provider_returns_error_response_for_4xx() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "bad request"}})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://example.test",
    )
    provider = OpenAICompatibleProvider(
        "remote",
        ProviderConfig(
            type="openai_compatible",
            base_url="https://example.test",
            model="demo-model",
        ),
        client=client,
    )

    response = await provider.generate("hello")
    await provider.close()

    assert response.status is ProviderStatus.ERROR
    assert response.error == "bad_request"


@pytest.mark.asyncio
async def test_openai_provider_logs_structured_http_error_details(caplog) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"error": {"message": "forbidden"}},
            headers={"x-request-id": "req-403"},
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://example.test",
    )
    provider = OpenAICompatibleProvider(
        "remote",
        ProviderConfig(
            type="openai_compatible",
            base_url="https://example.test",
            model="demo-model",
            max_retries=0,
        ),
        client=client,
    )

    with caplog.at_level(logging.WARNING):
        response = await provider.generate("hello")
    await provider.close()

    assert response.status is ProviderStatus.ERROR
    warning_record = next(record for record in caplog.records if record.event == "provider_error")
    assert warning_record.error_code == "bad_request"
    assert warning_record.http_status == 403
    assert warning_record.request_id == "req-403"
    assert warning_record.response_preview == '{"error":{"message":"forbidden"}}'


@pytest.mark.asyncio
async def test_openai_provider_logs_truncated_error_response_preview(caplog) -> None:
    long_message = "x" * 600

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            json={"error": {"message": long_message}},
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://example.test",
    )
    provider = OpenAICompatibleProvider(
        "remote",
        ProviderConfig(
            type="openai_compatible",
            base_url="https://example.test",
            model="demo-model",
            max_retries=0,
        ),
        client=client,
    )

    with caplog.at_level(logging.WARNING):
        response = await provider.generate("hello")
    await provider.close()

    assert response.status is ProviderStatus.ERROR
    warning_record = next(record for record in caplog.records if record.event == "provider_error")
    assert warning_record.error_code == "server_error"
    assert warning_record.http_status == 500
    assert warning_record.response_preview.endswith("...")
    assert len(warning_record.response_preview) == 503


@pytest.mark.asyncio
async def test_openai_provider_returns_timeout_response_for_timeout() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://example.test",
    )
    provider = OpenAICompatibleProvider(
        "remote",
        ProviderConfig(
            type="openai_compatible",
            base_url="https://example.test",
            model="demo-model",
        ),
        client=client,
    )

    response = await provider.generate("hello")
    await provider.close()

    assert response.status is ProviderStatus.TIMEOUT
    assert response.error == "Provider request timed out"


@pytest.mark.asyncio
async def test_openai_provider_returns_error_after_retry_budget_exhausted() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "server error"}})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://example.test",
    )
    provider = OpenAICompatibleProvider(
        "remote",
        ProviderConfig(
            type="openai_compatible",
            base_url="https://example.test",
            model="demo-model",
            max_retries=0,
        ),
        client=client,
    )

    response = await provider.generate("hello")
    await provider.close()

    assert response.status is ProviderStatus.ERROR
    assert response.error == "server_error"


def test_openai_provider_requires_base_url_and_model() -> None:
    with pytest.raises(ProviderInitError):
        OpenAICompatibleProvider("remote", ProviderConfig(type="openai_compatible"))


@pytest.mark.asyncio
async def test_with_retry_retries_retryable_provider_errors() -> None:
    attempts = {"count": 0}

    async def flaky() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            from mini_llm_eval.core.exceptions import ProviderError

            raise ProviderError("server_error")
        return "ok"

    result = await with_retry(flaky, max_retries=3, retry_delays=(0, 0, 0))

    assert result == "ok"
    assert attempts["count"] == 3
