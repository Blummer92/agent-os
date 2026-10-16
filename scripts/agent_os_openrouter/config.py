"""Opt-in configuration for the OpenRouter bug-investigation pilot (#3637).

The pilot is disabled by default. Enabling requires the explicit
``OPENROUTER_PILOT_ENABLED=true`` environment switch; the API key itself is
never stored on this object -- only the *name* of the environment variable
that holds it. The key is read from ``os.environ`` at call time, and never
appears in logs, errors, or ``repr`` output.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

PILOT_ENABLED_ENV_VAR = "OPENROUTER_PILOT_ENABLED"
API_KEY_ENV_VAR = "OPENROUTER_API_KEY"
MODEL_A_ENV_VAR = "OPENROUTER_MODEL_A"
MODEL_B_ENV_VAR = "OPENROUTER_MODEL_B"
LIVE_BENCHMARK_ENV_VAR = "OPENROUTER_BENCHMARK_LIVE_APPROVED"

DEFAULT_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

# Example model identities in OpenRouter ``vendor/model`` form. These are
# defaults only: override via OPENROUTER_MODEL_A / OPENROUTER_MODEL_B.
# Model availability is verified at enablement time, not assumed here.
DEFAULT_MODEL_A = "anthropic/claude-sonnet-4.5"
DEFAULT_MODEL_B = "openai/gpt-5"


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _non_negative_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{name} must be a non-negative number")
    return float(value)


@dataclass(frozen=True, slots=True)
class OpenRouterConfig:
    """Frozen pilot configuration. Disabled unless explicitly opted in."""

    enabled: bool = False
    api_key_env_var: str = API_KEY_ENV_VAR
    model_a: str = DEFAULT_MODEL_A
    model_b: str = DEFAULT_MODEL_B
    max_tokens_per_request: int = 4096
    max_requests_per_investigation: int = 8
    max_total_tokens: int = 120_000
    timeout_seconds: float = 60.0
    max_retries: int = 3
    retry_backoff_seconds: float = 2.0
    endpoint: str = DEFAULT_ENDPOINT

    def __post_init__(self) -> None:
        self.validate()

    @classmethod
    def from_env(cls) -> "OpenRouterConfig":
        """Build config from the environment.

        The pilot is enabled ONLY when ``OPENROUTER_PILOT_ENABLED`` is exactly
        ``"true"``; any other value (including unset) leaves it disabled,
        regardless of the remaining variables.
        """
        env = os.environ
        enabled = env.get(PILOT_ENABLED_ENV_VAR) == "true"

        def _int(name: str, default: int) -> int:
            raw = env.get(name)
            if raw is None or raw == "":
                return default
            try:
                return int(raw)
            except ValueError:
                raise ValueError(f"{name} must be an integer") from None

        def _float(name: str, default: float) -> float:
            raw = env.get(name)
            if raw is None or raw == "":
                return default
            try:
                return float(raw)
            except ValueError:
                raise ValueError(f"{name} must be a number") from None

        return cls(
            enabled=enabled,
            api_key_env_var=env.get("OPENROUTER_API_KEY_ENV_VAR", API_KEY_ENV_VAR),
            model_a=env.get(MODEL_A_ENV_VAR, DEFAULT_MODEL_A),
            model_b=env.get(MODEL_B_ENV_VAR, DEFAULT_MODEL_B),
            max_tokens_per_request=_int("OPENROUTER_MAX_TOKENS_PER_REQUEST", 4096),
            max_requests_per_investigation=_int("OPENROUTER_MAX_REQUESTS_PER_INVESTIGATION", 8),
            max_total_tokens=_int("OPENROUTER_MAX_TOTAL_TOKENS", 120_000),
            timeout_seconds=_float("OPENROUTER_TIMEOUT_SECONDS", 60.0),
            max_retries=_int("OPENROUTER_MAX_RETRIES", 3),
            retry_backoff_seconds=_float("OPENROUTER_RETRY_BACKOFF_SECONDS", 2.0),
            endpoint=env.get("OPENROUTER_ENDPOINT", DEFAULT_ENDPOINT),
        )

    def validate(self) -> None:
        """Raise ValueError on any nonsensical setting. Fail closed at build time."""
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled must be a boolean")
        if not isinstance(self.api_key_env_var, str) or not self.api_key_env_var.strip():
            raise ValueError("api_key_env_var must be a non-empty environment variable name")
        for name in ("model_a", "model_b"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty model identity")
            if "/" not in value:
                raise ValueError(f"{name} must use OpenRouter vendor/model form")
        _positive_int(self.max_tokens_per_request, "max_tokens_per_request")
        _positive_int(self.max_requests_per_investigation, "max_requests_per_investigation")
        _positive_int(self.max_total_tokens, "max_total_tokens")
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float)) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be a positive number")
        if isinstance(self.max_retries, bool) or not isinstance(self.max_retries, int) or self.max_retries < 0:
            raise ValueError("max_retries must be a non-negative integer")
        _non_negative_number(self.retry_backoff_seconds, "retry_backoff_seconds")
        if not isinstance(self.endpoint, str) or not self.endpoint.startswith("https://"):
            raise ValueError("endpoint must be an https URL")

    def is_configured(self) -> bool:
        """True only when the pilot is enabled AND a key is present.

        The key value is read fresh from the environment on every call and is
        never stored, logged, or embedded in this object.
        """
        if not self.enabled:
            return False
        value = os.environ.get(self.api_key_env_var)
        return bool(value and value.strip())
