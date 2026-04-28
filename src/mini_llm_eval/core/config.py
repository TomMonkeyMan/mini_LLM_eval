"""Configuration loading helpers."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from mini_llm_eval.core.exceptions import ConfigError

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")
_DEFAULT_CONFIG_PATHS = (
    Path("config.yaml"),
    Path.home() / ".mini_llm_eval" / "config.yaml",
)
_DEFAULT_PROVIDER_PATHS = (
    Path("providers.yaml"),
    Path.home() / ".mini_llm_eval" / "providers.yaml",
)

_config_cache: Config | None = None
_providers_cache: dict[str, ProviderConfig] | None = None


class DefaultsConfig(BaseModel):
    """Project-level default settings."""

    evaluators: list[str] = Field(default_factory=lambda: ["contains"])


class Config(BaseModel):
    """Top-level project configuration."""

    timeout_ms: int = 30000
    max_retries: int = 3
    concurrency: int = 4
    log_level: str = "INFO"
    output_dir: str = "./outputs"
    evaluators_package: str = "mini_llm_eval.evaluators"
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)


class ProviderConfig(BaseModel):
    """Per-provider configuration."""

    type: str
    plugin: str | None = None
    plugins_dir: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_key_env: str | None = None
    timeout_ms: int | None = None
    max_retries: int | None = None
    provider_concurrency_limit: int | None = None
    requests_per_second: float | None = None
    mode: str | None = None
    mapping_file: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "ProviderConfig":
        known_fields = set(cls.model_fields)
        data = dict(payload)
        extra = {key: value for key, value in data.items() if key not in known_fields}
        data["extra"] = extra
        return cls.model_validate(data)


def _resolve_path(explicit_path: str | None, candidates: tuple[Path, ...]) -> Path | None:
    if explicit_path is not None:
        path = Path(explicit_path).expanduser()
        if not path.exists():
            raise ConfigError(f"Configuration file not found: {path}")
        return path

    for candidate in candidates:
        path = candidate.expanduser()
        if path.exists():
            return path
    return None


def _load_yaml_file(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            content = yaml.safe_load(handle) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Failed to read configuration file {path}: {exc}") from exc

    if not isinstance(content, dict):
        raise ConfigError(f"Configuration file must contain a mapping: {path}")
    return content


def _expand_env_vars(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _expand_env_vars(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env_vars(item) for item in value]
    if not isinstance(value, str):
        return value

    def replace(match: re.Match[str]) -> str:
        env_name = match.group(1)
        if env_name not in os.environ:
            raise ConfigError(f"Environment variable {env_name} is not set")
        return os.environ[env_name]

    return _ENV_PATTERN.sub(replace, value)


def load_config(config_path: str | None = None) -> Config:
    """Load project configuration from YAML if available."""

    path = _resolve_path(config_path, _DEFAULT_CONFIG_PATHS)
    if path is None:
        return Config()

    raw = _expand_env_vars(_load_yaml_file(path))
    try:
        return Config.model_validate(raw)
    except Exception as exc:  # pydantic validation error
        raise ConfigError(f"Invalid project configuration in {path}: {exc}") from exc


def load_providers(providers_path: str | None = None) -> dict[str, ProviderConfig]:
    """Load provider configuration mapping from YAML if available."""

    path = _resolve_path(providers_path, _DEFAULT_PROVIDER_PATHS)
    if path is None:
        return {}

    raw = _expand_env_vars(_load_yaml_file(path))
    providers: dict[str, ProviderConfig] = {}
    try:
        for name, payload in raw.items():
            if not isinstance(payload, dict):
                raise ConfigError(f"Provider entry '{name}' must be a mapping")
            providers[name] = ProviderConfig.from_mapping(payload)
    except ConfigError:
        raise
    except Exception as exc:
        raise ConfigError(f"Invalid providers configuration in {path}: {exc}") from exc
    return providers


def set_runtime_config(
    config: Config | None = None,
    providers: dict[str, ProviderConfig] | None = None,
) -> None:
    """Set cached runtime configuration, primarily for CLI and tests."""

    global _config_cache, _providers_cache
    _config_cache = config
    _providers_cache = providers


def get_config(config_path: str | None = None) -> Config:
    """Return cached project configuration or load it on demand."""

    global _config_cache
    if _config_cache is None:
        _config_cache = load_config(config_path=config_path)
    return _config_cache


def get_providers(providers_path: str | None = None) -> dict[str, ProviderConfig]:
    """Return cached provider configuration or load it on demand."""

    global _providers_cache
    if _providers_cache is None:
        _providers_cache = load_providers(providers_path=providers_path)
    return _providers_cache


def reset_runtime_config() -> None:
    """Clear cached configuration state."""

    global _config_cache, _providers_cache
    _config_cache = None
    _providers_cache = None
