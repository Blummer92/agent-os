"""Config tests: disabled by default, explicit opt-in, budget validation."""

from __future__ import annotations

import pytest

from scripts.agent_os_openrouter.config import (
    API_KEY_ENV_VAR,
    PILOT_ENABLED_ENV_VAR,
    OpenRouterConfig,
)

from ._helpers import TEST_API_KEY


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(PILOT_ENABLED_ENV_VAR, raising=False)
    monkeypatch.delenv(API_KEY_ENV_VAR, raising=False)


def test_disabled_by_default():
    config = OpenRouterConfig()
    assert config.enabled is False
    assert config.is_configured() is False


def test_from_env_enables_only_on_exact_true(monkeypatch):
    for raw in ("1", "TRUE", "True", "yes", ""):
        monkeypatch.setenv(PILOT_ENABLED_ENV_VAR, raw)
        monkeypatch.setenv(API_KEY_ENV_VAR, TEST_API_KEY)
        config = OpenRouterConfig.from_env()
        assert config.enabled is False, raw
        assert config.is_configured() is False


def test_from_env_enables_on_exact_true_with_key(monkeypatch):
    monkeypatch.setenv(PILOT_ENABLED_ENV_VAR, "true")
    monkeypatch.setenv(API_KEY_ENV_VAR, TEST_API_KEY)
    config = OpenRouterConfig.from_env()
    assert config.enabled is True
    assert config.is_configured() is True


def test_enabled_without_key_is_not_configured(monkeypatch):
    monkeypatch.setenv(PILOT_ENABLED_ENV_VAR, "true")
    config = OpenRouterConfig.from_env()
    assert config.enabled is True
    assert config.is_configured() is False


def test_blank_key_is_not_configured(monkeypatch):
    monkeypatch.setenv(PILOT_ENABLED_ENV_VAR, "true")
    monkeypatch.setenv(API_KEY_ENV_VAR, "   ")
    assert OpenRouterConfig.from_env().is_configured() is False


def test_key_never_in_repr(monkeypatch):
    monkeypatch.setenv(PILOT_ENABLED_ENV_VAR, "true")
    monkeypatch.setenv(API_KEY_ENV_VAR, TEST_API_KEY)
    config = OpenRouterConfig.from_env()
    assert TEST_API_KEY not in repr(config)


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_tokens_per_request", 0),
        ("max_tokens_per_request", -10),
        ("max_requests_per_investigation", 0),
        ("max_total_tokens", -1),
        ("timeout_seconds", 0),
        ("timeout_seconds", -2.5),
        ("max_retries", -1),
        ("retry_backoff_seconds", -0.5),
        ("endpoint", "http://insecure.example/v1"),
        ("endpoint", ""),
        ("model_a", ""),
        ("model_b", "no-vendor-separator"),
        ("api_key_env_var", "   "),
    ],
)
def test_invalid_budgets_raise_value_error(field, value):
    with pytest.raises(ValueError):
        OpenRouterConfig(enabled=True, **{field: value})


def test_from_env_rejects_invalid_budget_value(monkeypatch):
    monkeypatch.setenv(PILOT_ENABLED_ENV_VAR, "true")
    monkeypatch.setenv("OPENROUTER_MAX_TOKENS_PER_REQUEST", "-5")
    with pytest.raises(ValueError):
        OpenRouterConfig.from_env()


def test_model_overrides_from_env(monkeypatch):
    monkeypatch.setenv(PILOT_ENABLED_ENV_VAR, "true")
    monkeypatch.setenv("OPENROUTER_MODEL_A", "vendor-a/custom-a")
    monkeypatch.setenv("OPENROUTER_MODEL_B", "vendor-b/custom-b")
    config = OpenRouterConfig.from_env()
    assert config.model_a == "vendor-a/custom-a"
    assert config.model_b == "vendor-b/custom-b"
