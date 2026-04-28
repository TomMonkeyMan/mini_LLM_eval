"""Tests for configuration loading."""

from __future__ import annotations

import textwrap

import pytest

from mini_llm_eval.core.config import (
    Config,
    get_config,
    get_providers,
    load_config,
    load_providers,
    reset_runtime_config,
    set_runtime_config,
)
from mini_llm_eval.core.exceptions import ConfigError


def test_load_config_returns_defaults_when_no_default_file_exists(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    config = load_config()

    assert isinstance(config, Config)
    assert config.timeout_ms == 30000
    assert config.log_level == "INFO"
    assert config.defaults.evaluators == ["contains"]


def test_load_config_expands_environment_variables(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            timeout_ms: 1234
            output_dir: ${TEST_OUTPUT_DIR}
            defaults:
              evaluators: [exact_match]
            """
        ).strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("TEST_OUTPUT_DIR", "./tmp-output")

    config = load_config(config_path=str(config_path))

    assert config.timeout_ms == 1234
    assert config.output_dir == "./tmp-output"
    assert config.log_level == "INFO"
    assert config.defaults.evaluators == ["exact_match"]


def test_load_providers_preserves_extra_fields(tmp_path, monkeypatch) -> None:
    providers_path = tmp_path / "providers.yaml"
    providers_path.write_text(
        textwrap.dedent(
            """
            remote-model:
              type: openai_compatible
              base_url: ${MODEL_BASE_URL}
              model: ft-model
              api_key_env: MODEL_API_KEY
              custom_header: x-tenant-id
            """
        ).strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("MODEL_BASE_URL", "https://example.test/v1")

    providers = load_providers(providers_path=str(providers_path))

    provider = providers["remote-model"]
    assert provider.base_url == "https://example.test/v1"
    assert provider.extra["custom_header"] == "x-tenant-id"


def test_load_providers_parses_rate_limit_fields(tmp_path) -> None:
    providers_path = tmp_path / "providers.yaml"
    providers_path.write_text(
        textwrap.dedent(
            """
            remote-model:
              type: openai_compatible
              base_url: https://example.test/v1
              model: ft-model
              provider_concurrency_limit: 2
              requests_per_second: 1.5
            """
        ).strip(),
        encoding="utf-8",
    )

    providers = load_providers(providers_path=str(providers_path))

    provider = providers["remote-model"]
    assert provider.provider_concurrency_limit == 2
    assert provider.requests_per_second == 1.5


def test_missing_environment_variable_raises_config_error(tmp_path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("output_dir: ${MISSING_ENV}\n", encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(config_path=str(config_path))


def test_runtime_config_cache_round_trip() -> None:
    reset_runtime_config()
    config = Config(concurrency=9)
    set_runtime_config(config=config, providers={})

    assert get_config().concurrency == 9
    assert get_providers() == {}

    reset_runtime_config()
