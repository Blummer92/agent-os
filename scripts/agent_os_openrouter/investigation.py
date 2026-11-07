"""Dual-model independent investigation orchestration for the #3637 pilot.

Two OpenRouter models investigate the same ``ProposalRequest`` independently:
separate adapter instances, separate provider calls, separate provenance.
The only shared mutable state is the investigation token-budget tracker, so
one model's spend is visible to the other's pre-call gate without coupling
their outcomes.

Kernel imports are deferred to call time so this module (and the package)
stays importable without the kernel on the path; the kernel itself is
pure-local. Kernel preconditions (enforced by ``propose_high_reasoning_plan``
itself, not re-implemented here): the caller must construct a
``ProposalRequest`` with ``compute_route="high-reasoning-required"``,
``authorization_state="authorized"`` plus an ``authorization_fingerprint``,
and ``source_sha == observed_source_sha``. When any precondition fails the
kernel returns NEEDS_DECISION/MANUAL_REVIEW without invoking the adapter, and
that disposition is recorded per model.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from .adapter import OpenRouterBudgetExhausted, OpenRouterBudgetTracker, OpenRouterProposalAdapter, Transport
from .config import OpenRouterConfig
from .pricing import FreeModelPricingGate, GenerationFetcher


@lru_cache(maxsize=1)
def _proposal_kernel():
    from scripts.agent_os_pr_remediation import high_reasoning_proposal

    return high_reasoning_proposal


@lru_cache(maxsize=1)
def _models_kernel():
    from scripts.agent_os_pr_remediation import models

    return models


@dataclass(frozen=True, slots=True)
class ModelInvestigationOutcome:
    """Per-model provenance record. Fail-closed: a model that errors still
    yields a record with its reason codes, never a synthesized plan."""

    model_identity: str
    outcome: str  # ProposalOutcome.value
    reason_codes: tuple[str, ...]
    plan_id: str | None
    request_fingerprint: str
    tokens_used: int
    latency_seconds: float
    retries: int
    adapter_invoked: bool
    error: str | None  # short redacted note; None on a clean kernel run
    # Zero-cost evidence from the pricing gate (None when no gate was wired).
    # Per-run evidence, not identity: excluded from identity_core() like
    # latency_seconds. pricing_gate_defect carries the gate's failure message
    # when the gate raised: the kernel maps the exception to NEEDS_DECISION /
    # provider.failure with error=None, so this flag is the runner-level
    # signal that the free-model assumption was violated.
    pricing_evidence: dict[str, Any] | None = None
    generation_cost_evidence: dict[str, Any] | None = None
    pricing_gate_defect: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "model_identity": self.model_identity,
            "outcome": self.outcome,
            "reason_codes": list(self.reason_codes),
            "plan_id": self.plan_id,
            "request_fingerprint": self.request_fingerprint,
            "tokens_used": self.tokens_used,
            "latency_seconds": self.latency_seconds,
            "retries": self.retries,
            "adapter_invoked": self.adapter_invoked,
            "error": self.error,
            "pricing_evidence": self.pricing_evidence,
            "generation_cost_evidence": self.generation_cost_evidence,
            "pricing_gate_defect": self.pricing_gate_defect,
        }

    def identity_core(self) -> dict[str, Any]:
        """Deterministic subset for content addressing. Wall-clock latency and
        pricing/cost evidence are evidence, not identity: they are excluded so
        the investigation id is stable across replays of the same logical
        investigation."""
        payload = self.to_payload()
        del payload["latency_seconds"]
        del payload["pricing_evidence"]
        del payload["generation_cost_evidence"]
        del payload["pricing_gate_defect"]
        return payload


@dataclass(frozen=True, slots=True)
class DualInvestigationResult:
    """Frozen, content-addressed record of one dual-model investigation."""

    investigation_id: str
    request_fingerprint: str
    model_a: ModelInvestigationOutcome
    model_b: ModelInvestigationOutcome
    total_tokens_used: int
    budget_exhausted_before_model_b: bool

    def to_payload(self) -> dict[str, Any]:
        return {
            "investigation_id": self.investigation_id,
            "request_fingerprint": self.request_fingerprint,
            "model_a": self.model_a.to_payload(),
            "model_b": self.model_b.to_payload(),
            "total_tokens_used": self.total_tokens_used,
            "budget_exhausted_before_model_b": self.budget_exhausted_before_model_b,
        }


def run_dual_investigation(
    request: "object",
    config: OpenRouterConfig,
    transport: Transport | None = None,
    pricing_gate: FreeModelPricingGate | None = None,
    generation_cost_fetcher: GenerationFetcher | None = None,
) -> DualInvestigationResult:
    """Run both pilot models against the same request, independently.

    ``transport`` is injectable for offline tests; when omitted each adapter
    builds its own default urllib transport. One model's failure never poisons
    the other: each outcome is recorded separately, fail-closed per model.
    When ``pricing_gate`` is provided it is enforced inside every adapter
    invocation (zero-cost verification pre-call, cost verification post-call);
    the resulting evidence is threaded into each model's outcome record.
    """
    kernel = _proposal_kernel()
    if not isinstance(request, kernel.ProposalRequest):
        raise TypeError("request must be ProposalRequest")
    if not isinstance(config, OpenRouterConfig):
        raise TypeError("config must be OpenRouterConfig")
    config.validate()

    tracker = OpenRouterBudgetTracker(config.max_total_tokens)
    fingerprint = request.request_fingerprint

    def _run_one(model_identity: str) -> ModelInvestigationOutcome:
        adapter = OpenRouterProposalAdapter(
            config,
            model_identity,
            transport=transport,
            budget_tracker=tracker,
            pricing_gate=pricing_gate,
            generation_cost_fetcher=generation_cost_fetcher,
        )
        try:
            result = kernel.propose_high_reasoning_plan(request, adapter)
        except Exception as exc:  # noqa: BLE001 -- record, never propagate
            stats = adapter.stats
            return ModelInvestigationOutcome(
                model_identity=model_identity,
                outcome=kernel.ProposalOutcome.NEEDS_DECISION.value,
                reason_codes=("provider.failure",),
                plan_id=None,
                request_fingerprint=fingerprint,
                tokens_used=stats["tokens_used"],
                latency_seconds=stats["latency_seconds"],
                retries=stats["retries"],
                adapter_invoked=False,
                error=_redact_error(exc),
                pricing_evidence=stats["pricing_evidence"],
                generation_cost_evidence=stats["generation_cost_evidence"],
                pricing_gate_defect=stats["pricing_gate_defect"],
            )
        stats = adapter.stats
        return ModelInvestigationOutcome(
            model_identity=model_identity,
            outcome=result.outcome.value,
            reason_codes=result.reason_codes,
            plan_id=result.plan.plan_id if result.plan is not None else None,
            request_fingerprint=fingerprint,
            tokens_used=stats["tokens_used"],
            latency_seconds=stats["latency_seconds"],
            retries=stats["retries"],
            adapter_invoked=result.adapter_invoked,
            error=None,
            pricing_evidence=stats["pricing_evidence"],
            generation_cost_evidence=stats["generation_cost_evidence"],
            pricing_gate_defect=stats["pricing_gate_defect"],
        )

    outcome_a = _run_one(config.model_a)

    budget_exhausted = False
    try:
        tracker.check_available()
    except OpenRouterBudgetExhausted:
        budget_exhausted = True
    if budget_exhausted:
        outcome_b = ModelInvestigationOutcome(
            model_identity=config.model_b,
            outcome=kernel.ProposalOutcome.NEEDS_DECISION.value,
            reason_codes=("provider.unavailable",),
            plan_id=None,
            request_fingerprint=fingerprint,
            tokens_used=0,
            latency_seconds=0.0,
            retries=0,
            adapter_invoked=False,
            error="shared token budget exhausted; second model not invoked",
        )
    else:
        outcome_b = _run_one(config.model_b)

    models = _models_kernel()
    core = {
        "request_fingerprint": fingerprint,
        "model_a": outcome_a.identity_core(),
        "model_b": outcome_b.identity_core(),
        "total_tokens_used": tracker.tokens_used,
        "budget_exhausted_before_model_b": budget_exhausted,
    }
    investigation_id = "dual-investigation:" + models.deterministic_id(core)
    return DualInvestigationResult(
        investigation_id=investigation_id,
        request_fingerprint=fingerprint,
        model_a=outcome_a,
        model_b=outcome_b,
        total_tokens_used=tracker.tokens_used,
        budget_exhausted_before_model_b=budget_exhausted,
    )


def _redact_error(exc: BaseException) -> str:
    # Adapter and kernel messages never contain the API key (it is never
    # interpolated into errors), but truncate defensively anyway.
    text = f"{type(exc).__name__}: {exc}".strip()
    return text[:200]


def serialize_dual_investigation(result: DualInvestigationResult) -> bytes:
    if not isinstance(result, DualInvestigationResult):
        raise TypeError("result must be DualInvestigationResult")
    return _models_kernel().canonical_json(result.to_payload()).encode("utf-8")
