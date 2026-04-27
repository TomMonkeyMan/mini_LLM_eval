"""Tests for provider implementations."""

from __future__ import annotations

import json
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
