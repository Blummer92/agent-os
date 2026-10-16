"""Free-model pricing gate for the OpenRouter pilot (#3637).

Fail-closed enforcement that a model invocation costs nothing, checked IN THE
INVOCATION PATH (inside ``OpenRouterProposalAdapter.propose``) rather than as
an advisory side check. Rules:

- The exact model identity sent to the API must end with ``:free``. The gate
  never strips ``:free`` and never substitutes a paid model; a stripped or
  paid identity is rejected.
- Zero-cost pricing must be verified from an OpenRouter ``/models`` catalog
  snapshot: ``pricing.prompt`` and ``pricing.completion`` must both be zero.
  Accepted zero forms: the string ``"0"`` / ``"0.0"`` (OpenRouter's wire
  format), int ``0``, float ``0.0``. Anything else -- missing keys, unknown
  model id, nonzero values, non-numeric strings -- fails closed.
- Catalog freshness: the runner fetches a fresh catalog at start; the gate
  re-fetches before EVERY invocation when a refetch callable is configured.
  A re-fetch failure mid-run fails closed: no invocation on stale or unknown
  pricing, never a fallback to the previous snapshot.
- Post-call cost verification: the generation id from the chat-completions
  response is looked up at ``/api/v1/generation``; a nonzero or unknown cost
  is a fail-closed defect (these models are free).

Any violation raises :class:`OpenRouterPricingGateError`. The kernel maps an
adapter exception to NEEDS_DECISION / ``provider.failure`` -- never a
synthesized plan.

Zero network in tests: the catalog snapshot, the refetch callable, and the
generation-cost lookup are all injectable.
"""

from __future__ import annotations

import json
import time
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

DEFAULT_MODELS_ENDPOINT = "https://openrouter.ai/api/v1/models"
DEFAULT_GENERATION_ENDPOINT = "https://openrouter.ai/api/v1/generation"

FREE_MODEL_SUFFIX = ":free"


class OpenRouterPricingGateError(RuntimeError):
    """A pricing assumption was violated. Fail closed: no invocation, no
    paid-model fallback, no stale-snapshot reuse."""


def is_zero_price(value: Any) -> bool:
    """True only for an unambiguous numeric zero.

    Accepts ``"0"`` / ``"0.0"`` (and surrounding whitespace), int ``0``,
    float ``0.0``. Rejects bools, non-numeric strings, None, and any nonzero
    value -- including tiny ones like ``"0.000001"``.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return value == 0
    if isinstance(value, str):
        try:
            return float(value.strip()) == 0.0
        except ValueError:
            return False
    return False


def fetch_models_catalog(endpoint: str, timeout_seconds: float) -> dict[str, Any]:
    """Fetch the live ``/models`` catalog. Raises on any transport or parse
    failure -- the caller fails closed."""
    request = urllib.request.Request(endpoint, method="GET")
    with urllib.request.urlopen(request, timeout=timeout_seconds) as http_response:
        raw = http_response.read()
    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise OpenRouterPricingGateError("models catalog response is not a JSON object")
    return parsed


def fetch_generation_record(
    endpoint: str, api_key: str, generation_id: str, timeout_seconds: float
) -> dict[str, Any]:
    """Fetch one generation record from ``/api/v1/generation``. Raises on any
    transport or parse failure -- unknown cost fails closed."""
    url = endpoint.rstrip("/") + "?ids=" + generation_id
    request = urllib.request.Request(
        url, headers={"Authorization": "Bearer " + api_key}, method="GET"
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as http_response:
        raw = http_response.read()
    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise OpenRouterPricingGateError("generation response is not a JSON object")
    return parsed


# Injectable catalog source: () -> parsed /models JSON dict.
CatalogFetcher = Callable[[], dict[str, Any]]
# Injectable generation lookup: (generation_id) -> parsed /generation JSON dict.
GenerationFetcher = Callable[[str], dict[str, Any]]


class FreeModelPricingGate:
    """Verifies zero-cost pricing before each invocation and zero actual cost
    after each response.

    ``catalog_snapshot`` is the ``/models`` response fetched at runner start.
    When ``catalog_refetch`` is provided it is called before EVERY invocation;
    a refetch failure raises instead of reusing the stale snapshot.
    """

    def __init__(
        self,
        catalog_snapshot: Mapping[str, Any],
        catalog_refetch: CatalogFetcher | None = None,
    ) -> None:
        if not isinstance(catalog_snapshot, Mapping):
            raise OpenRouterPricingGateError("catalog snapshot must be a mapping")
        if catalog_refetch is not None and not callable(catalog_refetch):
            raise TypeError("catalog_refetch must be callable")
        self._catalog = catalog_snapshot
        self._refetch = catalog_refetch

    def verify_model_is_free(self, model_id: str) -> dict[str, Any]:
        """Re-verify (refetching first when configured) that ``model_id`` is a
        free model with zero prompt and completion pricing.

        Returns the pricing evidence record. Raises
        :class:`OpenRouterPricingGateError` on any violation -- including a
        failed refetch, which never falls back to the stale snapshot.
        """
        if not isinstance(model_id, str) or not model_id:
            raise OpenRouterPricingGateError("model identity is missing")
        if not model_id.endswith(FREE_MODEL_SUFFIX):
            # NEVER strip ':free' or substitute a paid model: reject outright.
            raise OpenRouterPricingGateError(
                f"model '{model_id}' is not a free-model identity "
                f"(must end with '{FREE_MODEL_SUFFIX}')"
            )
        if self._refetch is not None:
            try:
                fresh = self._refetch()
            except OpenRouterPricingGateError:
                raise
            except Exception as exc:  # noqa: BLE001 -- any fetch failure fails closed
                raise OpenRouterPricingGateError(
                    "models catalog re-fetch failed; refusing invocation on "
                    f"stale pricing: {type(exc).__name__}"
                ) from None
            if not isinstance(fresh, Mapping):
                raise OpenRouterPricingGateError(
                    "models catalog re-fetch returned a non-mapping; refusing invocation"
                )
            self._catalog = fresh

        entry = self._find_entry(model_id)
        pricing = entry.get("pricing")
        if not isinstance(pricing, Mapping):
            raise OpenRouterPricingGateError(
                f"model '{model_id}' has no pricing block in the catalog"
            )
        prompt_price = pricing.get("prompt")
        completion_price = pricing.get("completion")
        if prompt_price is None or completion_price is None:
            raise OpenRouterPricingGateError(
                f"model '{model_id}' is missing prompt/completion pricing"
            )
        if not is_zero_price(prompt_price) or not is_zero_price(completion_price):
            raise OpenRouterPricingGateError(
                f"model '{model_id}' is not zero-cost "
                f"(prompt={prompt_price!r}, completion={completion_price!r})"
            )
        return {
            "model_id": model_id,
            "prompt_price": prompt_price,
            "completion_price": completion_price,
            "verified_at_epoch": time.time(),
            "catalog_entry_id": entry.get("id"),
        }

    def verify_generation_cost_zero(
        self, generation_id: str | None, fetch_generation: GenerationFetcher | None
    ) -> dict[str, Any]:
        """Verify the actual cost of one generation is zero.

        ``generation_id`` is the ``id`` field of the chat-completions
        response. A missing id, a failed lookup, a missing/unknown cost, or a
        nonzero cost all raise :class:`OpenRouterPricingGateError`.
        """
        if not isinstance(generation_id, str) or not generation_id:
            raise OpenRouterPricingGateError(
                "cannot verify cost: response carries no generation id"
            )
        if fetch_generation is None or not callable(fetch_generation):
            raise OpenRouterPricingGateError(
                "cannot verify cost: no generation-cost lookup is configured"
            )
        try:
            record = fetch_generation(generation_id)
        except OpenRouterPricingGateError:
            raise
        except Exception as exc:  # noqa: BLE001 -- unknown cost fails closed
            raise OpenRouterPricingGateError(
                "generation cost lookup failed; treating cost as unknown: "
                f"{type(exc).__name__}"
            ) from None
        cost = _extract_total_cost(record)
        if cost is None:
            raise OpenRouterPricingGateError(
                f"generation '{generation_id}' has unknown cost; failing closed"
            )
        if not is_zero_price(cost):
            raise OpenRouterPricingGateError(
                f"generation '{generation_id}' cost is nonzero ({cost!r}); "
                "free-model assumption violated"
            )
        return {
            "generation_id": generation_id,
            "total_cost": cost,
            "verified_at_epoch": time.time(),
        }

    def _find_entry(self, model_id: str) -> Mapping[str, Any]:
        data = self._catalog.get("data")
        if not isinstance(data, list):
            raise OpenRouterPricingGateError("catalog snapshot has no 'data' list")
        for entry in data:
            if isinstance(entry, Mapping) and entry.get("id") == model_id:
                return entry
        raise OpenRouterPricingGateError(
            f"model '{model_id}' is not present in the models catalog"
        )


def _extract_total_cost(record: Mapping[str, Any]) -> Any:
    """Pull the total cost out of a /generation response.

    The endpoint returns ``{"data": [{"id": ..., "total_cost": ...}]}``;
    accept that shape plus a bare ``{"total_cost": ...}`` record. Returns
    None when no cost is present (unknown -- fails closed upstream).
    """
    if not isinstance(record, Mapping):
        return None
    data = record.get("data")
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, Mapping) and "total_cost" in first:
            return first["total_cost"]
    if "total_cost" in record:
        return record["total_cost"]
    return None
