"""Offline evaluation runner for #3337 (AN-MR2).

Compares candidate identities against identical canonical packets:

- every provider must be a ``MockModelProvider``; anything else raises
  ``LiveCallRefusedError`` before any execution attempt;
- every run carries a run identity bound to the packet digest, the
  candidate identity, and the run number; if a packet digest changed
  between runs the comparison is marked non-comparable;
- unsupported configurations (a candidate requesting a reasoning setting
  its policy marks unsupported) are recorded as
  ``unsupported_configuration`` exclusions without execution;
- the report is component evidence only: per-run metrics, per-family and
  overall aggregates with explicit denominators, and a comparability
  verdict. No universal "best model" score is emitted.

Latency is measured wall-clock around the mock ``run`` call; cost is
measured $0.00 offline and never projected to live costs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .metrics import AggregateMetrics, RunMetrics, aggregate, score_run
from .providers import (
    LiveCallRefusedError,
    LiveModelProvider,
    MockModelProvider,
    ProviderObservation,
    load_candidates,
    load_policies,
    provider_for,
)
from .task_packets import TaskPacket, load_packets, verify_packets_frozen

REPORT_SCHEMA_VERSION = "1.0"

DISCLAIMER = (
    "Component evidence only. These measurements describe fixture/mock "
    "transcripts against frozen canonical task packets; they are not a "
    "universal 'best model' score, not live provider evidence, and grant "
    "no execution, readiness, merge, or closure authority."
)


@dataclass(frozen=True, slots=True)
class RunRecord:
    """One recorded candidate x packet run."""

    run_id: str
    identity_id: str
    packet_id: str
    packet_digest: str
    run_number: int
    comparable: bool
    transcript_digest: str
    metrics: RunMetrics
    candidate_capabilities_unknown: bool


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    """The full component-evidence report of one evaluation pass."""

    schema_version: str
    generated_at: str
    disclaimer: str
    comparability: str
    packet_digests: dict[str, str]
    runs: tuple[RunRecord, ...]
    aggregate: AggregateMetrics
    per_family: dict[str, AggregateMetrics]
    unsupported_configurations: tuple[tuple[str, str], ...] = ()


def run_identity(packet_digest: str, identity_id: str, run_number: int) -> str:
    """Deterministic run identity binding packet content, candidate, and run."""
    material = f"eval-run:v1\0{packet_digest}|{identity_id}|{run_number}"
    return f"eval-run:{hashlib.sha256(material.encode('utf-8')).hexdigest()}"


class EvaluationRunner:
    """Runs fixture-only evaluations across candidates and packets."""

    def __init__(self, runs_per_candidate: int = 1) -> None:
        if not isinstance(runs_per_candidate, int) or runs_per_candidate < 1:
            raise ValueError("runs_per_candidate must be a positive integer")
        self._runs_per_candidate = runs_per_candidate

    def _check_provider(self, provider: object) -> MockModelProvider:
        if isinstance(provider, LiveModelProvider):
            raise LiveCallRefusedError(
                "live provider refused: the #3337 harness executes fixture/mock "
                "providers only"
            )
        if not isinstance(provider, MockModelProvider):
            raise LiveCallRefusedError(
                f"refusing unknown provider type {type(provider).__name__}: "
                "only fixture/mock providers may execute"
            )
        return provider

    def run(
        self,
        providers: Sequence[object],
        packets: Sequence[TaskPacket],
    ) -> EvaluationReport:
        """Execute every candidate against every packet and score the runs."""
        mocks = [self._check_provider(provider) for provider in providers]
        packet_list = list(packets)
        if not packet_list:
            raise ValueError("no packets supplied")
        packet_digests = verify_packets_frozen(tuple(packet_list))

        policies = load_policies()
        unsupported: list[tuple[str, str]] = []
        records: list[RunRecord] = []
        metrics: list[RunMetrics] = []

        for mock in mocks:
            identity = mock.identity
            policy = policies.get(identity.identity_id)
            if identity.reasoning_setting in (policy.unsupported_settings if policy else ()):
                unsupported.append((identity.identity_id, identity.reasoning_setting))
                continue
            for packet in packet_list:
                for run_number in range(1, self._runs_per_candidate + 1):
                    record = self._run_once(mock, packet, run_number, packet_digests)
                    records.append(record)
                    metrics.append(record.metrics)

        per_family: dict[str, AggregateMetrics] = {}
        families = sorted({record.packet_id.split("-")[0].upper() for record in records})
        for family in families:
            per_family[family] = aggregate(
                [record.metrics for record in records if record.packet_id.startswith(family.lower())]
            )

        comparable = all(record.comparable for record in records)
        return EvaluationReport(
            schema_version=REPORT_SCHEMA_VERSION,
            generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            disclaimer=DISCLAIMER,
            comparability="comparable" if comparable else "non-comparable",
            packet_digests=packet_digests,
            runs=tuple(records),
            aggregate=aggregate(metrics),
            per_family=per_family,
            unsupported_configurations=tuple(unsupported),
        )

    def _run_once(
        self,
        mock: MockModelProvider,
        packet: TaskPacket,
        run_number: int,
        packet_digests: dict[str, str],
    ) -> RunRecord:
        identity = mock.identity
        digest = packet_digests[packet.packet_id]
        start = time.perf_counter()
        observation: ProviderObservation = mock.run(packet)
        latency_ms = (time.perf_counter() - start) * 1000.0
        run_metrics = score_run(packet, observation, latency_ms)
        return RunRecord(
            run_id=run_identity(digest, identity.identity_id, run_number),
            identity_id=identity.identity_id,
            packet_id=packet.packet_id,
            packet_digest=digest,
            run_number=run_number,
            comparable=True,
            transcript_digest=observation.transcript_digest,
            metrics=run_metrics,
            candidate_capabilities_unknown=identity.capabilities_unknown,
        )


def _metrics_payload(item: RunMetrics) -> dict[str, Any]:
    return {
        "accuracy": item.accuracy,
        "unsupported_claim_rate": item.unsupported_claim_rate,
        "governance_adherence": item.governance_adherence,
        "latency_ms_measured": item.latency_ms_measured,
        "latency_basis": item.latency_basis,
        "cost_usd_measured": item.cost_usd_measured,
        "cost_basis": item.cost_basis,
        "tokens_fixture": item.tokens_fixture,
        "tokens_basis": item.tokens_basis,
        "valid": item.valid,
        "exclusion_reason": item.exclusion_reason,
    }


def _aggregate_payload(item: AggregateMetrics) -> dict[str, Any]:
    return {
        "n_total": item.n_total,
        "n_valid": item.n_valid,
        "n_excluded": item.n_excluded,
        "exclusions": list(item.exclusions),
        "mean_accuracy": item.mean_accuracy,
        "mean_unsupported_claim_rate": item.mean_unsupported_claim_rate,
        "mean_governance_adherence": item.mean_governance_adherence,
        "mean_latency_ms_measured": item.mean_latency_ms_measured,
        "total_cost_usd_measured": item.total_cost_usd_measured,
        "cost_basis": item.cost_basis,
    }


def render_report(report: EvaluationReport) -> dict[str, Any]:
    """Render the report as JSON-serializable component evidence."""
    return {
        "schema_version": report.schema_version,
        "generated_at": report.generated_at,
        "disclaimer": report.disclaimer,
        "comparability": report.comparability,
        "packet_digests": report.packet_digests,
        "runs": [
            {
                "run_id": record.run_id,
                "identity_id": record.identity_id,
                "packet_id": record.packet_id,
                "packet_digest": record.packet_digest,
                "run_number": record.run_number,
                "comparable": record.comparable,
                "transcript_digest": record.transcript_digest,
                "candidate_capabilities_unknown": record.candidate_capabilities_unknown,
                "metrics": _metrics_payload(record.metrics),
            }
            for record in report.runs
        ],
        "aggregate": _aggregate_payload(report.aggregate),
        "per_family": {
            family: _aggregate_payload(item) for family, item in report.per_family.items()
        },
        "unsupported_configurations": list(report.unsupported_configurations),
    }


def write_report(report: EvaluationReport, path: str | Path) -> Path:
    """Persist the rendered report as canonical JSON."""
    target = Path(path)
    target.write_text(
        json.dumps(render_report(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def main(argv: Sequence[str] | None = None) -> int:
    """Run every candidate against every packet and print the evidence summary."""
    parser = argparse.ArgumentParser(description="Offline #3337 model x reasoning evaluation")
    parser.add_argument("--out", default=None, help="Write the full JSON report to this path")
    parser.add_argument("--runs", type=int, default=1, help="Runs per candidate x packet")
    args = parser.parse_args(argv)

    packets = load_packets()
    candidates = load_candidates()
    policies = load_policies()
    providers = [provider_for(identity_id, candidates, policies) for identity_id in candidates]
    report = EvaluationRunner(runs_per_candidate=args.runs).run(providers, packets)
    summary = {
        "disclaimer": report.disclaimer,
        "comparability": report.comparability,
        "n_runs": len(report.runs),
        "aggregate": _aggregate_payload(report.aggregate),
        "per_family_mean_accuracy": {
            family: item.mean_accuracy for family, item in report.per_family.items()
        },
        "unsupported_configurations": list(report.unsupported_configurations),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    if args.out:
        write_report(report, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
