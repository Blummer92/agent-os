"""Offline benchmark harness for the OpenRouter pilot (#3637).

Compares the dual-model investigation pipeline against a corpus of previously
verified Agent OS bugs (``benchmark_corpus.json``). Default mode is fully
offline: an injectable runner replays canned per-bug model transcripts from
the corpus fixtures, so no network call is ever made in tests.

Metrics per bug and in aggregate:
- time to verified root cause (simulated from fixture transcripts offline)
- detection accuracy (predicted root-cause key vs the verified key)
- false positives count
- token usage and estimated cost (per-model reference price in the fixture)
- regression-test success as the kernel verifier ACCEPTED rate

The ``--live`` path exists but refuses to run unless
``OPENROUTER_BENCHMARK_LIVE_APPROVED`` is exactly ``"true"`` AND the pilot
config is enabled and keyed. Even then, the live two-model comparison is a
prepared-but-unexecuted plan pending owner approval for API spend: the harness
raises instead of calling the network.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .config import LIVE_BENCHMARK_ENV_VAR, OpenRouterConfig

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


class LiveBenchmarkNotExecuted(RuntimeError):
    """Live comparison is a prepared-but-unexecuted plan; no network is called."""


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
) -> BenchmarkReport:
    """Execute the benchmark over every corpus entry.

    Offline by default. ``live=True`` is refused unless the live-approval env
    var is exactly "true" and the pilot config is enabled and keyed; even then
    the live comparison is unexecuted by design (see module docstring).
    """
    if live:
        _require_live_approval(config)
        raise LiveBenchmarkNotExecuted(
            "the live two-model comparison is a prepared-but-unexecuted plan "
            "pending owner approval for API spend; no network call was made"
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
    parser = argparse.ArgumentParser(description="Offline OpenRouter pilot benchmark.")
    parser.add_argument("--corpus", default=str(default_corpus_path()))
    parser.add_argument("--live", action="store_true",
                        help="request the live two-model comparison (refused without approvals)")
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
