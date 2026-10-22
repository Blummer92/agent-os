"""OpenRouter implementation of the pr-remediation ``ProposalAdapter`` seam (#3637).

This is the first in-repo network-calling provider adapter. It is
structurally compatible with the ``ProposalAdapter`` protocol (a single
``propose(request_payload)`` method) and reuses the kernel's strict verifier,
reason codes, and fail-closed outcomes without modifying any kernel file.

Security invariants:
- The API key is read from ``os.environ`` at call time only. It is never
  stored on the config or adapter, never logged, and never interpolated into
  error messages, stats, or evidence payloads.
- The request payload carries structured investigation metadata (paths,
  fingerprints, schema keys) only -- never file contents. A defense-in-depth
  bound (mirroring the kernel's ``MAX_TEXT_BYTES``) rejects any payload string
  that exceeds it before any network call.
- Provider and model identities and the request fingerprint are overwritten
  deterministically by the adapter, so model output cannot forge bindings.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable

from .config import OpenRouterConfig
from .pricing import (
    FreeModelPricingGate,
    GenerationFetcher,
    OpenRouterPricingGateError,
)

PROVIDER_IDENTITY = "openrouter"

# Defense-in-depth payload bound, mirroring the kernel's MAX_TEXT_BYTES
# (4 KiB). The kernel already bounds ProposalRequest text; the adapter
# re-checks so a caller bypassing the kernel cannot leak file-sized content.
MAX_PAYLOAD_TEXT_BYTES = 4 * 1024

# Retryable: transient server failures and rate limiting only. Other 4xx
# responses are terminal and fail closed without retry.
_RETRYABLE_HTTP_STATUS = frozenset({408, 425, 429}) | frozenset(range(500, 600))

SYSTEM_PROMPT = (
    "You are a bug-investigation assistant for the Agent OS repository. "
    "Return ONLY a single JSON object -- no prose, no markdown fences -- matching "
    "the exact proposal schema below. Every listed key is required; no additional "
    "keys are permitted. All authority fields MUST be false. proposed_files must "
    "stay within the request's allowed_paths and outside forbidden_paths. "
    "steps[].action must be one of: inspect, edit, validate, document, handoff. "
    "Do not include shell-like content. Bind request_fingerprint, evidence_refs, "
    "non_goals, validations, prohibited_changes, and blockers exactly to the request. "
    "Required keys: schema_version, plan_type, request_fingerprint, provider_identity, "
    "model_identity, evidence_refs, non_goals, steps, proposed_files, prohibited_changes, "
    "validations, blockers, rollback_concept, executor_route_requirements, "
    "insufficiency_reason, uncertainty, expiry_condition, invalidation_conditions, "
    "execution_authorized, source_edit_authorized, github_write_authorized, "
    "validation_authorized, ready_for_review_authorized, merge_authorized, "
    "issue_closure_authorized, workflow_authorized, credential_authorized, "
    "production_authorized, external_write_authorized, side_effects_performed. "
    'Use schema_version "1.0".'
)

# Injectable transport: (request_body, headers, timeout_seconds) -> parsed
# JSON response dict. The default uses urllib with the configured timeout.
Transport = Callable[[dict[str, Any], dict[str, str], float], dict[str, Any]]


class OpenRouterMalformedResponse(ValueError):
    """Model output was not usable JSON. The kernel maps this to
    NEEDS_DECISION / provider.failure -- fail closed, never synthesize."""


class OpenRouterBudgetExhausted(RuntimeError):
    """The shared investigation token budget is exhausted."""


@lru_cache(maxsize=1)
def _kernel():
    # Deferred import: the adapter stays importable without the kernel, and
    # the kernel module itself is pure-local (no network, no env, no I/O).
    from scripts.agent_os_pr_remediation import high_reasoning_proposal

    return high_reasoning_proposal


class OpenRouterBudgetTracker:
    """Shared token budget for one dual-model investigation.

    The pre-call check guarantees no new provider call starts once the budget
    is exhausted; per-call accounting records actual usage afterwards. A single
    response may overrun the budget by at most its own reported usage -- the
    bound on ``max_tokens_per_request`` keeps that overrun small.
    """

    def __init__(self, max_total_tokens: int):
        if isinstance(max_total_tokens, bool) or not isinstance(max_total_tokens, int) or max_total_tokens <= 0:
            raise ValueError("max_total_tokens must be a positive integer")
        self._max_total_tokens = max_total_tokens
        self._tokens_used = 0

    @property
    def tokens_used(self) -> int:
        return self._tokens_used

    @property
    def tokens_remaining(self) -> int:
        return self._max_total_tokens - self._tokens_used

    def check_available(self) -> None:
        if self.tokens_remaining <= 0:
            raise OpenRouterBudgetExhausted("shared investigation token budget is exhausted")

    def record_spent(self, tokens: int) -> None:
        if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens < 0:
            raise ValueError("tokens must be a non-negative integer")
        self._tokens_used += tokens


@dataclass
class AdapterStats:
    requests_made: int = 0
    tokens_used: int = 0
    retries: int = 0
    latency_seconds: float = 0.0


class OpenRouterProposalAdapter:
    """ProposalAdapter backed by OpenRouter chat completions.

    Structural implementation of the protocol: ``propose(request_payload)``.
    """

    def __init__(
        self,
        config: OpenRouterConfig,
        model_identity: str,
        transport: Transport | None = None,
        budget_tracker: OpenRouterBudgetTracker | None = None,
        pricing_gate: FreeModelPricingGate | None = None,
        generation_cost_fetcher: GenerationFetcher | None = None,
    ) -> None:
        if not isinstance(config, OpenRouterConfig):
            raise TypeError("config must be OpenRouterConfig")
        config.validate()
        if not isinstance(model_identity, str) or not model_identity.strip():
            raise ValueError("model_identity must be a non-empty string")
        if transport is not None and not callable(transport):
            raise TypeError("transport must be callable")
        if pricing_gate is not None and not isinstance(pricing_gate, FreeModelPricingGate):
            raise TypeError("pricing_gate must be FreeModelPricingGate")
        if generation_cost_fetcher is not None and not callable(generation_cost_fetcher):
            raise TypeError("generation_cost_fetcher must be callable")
        self._config = config
        self._model_identity = model_identity
        self._transport: Transport = transport or self._default_transport()
        self._budget = budget_tracker or OpenRouterBudgetTracker(config.max_total_tokens)
        self._pricing_gate = pricing_gate
        self._generation_cost_fetcher = generation_cost_fetcher
        self._stats = AdapterStats()
        # Latest zero-cost evidence, plus a count proving EVERY transport
        # invocation was preceded by exactly one successful verification.
        # _pricing_gate_defect records the gate's failure message when the
        # gate raises: the kernel maps the exception to NEEDS_DECISION /
        # provider.failure, so the flag is the runner-level defect signal.
        self._pricing_evidence: dict[str, Any] | None = None
        self._pricing_verifications = 0
        self._generation_cost_evidence: dict[str, Any] | None = None
        self._pricing_gate_defect: str | None = None

    @property
    def config(self) -> OpenRouterConfig:
        return self._config

    @property
    def model_identity(self) -> str:
        return self._model_identity

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "requests_made": self._stats.requests_made,
            "tokens_used": self._stats.tokens_used,
            "retries": self._stats.retries,
            "latency_seconds": self._stats.latency_seconds,
            "pricing_evidence": self._pricing_evidence,
            "pricing_verifications": self._pricing_verifications,
            "generation_cost_evidence": self._generation_cost_evidence,
            "pricing_gate_defect": self._pricing_gate_defect,
        }

    def propose(self, request_payload: Mapping[str, Any]) -> Mapping[str, Any]:
        kernel = _kernel()
        config = self._config

        # Fail closed before any network: disabled or keyless is unavailable.
        if not config.is_configured():
            raise kernel.ProposalProviderUnavailable("openrouter pilot is not configured")
        if self._stats.requests_made >= config.max_requests_per_investigation:
            raise kernel.ProposalProviderUnavailable("per-investigation request budget exhausted")
        try:
            self._budget.check_available()
        except OpenRouterBudgetExhausted as exc:
            raise kernel.ProposalProviderUnavailable(str(exc)) from None

        self._assert_payload_bounds(request_payload)

        # Key read at call time only; never stored, never logged, never
        # interpolated into errors.
        api_key = os.environ.get(config.api_key_env_var)
        if not api_key or not api_key.strip():
            raise kernel.ProposalProviderUnavailable("openrouter api key is not available")

        fingerprint = request_payload.get("request_fingerprint")
        if not isinstance(fingerprint, str) or not fingerprint:
            raise kernel.ProposalProviderUnavailable("request payload lacks a request fingerprint")

        # Free-model pricing gate, IN THE INVOCATION PATH: no transport call
        # happens unless zero-cost pricing was just verified for the exact
        # model identity below. Raises OpenRouterPricingGateError (fail
        # closed) on unknown/missing/nonzero pricing or a failed re-fetch.
        # The defect message is recorded on the adapter because the kernel
        # maps the raised exception to NEEDS_DECISION / provider.failure.
        if self._pricing_gate is not None:
            try:
                self._pricing_evidence = self._pricing_gate.verify_model_is_free(
                    self._model_identity
                )
            except OpenRouterPricingGateError as exc:
                self._pricing_gate_defect = f"{type(exc).__name__}: {exc}"
                raise
            self._pricing_verifications += 1

        body = {
            "model": self._model_identity,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": self._canonical_payload(request_payload)},
            ],
            "max_tokens": config.max_tokens_per_request,
        }
        headers = {"Authorization": "Bearer " + api_key, "Content-Type": "application/json"}

        started = time.monotonic()
        self._stats.requests_made += 1
        try:
            response = self._post_with_retry(body, headers)
        finally:
            self._stats.latency_seconds += time.monotonic() - started

        self._record_usage(response)

        # Post-call cost verification: the generation id from the response is
        # looked up and its cost must verify zero. Nonzero or unknown cost is
        # a fail-closed defect (these models are free). A gate without a
        # cost lookup configured also fails closed -- unverifiable is unknown.
        if self._pricing_gate is not None:
            generation_id = response.get("id") if isinstance(response, Mapping) else None
            try:
                self._generation_cost_evidence = self._pricing_gate.verify_generation_cost_zero(
                    generation_id, self._generation_cost_fetcher
                )
            except OpenRouterPricingGateError as exc:
                self._pricing_gate_defect = f"{type(exc).__name__}: {exc}"
                raise

        content = self._extract_content(response)
        if len(content.encode("utf-8")) > kernel.MAX_RESPONSE_BYTES:
            raise kernel.ProposalProviderUnavailable("model response exceeds size bound")

        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            raise OpenRouterMalformedResponse("model response is not valid JSON") from None
        if not isinstance(parsed, dict):
            raise OpenRouterMalformedResponse("model response JSON is not an object")

        # Deterministic binding overwrite: the model cannot forge these.
        parsed["provider_identity"] = PROVIDER_IDENTITY
        parsed["model_identity"] = self._model_identity
        parsed["request_fingerprint"] = fingerprint
        return parsed

    # -- internals ---------------------------------------------------------

    def _default_transport(self) -> Transport:
        endpoint = self._config.endpoint

        def _transport(body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
            data = json.dumps(body).encode("utf-8")
            request = urllib.request.Request(endpoint, data=data, headers=dict(headers), method="POST")
            with urllib.request.urlopen(request, timeout=timeout) as http_response:
                raw = http_response.read()
            parsed = json.loads(raw.decode("utf-8"))
            if not isinstance(parsed, dict):
                raise ValueError("openrouter envelope is not a JSON object")
            return parsed

        return _transport

    def _post_with_retry(self, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        kernel = _kernel()
        config = self._config
        attempts = 0
        while True:
            try:
                return self._transport(body, headers, config.timeout_seconds)
            except urllib.error.HTTPError as exc:
                status = exc.code
                if status in _RETRYABLE_HTTP_STATUS and attempts < config.max_retries:
                    attempts += 1
                    self._stats.retries += 1
                    time.sleep(config.retry_backoff_seconds * (2 ** (attempts - 1)))
                    continue
                # 4xx (other than 429) is terminal: fail closed, no retry.
                raise kernel.ProposalProviderUnavailable(
                    f"openrouter request failed with HTTP {status}"
                ) from None
            except (urllib.error.URLError, TimeoutError, OSError):
                if attempts < config.max_retries:
                    attempts += 1
                    self._stats.retries += 1
                    time.sleep(config.retry_backoff_seconds * (2 ** (attempts - 1)))
                    continue
                raise kernel.ProposalProviderUnavailable(
                    "openrouter request failed after retries"
                ) from None
            except (ValueError, TypeError, KeyError):
                # Unusable transport envelope (e.g. non-JSON body).
                raise kernel.ProposalProviderUnavailable(
                    "openrouter transport returned an unusable response"
                ) from None

    def _record_usage(self, response: Any) -> None:
        tokens = 0
        if isinstance(response, Mapping):
            usage = response.get("usage")
            if isinstance(usage, Mapping):
                candidate = usage.get("total_tokens", 0)
                if isinstance(candidate, int) and not isinstance(candidate, bool) and candidate >= 0:
                    tokens = candidate
        self._budget.record_spent(tokens)
        self._stats.tokens_used += tokens

    def _extract_content(self, response: Any) -> str:
        if not isinstance(response, Mapping):
            raise OpenRouterMalformedResponse("response envelope is not a mapping")
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            raise OpenRouterMalformedResponse("response has no choices")
        first = choices[0]
        message = first.get("message") if isinstance(first, Mapping) else None
        content = message.get("content") if isinstance(message, Mapping) else None
        if not isinstance(content, str) or not content.strip():
            raise OpenRouterMalformedResponse("model response content is missing or empty")
        return content

    def _assert_payload_bounds(self, payload: Any) -> None:
        """Defense-in-depth: no payload string may exceed the text bound.

        The payload is structured investigation metadata (paths, SHAs,
        schema keys) -- never file contents. The kernel already bounds
        ProposalRequest text; this re-checks for callers that bypass it.
        """
        kernel = _kernel()
        stack = [payload]
        while stack:
            value = stack.pop()
            if isinstance(value, str):
                if len(value.encode("utf-8")) > MAX_PAYLOAD_TEXT_BYTES:
                    raise kernel.ProposalProviderUnavailable(
                        "request payload value exceeds the metadata text bound"
                    )
            elif isinstance(value, Mapping):
                stack.extend(value.values())
            elif isinstance(value, (list, tuple)):
                stack.extend(value)

    @staticmethod
    def _canonical_payload(request_payload: Mapping[str, Any]) -> str:
        return json.dumps(
            dict(request_payload), sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        )
