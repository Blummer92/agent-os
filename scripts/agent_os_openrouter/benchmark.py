"""Benchmark harness for the OpenRouter pilot (#3637).

Compares the dual-model investigation pipeline against a corpus of previously
verified Agent OS bugs (``benchmark_corpus.json``). Default mode is fully
offline: an injectable runner replays canned per-bug model transcripts from
the corpus fixtures, so no network call is ever made in tests.

Offline metrics per bug and in aggregate:
- time to verified root cause (simulated from fixture transcripts offline)
- detection accuracy (predicted root-cause key vs the verified key)
- false positives count
- token usage and estimated cost (per-model reference price in the fixture)
- regression-test success as the kernel verifier ACCEPTED rate

The ``--live`` path runs the real two-model comparison (10 bugs x 2 models =
20 investigations) through the free-model pricing gate. It refuses to run
unless ``OPENROUTER_BENCHMARK_LIVE_APPROVED`` is exactly ``"true"`` AND the
pilot config is enabled and keyed. Every model invocation verifies zero-cost
pricing from a fresh ``/models`` catalog snapshot before the call and zero
actual cost via ``/api/v1/generation`` after it; any pricing violation fails
closed and stops the run. Paid-model fallback is prohibited.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .config import LIVE_BENCHMARK_ENV_VAR, OpenRouterConfig
from .pricing import (
    FreeModelPricingGate,
    GenerationFetcher,
    OpenRouterPricingGateError,
    fetch_generation_record,
    fetch_models_catalog,
)

CORPUS_SCHEMA_VERSION = "1.0"
MODEL_ROLES = ("model_a", "model_b")

_REQUIRED_ENTRY_KEYS = frozenset({
    "issue_number", "title", "verified_root_cause", "verified_root_cause_key",
    "evidence_refs", "detection_criteria", "reference_transcript",
    "estimated_cost_usd_per_1k_tokens",
})
_REQUIRED_TRANSCRIPT_KEYS = frozenset({
    "predicted_root_cause", "predicted_root_cause_key", "tokens_used",
    "latency_seconds", "time_to_root_cause_seconds", "false_positives",
    "kernel_verifier_outcome",
})


class CorpusError(ValueError):
    """The benchmark corpus is malformed."""


class LiveBenchmarkNotApproved(RuntimeError):
    """The --live path was requested without the required approvals."""


# Offline runner: (corpus_entry, model_role) -> simulated model observation.
OfflineRunner = Callable[[Mapping[str, Any], str], Mapping[str, Any]]


def load_corpus(path: str | Path) -> list[dict[str, Any]]:
    """Load and validate the benchmark corpus."""
    raw_path = Path(path)
    try:
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CorpusError(f"cannot load corpus: {exc}") from None
    if not isinstance(raw, dict) or raw.get("schema_version") != CORPUS_SCHEMA_VERSION:
        raise CorpusError("corpus schema_version must be '1.0'")
    entries = raw.get("entries")
    if not isinstance(entries, list) or not entries:
        raise CorpusError("corpus entries must be a non-empty list")
    for entry in entries:
        _validate_entry(entry)
    return entries


def _validate_entry(entry: Any) -> None:
    if not isinstance(entry, dict):
        raise CorpusError("corpus entry must be an object")
    missing = _REQUIRED_ENTRY_KEYS - set(entry)
    if missing:
        raise CorpusError(f"corpus entry {entry.get('issue_number')} missing keys: {sorted(missing)}")
    if not isinstance(entry["issue_number"], int):
        raise CorpusError("issue_number must be an integer")
    transcript = entry["reference_transcript"]
    if not isinstance(transcript, dict):
        raise CorpusError("reference_transcript must be an object")
    for role in MODEL_ROLES:
        fixture = transcript.get(role)
        if not isinstance(fixture, dict):
            raise CorpusError(f"reference_transcript missing model role '{role}'")
        missing = _REQUIRED_TRANSCRIPT_KEYS - set(fixture)
        if missing:
            raise CorpusError(f"transcript fixture for '{role}' missing keys: {sorted(missing)}")
    prices = entry["estimated_cost_usd_per_1k_tokens"]
    if not isinstance(prices, dict) or any(
        role not in prices or not isinstance(prices[role], (int, float)) for role in MODEL_ROLES
    ):
        raise CorpusError("estimated_cost_usd_per_1k_tokens must price model_a and model_b")


def default_offline_runner(entry: Mapping[str, Any], model_role: str) -> Mapping[str, Any]:
    """Replay the canned transcript fixture for one bug and model role."""
    if model_role not in MODEL_ROLES:
        raise ValueError(f"unknown model role: {model_role}")
    return dict(entry["reference_transcript"][model_role])


@dataclass(frozen=True, slots=True)
class ModelBenchmarkResult:
    model_role: str
    predicted_root_cause_key: str
    detected: bool
    time_to_root_cause_seconds: float | None
    false_positives: int
    tokens_used: int
    estimated_cost_usd: float
    kernel_verifier_accepted: bool

    def to_payload(self) -> dict[str, Any]:
        return {
            "model_role": self.model_role,
            "predicted_root_cause_key": self.predicted_root_cause_key,
            "detected": self.detected,
            "time_to_root_cause_seconds": self.time_to_root_cause_seconds,
            "false_positives": self.false_positives,
            "tokens_used": self.tokens_used,
            "estimated_cost_usd": self.estimated_cost_usd,
            "kernel_verifier_accepted": self.kernel_verifier_accepted,
        }


@dataclass(frozen=True, slots=True)
class BugBenchmarkResult:
    issue_number: int
    title: str
    model_a: ModelBenchmarkResult
    model_b: ModelBenchmarkResult

    def to_payload(self) -> dict[str, Any]:
        return {
            "issue_number": self.issue_number,
            "title": self.title,
            "model_a": self.model_a.to_payload(),
            "model_b": self.model_b.to_payload(),
        }


@dataclass(frozen=True, slots=True)
class BenchmarkAggregate:
    bugs_evaluated: int
    detection_accuracy: float
    mean_time_to_root_cause_seconds: float | None
    total_false_positives: int
    total_tokens_used: int
    total_estimated_cost_usd: float
    kernel_verifier_accepted_rate: float

    def to_payload(self) -> dict[str, Any]:
        return {
            "bugs_evaluated": self.bugs_evaluated,
            "detection_accuracy": self.detection_accuracy,
            "mean_time_to_root_cause_seconds": self.mean_time_to_root_cause_seconds,
            "total_false_positives": self.total_false_positives,
            "total_tokens_used": self.total_tokens_used,
            "total_estimated_cost_usd": self.total_estimated_cost_usd,
            "kernel_verifier_accepted_rate": self.kernel_verifier_accepted_rate,
        }


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    bugs: tuple[BugBenchmarkResult, ...]
    aggregate: BenchmarkAggregate

    def to_payload(self) -> dict[str, Any]:
        return {
            "bugs": [bug.to_payload() for bug in self.bugs],
            "aggregate": self.aggregate.to_payload(),
        }


def run_benchmark(
    corpus: Sequence[Mapping[str, Any]],
    runner: OfflineRunner | None = None,
    *,
    live: bool = False,
    config: OpenRouterConfig | None = None,
    transport: Callable[..., Any] | None = None,
    catalog_fetcher: Callable[[], dict[str, Any]] | None = None,
    generation_cost_fetcher: GenerationFetcher | None = None,
) -> BenchmarkReport | "LiveBenchmarkReport":
    """Execute the benchmark over every corpus entry.

    Offline by default. ``live=True`` runs the real two-model comparison via
    :func:`run_live_benchmark`; it is refused unless the live-approval env var
    is exactly "true" and the pilot config is enabled and keyed. ``runner``
    is offline-only and rejected together with ``live=True``. The ``transport``,
    ``catalog_fetcher``, and ``generation_cost_fetcher`` hooks are injectable
    so tests stay zero-network.
    """
    if live:
        if runner is not None:
            raise ValueError("runner is offline-only; the live path uses the provider transport")
        return run_live_benchmark(
            corpus,
            config,
            transport=transport,
            catalog_fetcher=catalog_fetcher,
            generation_cost_fetcher=generation_cost_fetcher,
        )
    active_runner = runner or default_offline_runner
    bugs = tuple(_benchmark_bug(entry, active_runner) for entry in corpus)
    return BenchmarkReport(bugs=bugs, aggregate=_aggregate(bugs))


def _require_live_approval(config: OpenRouterConfig | None) -> None:
    approved = os.environ.get(LIVE_BENCHMARK_ENV_VAR) == "true"
    configured = isinstance(config, OpenRouterConfig) and config.is_configured()
    if not (approved and configured):
        raise LiveBenchmarkNotApproved(
            "live benchmark refused: requires "
            f"{LIVE_BENCHMARK_ENV_VAR}='true' and an enabled, keyed pilot config"
        )


# ---------------------------------------------------------------------------
# Live benchmark: 10 bugs x 2 models = 20 investigations through the pricing
# gate. Governance is not bypassed: every investigation goes through the
# kernel's ProposalAdapter seam and strict verifier (unchanged), the pricing
# gate is enforced inside each adapter invocation, and the corpus's verified
# root cause / detection criteria are NEVER sent to the model (they stay in
# the harness for post-hoc adjudication). Live detection accuracy is therefore
# not manufactured: the aggregate reports verifier outcomes, tokens, latency,
# and verified costs, with detection adjudication deferred to owner review.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LiveModelResult:
    model_identity: str
    pricing_evidence: dict[str, Any] | None
    outcome: str  # ProposalOutcome.value: "accepted" / "rejected" / "needs-decision" / ...
    reason_codes: tuple[str, ...]
    plan_id: str | None
    tokens_used: int
    latency_seconds: float  # wall-clock time to verifier outcome
    retries: int
    generation_cost_evidence: dict[str, Any] | None
    # Set when the pricing gate raised: the kernel maps the exception to
    # NEEDS_DECISION / provider.failure with error=None, so this flag (not
    # the error string) is the fail-closed run-stop signal.
    pricing_gate_defect: str | None
    adapter_invoked: bool
    error: str | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "model_identity": self.model_identity,
            "pricing_evidence": self.pricing_evidence,
            "outcome": self.outcome,
            "reason_codes": list(self.reason_codes),
            "plan_id": self.plan_id,
            "tokens_used": self.tokens_used,
            "latency_seconds": self.latency_seconds,
            "retries": self.retries,
            "generation_cost_evidence": self.generation_cost_evidence,
            "pricing_gate_defect": self.pricing_gate_defect,
            "adapter_invoked": self.adapter_invoked,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class LiveBugResult:
    issue_number: int
    title: str
    # Kept for post-hoc owner adjudication; never sent to the model.
    verified_root_cause_key: str
    investigation_id: str
    model_a: LiveModelResult
    model_b: LiveModelResult

    def to_payload(self) -> dict[str, Any]:
        return {
            "issue_number": self.issue_number,
            "title": self.title,
            "verified_root_cause_key": self.verified_root_cause_key,
            "investigation_id": self.investigation_id,
            "model_a": self.model_a.to_payload(),
            "model_b": self.model_b.to_payload(),
        }


@dataclass(frozen=True, slots=True)
class LiveBenchmarkAggregate:
    bugs_evaluated: int
    investigations_completed: int
    stopped_early: bool
    stop_reason: str | None
    verifier_accepted_rate: float | None
    mean_latency_seconds: float | None
    total_tokens_used: int
    total_verified_cost_usd: float
    spend_ceiling_usd: float
    # Not measured live: the model returns a proposal plan, not a root-cause
    # key, so manufacturing a detection boolean would be dishonest. Adjudication
    # against verified_root_cause_key is a separate owner-review step.
    detection_accuracy: None = None
    detection_adjudication: str = "pending-owner-review"

    def to_payload(self) -> dict[str, Any]:
        return {
            "bugs_evaluated": self.bugs_evaluated,
            "investigations_completed": self.investigations_completed,
            "stopped_early": self.stopped_early,
            "stop_reason": self.stop_reason,
            "verifier_accepted_rate": self.verifier_accepted_rate,
            "mean_latency_seconds": self.mean_latency_seconds,
            "total_tokens_used": self.total_tokens_used,
            "total_verified_cost_usd": self.total_verified_cost_usd,
            "spend_ceiling_usd": self.spend_ceiling_usd,
            "detection_accuracy": self.detection_accuracy,
            "detection_adjudication": self.detection_adjudication,
        }


@dataclass(frozen=True, slots=True)
class LiveBenchmarkReport:
    bugs: tuple[LiveBugResult, ...]
    aggregate: LiveBenchmarkAggregate

    def to_payload(self) -> dict[str, Any]:
        return {
            "bugs": [bug.to_payload() for bug in self.bugs],
            "aggregate": self.aggregate.to_payload(),
        }


def run_live_benchmark(
    corpus: Sequence[Mapping[str, Any]],
    config: OpenRouterConfig | None,
    *,
    transport: Callable[..., Any] | None = None,
    catalog_fetcher: Callable[[], dict[str, Any]] | None = None,
    generation_cost_fetcher: GenerationFetcher | None = None,
) -> LiveBenchmarkReport:
    """Run the live free-model benchmark over every corpus entry.

    Refused without live approval (see :func:`_require_live_approval`). The
    ``/models`` catalog is fetched at runner start (fail closed on failure);
    the gate re-verifies pricing before EVERY invocation and fails closed on a
    mid-run re-fetch failure. A pricing-gate defect (pre- or post-call) stops
    the run: the free-model assumption is violated and further invocations
    would risk spend. The spend ceiling is a defense-in-depth backstop checked
    after each bug. ``transport`` / ``catalog_fetcher`` /
    ``generation_cost_fetcher`` are injectable so tests stay zero-network;
    when omitted the runner uses live urllib transports.
    """
    from .investigation import run_dual_investigation

    _require_live_approval(config)
    assert isinstance(config, OpenRouterConfig)  # narrowed by _require_live_approval

    fetch_catalog = catalog_fetcher or (
        lambda: fetch_models_catalog(config.models_endpoint, config.timeout_seconds)
    )
    try:
        catalog = fetch_catalog()
    except OpenRouterPricingGateError:
        raise
    except Exception as exc:  # noqa: BLE001 -- any fetch failure fails closed
        raise OpenRouterPricingGateError(
            "live benchmark refused: initial /models catalog fetch failed: "
            f"{type(exc).__name__}"
        ) from None
    gate = FreeModelPricingGate(catalog, catalog_refetch=fetch_catalog)

    # Pre-flight: fail fast on a mispriced/misconfigured model before any bug.
    gate.verify_model_is_free(config.model_a)
    gate.verify_model_is_free(config.model_b)

    fetch_generation = generation_cost_fetcher or _default_generation_cost_fetcher(config)

    bugs: list[LiveBugResult] = []
    total_verified_cost_usd = 0.0
    stopped_early = False
    stop_reason: str | None = None

    for entry in corpus:
        request = _corpus_entry_to_live_request(entry)
        dual = run_dual_investigation(
            request,
            config,
            transport=transport,
            pricing_gate=gate,
            generation_cost_fetcher=fetch_generation,
        )
        bug = _live_bug_result(entry, dual)
        bugs.append(bug)
        total_verified_cost_usd += _live_bug_verified_cost_usd(bug)

        defect = _pricing_gate_defect(bug)
        if defect is not None:
            stopped_early = True
            stop_reason = f"pricing-gate defect; run stopped fail-closed: {defect}"
            break
        if _spend_ceiling_exceeded(total_verified_cost_usd, config.spend_ceiling_usd):
            stopped_early = True
            stop_reason = (
                f"spend ceiling exceeded: cumulative verified cost "
                f"{total_verified_cost_usd} > {config.spend_ceiling_usd}"
            )
            break

    return LiveBenchmarkReport(
        bugs=tuple(bugs),
        aggregate=_live_aggregate(
            tuple(bugs), stopped_early, stop_reason,
            total_verified_cost_usd, config.spend_ceiling_usd,
        ),
    )


def _default_generation_cost_fetcher(config: OpenRouterConfig) -> GenerationFetcher:
    """Live /generation lookup. The key is read from the environment at call
    time only -- never stored, never logged."""

    def _fetch(generation_id: str) -> dict[str, Any]:
        api_key = os.environ.get(config.api_key_env_var, "")
        return fetch_generation_record(
            config.generation_endpoint, api_key, generation_id, config.timeout_seconds
        )

    return _fetch


def _corpus_entry_to_live_request(entry: Mapping[str, Any]) -> Any:
    """Build a kernel-valid ProposalRequest for one corpus bug.

    The verified root cause, its key, and the detection criteria are NEVER
    included -- the model must investigate from the bug title and evidence
    pointers only. SHAs and the authorization fingerprint are deterministic
    harness-synthesized values (not repo state); authorization is the harness
    operator's own assertion. Production activation stays separately gated.
    """
    from scripts.agent_os_pr_remediation import models as models_kernel
    from scripts.agent_os_pr_remediation.high_reasoning_proposal import (
        REQUEST_SCHEMA_VERSION,
        ProposalRequest,
        ProposalType,
    )

    issue_number = int(entry["issue_number"])
    title = str(entry["title"])
    seed = models_kernel.canonical_json(
        {"benchmark": "openrouter-live", "issue_number": issue_number, "title": title}
    ).encode("utf-8")
    source_sha = hashlib.sha1(b"source-sha:" + seed).hexdigest()
    authorization_fingerprint = hashlib.sha256(b"authorization:" + seed).hexdigest()
    source_fingerprint = hashlib.sha256(b"source-fingerprint:" + seed).hexdigest()
    evidence_refs = [str(ref) for ref in entry.get("evidence_refs", [])]
    allowed_paths = _derive_allowed_paths(evidence_refs)
    objective = (
        f"Investigate the reported defect in Blummer92/agent-os issue #{issue_number}: "
        f"{title}. Determine the root cause from the referenced evidence and propose "
        "a bounded repair plan. Do not execute anything; produce the plan only."
    )
    return ProposalRequest(
        schema_version=REQUEST_SCHEMA_VERSION,
        repository="Blummer92/agent-os",
        issue_number=issue_number,
        pr_number=None,
        invocation_id=f"openrouter-live-benchmark-issue-{issue_number}",
        source_sha=source_sha,
        observed_source_sha=source_sha,
        base_branch="main",
        base_sha=None,
        objective=objective,
        non_goals=("No execution.", "No GitHub mutation.", "No production changes."),
        allowed_paths=tuple(allowed_paths),
        forbidden_paths=(".github/",),
        required_validations=("pytest-focused",),
        required_prohibited_changes=("No production changes without owner approval.",),
        blockers=(),
        changed_paths=(),
        compute_route="high-reasoning-required",
        authorization_state="authorized",
        authorization_fingerprint=authorization_fingerprint,
        proposal_type=ProposalType.EXECUTION,
        contract_versions=("prr2:1.0",),
        source_fingerprints=(source_fingerprint,),
        normalized_evidence_refs=tuple(evidence_refs) if evidence_refs else ("evidence:openrouter-live-benchmark",),
        provider_capability_requirements=("high-reasoning",),
        human_evidence_state="clear",
    )


def _derive_allowed_paths(evidence_refs: Sequence[str]) -> list[str]:
    """Scope proposals to the top-level areas the corpus evidence points at.

    URL refs are pointers, not paths, and are skipped. A root-level file ref
    is used verbatim; deeper refs contribute their top-level directory prefix.
    Falls back to ``scripts/`` when no ref names a repo path.
    """
    prefixes: set[str] = set()
    for ref in evidence_refs:
        if "://" in ref or not ref.strip():
            continue
        ref = ref.strip().lstrip("/")
        if "/" in ref:
            prefixes.add(ref.split("/", 1)[0] + "/")
        else:
            prefixes.add(ref)
    if not prefixes:
        prefixes.add("scripts/")
    return sorted(prefixes)


def _live_bug_result(entry: Mapping[str, Any], dual: Any) -> LiveBugResult:
    return LiveBugResult(
        issue_number=int(entry["issue_number"]),
        title=str(entry["title"]),
        verified_root_cause_key=str(entry["verified_root_cause_key"]),
        investigation_id=dual.investigation_id,
        model_a=_live_model_result(dual.model_a),
        model_b=_live_model_result(dual.model_b),
    )


def _live_model_result(outcome: Any) -> LiveModelResult:
    return LiveModelResult(
        model_identity=outcome.model_identity,
        pricing_evidence=outcome.pricing_evidence,
        outcome=outcome.outcome,
        reason_codes=tuple(outcome.reason_codes),
        plan_id=outcome.plan_id,
        tokens_used=outcome.tokens_used,
        latency_seconds=outcome.latency_seconds,
        retries=outcome.retries,
        generation_cost_evidence=outcome.generation_cost_evidence,
        pricing_gate_defect=outcome.pricing_gate_defect,
        adapter_invoked=outcome.adapter_invoked,
        error=outcome.error,
    )


def _pricing_gate_defect(bug: LiveBugResult) -> str | None:
    """Return the pricing-gate defect if either model's outcome records one.

    The kernel maps the gate's exception to NEEDS_DECISION / provider.failure
    with error=None, so detection uses the adapter-recorded defect flag, not
    the error string.
    """
    for model_result in (bug.model_a, bug.model_b):
        defect = model_result.pricing_gate_defect
        if isinstance(defect, str) and defect:
            return f"{model_result.model_identity}: {defect}"
    return None


def _live_bug_verified_cost_usd(bug: LiveBugResult) -> float:
    total = 0.0
    for model_result in (bug.model_a, bug.model_b):
        evidence = model_result.generation_cost_evidence
        if isinstance(evidence, dict):
            total += float(evidence.get("total_cost", 0.0) or 0.0)
    return total


def _spend_ceiling_exceeded(cumulative_usd: float, ceiling_usd: float) -> bool:
    """Defense-in-depth backstop: stop the run if cumulative verified cost
    exceeds the ceiling. (Nonzero costs raise in the gate first, so in
    practice this only fires on a logic defect -- which is exactly when a
    backstop matters.)"""
    return cumulative_usd > ceiling_usd


def _live_aggregate(
    bugs: Sequence[LiveBugResult],
    stopped_early: bool,
    stop_reason: str | None,
    total_verified_cost_usd: float,
    spend_ceiling_usd: float,
) -> LiveBenchmarkAggregate:
    from scripts.agent_os_pr_remediation.high_reasoning_proposal import ProposalOutcome

    outcomes = [bug.model_a for bug in bugs] + [bug.model_b for bug in bugs]
    accepted = [o for o in outcomes if o.outcome == ProposalOutcome.ACCEPTED.value]
    latencies = [o.latency_seconds for o in outcomes]
    return LiveBenchmarkAggregate(
        bugs_evaluated=len(bugs),
        investigations_completed=len(outcomes),
        stopped_early=stopped_early,
        stop_reason=stop_reason,
        verifier_accepted_rate=(len(accepted) / len(outcomes)) if outcomes else None,
        mean_latency_seconds=(sum(latencies) / len(latencies)) if latencies else None,
        total_tokens_used=sum(o.tokens_used for o in outcomes),
        total_verified_cost_usd=total_verified_cost_usd,
        spend_ceiling_usd=spend_ceiling_usd,
    )


def _benchmark_bug(entry: Mapping[str, Any], runner: OfflineRunner) -> BugBenchmarkResult:
    verified_key = entry["verified_root_cause_key"]
    prices = entry["estimated_cost_usd_per_1k_tokens"]
    results = {}
    for role in MODEL_ROLES:
        observed = runner(entry, role)
        tokens = int(observed["tokens_used"])
        results[role] = ModelBenchmarkResult(
            model_role=role,
            predicted_root_cause_key=str(observed["predicted_root_cause_key"]),
            detected=str(observed["predicted_root_cause_key"]) == verified_key,
            time_to_root_cause_seconds=_optional_float(observed.get("time_to_root_cause_seconds")),
            false_positives=int(observed["false_positives"]),
            tokens_used=tokens,
            estimated_cost_usd=(tokens / 1000.0) * float(prices[role]),
            kernel_verifier_accepted=observed["kernel_verifier_outcome"] == "accepted",
        )
    return BugBenchmarkResult(
        issue_number=int(entry["issue_number"]),
        title=str(entry["title"]),
        model_a=results["model_a"],
        model_b=results["model_b"],
    )


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _aggregate(bugs: Sequence[BugBenchmarkResult]) -> BenchmarkAggregate:
    observations = [bug.model_a for bug in bugs] + [bug.model_b for bug in bugs]
    times = [o.time_to_root_cause_seconds for o in observations if o.time_to_root_cause_seconds is not None]
    return BenchmarkAggregate(
        bugs_evaluated=len(bugs),
        detection_accuracy=(sum(1 for o in observations if o.detected) / len(observations)) if observations else 0.0,
        mean_time_to_root_cause_seconds=(sum(times) / len(times)) if times else None,
        total_false_positives=sum(o.false_positives for o in observations),
        total_tokens_used=sum(o.tokens_used for o in observations),
        total_estimated_cost_usd=sum(o.estimated_cost_usd for o in observations),
        kernel_verifier_accepted_rate=(
            sum(1 for o in observations if o.kernel_verifier_accepted) / len(observations)
        ) if observations else 0.0,
    )


def default_corpus_path() -> Path:
    return Path(__file__).resolve().parent / "benchmark_corpus.json"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenRouter pilot benchmark (offline default; --live runs the gated free-model comparison).")
    parser.add_argument("--corpus", default=str(default_corpus_path()))
    parser.add_argument("--live", action="store_true",
                        help="run the live two-model comparison through the free-model pricing gate "
                             f"(requires {LIVE_BENCHMARK_ENV_VAR}='true' and an enabled, keyed pilot config)")
    parser.add_argument("--output", default=None, help="write the JSON report to this path")
    args = parser.parse_args(argv)

    corpus = load_corpus(args.corpus)
    config = OpenRouterConfig.from_env() if args.live else None
    report = run_benchmark(corpus, live=args.live, config=config)
    payload = json.dumps(report.to_payload(), indent=1, sort_keys=True)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
