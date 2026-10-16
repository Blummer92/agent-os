"""Tests for the #3337 fixture-first model x reasoning evaluation harness.

Covers fixture determinism, the fail-closed no-network guarantee, mock
provider comparison, metrics recording, and the AN-MR1 semantic reuse.
"""

from __future__ import annotations

import socket
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.agent_os_model_reasoning_eval import (
    EvaluationRunner,
    LiveCallRefusedError,
    MockModelProvider,
    load_candidates,
    load_packets,
    score_run,
)
from scripts.agent_os_model_reasoning_eval.metrics import (
    COST_BASIS,
    detect_authority_bearing,
    score_field,
)
from scripts.agent_os_model_reasoning_eval.providers import (
    LiveModelProvider,
    ScriptedTranscriptPolicy,
    provider_for,
    scripted_transcript,
)
from scripts.agent_os_model_reasoning_eval.runner import (
    DISCLAIMER,
    render_report,
    run_identity,
)
from scripts.agent_os_model_reasoning_eval.task_packets import (
    PacketError,
    TaskFamily,
    packet_content_digest,
    verify_packets_frozen,
)

PACKAGE_DIR = Path(__file__).resolve().parent.parent.parent / "scripts" / "agent_os_model_reasoning_eval"

BANNED_USAGE_PATTERNS = (
    "import httpx",
    "from httpx",
    "import requests",
    "from requests",
    "urllib.request",
    "import aiohttp",
    "from aiohttp",
    "import socket",
    "from socket",
    "socket.",
    "import websocket",
    "from websocket",
)


def _strip_docstrings_and_comments(text: str) -> str:
    """Remove triple-quoted docstrings and # comments so prose cannot trip the scan."""
    import re

    no_docstrings = re.sub(r'"""[\s\S]*?"""', "", text)
    return "\n".join(line.split("#", 1)[0] for line in no_docstrings.splitlines())


# ---------------------------------------------------------------------------
# Fixture determinism
# ---------------------------------------------------------------------------


def test_packet_digests_stable_across_loads():
    first = verify_packets_frozen(load_packets())
    second = verify_packets_frozen(load_packets())
    assert first == second
    assert len(first) == 14


def test_packet_digest_changes_when_content_changes():
    packets = load_packets()
    packet = packets[0]
    raw = {
        "packet_id": packet.packet_id,
        "scored_fields": [
            {"name": f.name, "kind": f.kind, "expected": "CHANGED"}
            for f in packet.scored_fields
        ],
    }
    assert packet_content_digest(raw) != packet.packet_digest


def test_all_seven_families_present_with_two_packets_each():
    packets = load_packets()
    families = {packet.family for packet in packets}
    assert families == set(TaskFamily)
    for family in TaskFamily:
        assert sum(1 for packet in packets if packet.family is family) == 2


def test_packets_reuse_an_mr1_semantics():
    from agent_os_execution_service.reasoning_profile import ReasoningEffort, TaskClass

    for packet in load_packets():
        assert type(packet.task_class) is TaskClass
        assert type(packet.reasoning_effort) is ReasoningEffort


def test_malformed_packet_rejected():
    with pytest.raises(PacketError):
        packet_content_digest({"packet_id": "x"})  # missing scored_fields


def test_mock_transcripts_deterministic():
    packets = load_packets()
    packet = packets[0]
    provider = provider_for("claude-sonnet-medium")
    first = provider.run(packet)
    second = provider.run(packet)
    assert first.transcript_digest == second.transcript_digest
    assert first.output_fields == second.output_fields


def test_run_identity_stable_and_sensitive_to_inputs():
    packets = load_packets()
    packet = packets[0]
    first = run_identity(packet.packet_digest, "claude-sonnet-medium", 1)
    assert first == run_identity(packet.packet_digest, "claude-sonnet-medium", 1)
    assert first != run_identity(packet.packet_digest, "claude-sonnet-medium", 2)
    assert first != run_identity(packet.packet_digest, "gpt-6-luna-standard", 1)


# ---------------------------------------------------------------------------
# Fail-closed: no network
# ---------------------------------------------------------------------------


def test_no_network_imports_in_package():
    for path in sorted(PACKAGE_DIR.glob("*.py")):
        code = _strip_docstrings_and_comments(path.read_text(encoding="utf-8"))
        for banned in BANNED_USAGE_PATTERNS:
            assert banned not in code, f"{path.name} uses banned network API {banned}"


def test_live_provider_run_refuses():
    provider = LiveModelProvider(load_candidates()["gpt-6-luna-standard"])
    with pytest.raises(LiveCallRefusedError):
        provider.run(load_packets()[0])


def test_runner_rejects_non_mock_provider():
    packets = load_packets()
    live = LiveModelProvider(load_candidates()["gpt-6-luna-standard"])
    with pytest.raises(LiveCallRefusedError):
        EvaluationRunner().run([live], packets)


def test_runner_rejects_unknown_provider_type():
    with pytest.raises(LiveCallRefusedError):
        EvaluationRunner().run([object()], load_packets())


def test_full_evaluation_runs_with_sockets_disabled(monkeypatch):
    def _blocked(*args, **kwargs):
        raise AssertionError("network socket use is forbidden in the offline harness")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    packets = load_packets()
    candidates = load_candidates()
    providers = [provider_for(identity_id, candidates) for identity_id in candidates]
    report = EvaluationRunner().run(providers, packets)
    assert report.comparability == "comparable"
    assert report.aggregate.n_total > 0


# ---------------------------------------------------------------------------
# Mock provider comparison
# ---------------------------------------------------------------------------


def test_identical_packets_are_comparable_across_candidates():
    packets = load_packets()
    candidates = load_candidates()
    providers = [provider_for(identity_id, candidates) for identity_id in candidates]
    report = EvaluationRunner().run(providers, packets)
    digests = {record.packet_digest for record in report.runs if record.packet_id == "t1-extract-01"}
    assert len(digests) == 1
    assert all(record.comparable for record in report.runs)


def test_candidate_identities_representable_without_fabrication():
    candidates = load_candidates()
    assert len(candidates) == 10
    muse = candidates["muse-standard"]
    assert muse.capabilities_unknown is True
    assert candidates["claude-fable-maximum"].availability == "unknown"


def _policy_with_unsupported_setting():
    return {
        "muse-standard": ScriptedTranscriptPolicy(
            identity_id="muse-standard",
            family_competence={f"T{i}": 80 for i in range(1, 8)},
            unsupported_settings=("maximum",),
            overrides={},
        )
    }


def test_unsupported_reasoning_setting_recorded(monkeypatch):
    packets = load_packets()
    identity = replace(load_candidates()["muse-standard"], reasoning_setting="maximum")
    policies = _policy_with_unsupported_setting()
    import scripts.agent_os_model_reasoning_eval.runner as runner_module

    monkeypatch.setattr(runner_module, "load_policies", lambda: policies)
    report = EvaluationRunner().run(
        [MockModelProvider(identity, policies["muse-standard"])], packets
    )
    assert ("muse-standard", "maximum") in report.unsupported_configurations
    assert report.aggregate.n_total == 0


def test_supported_reasoning_setting_executes(monkeypatch):
    packets = load_packets()
    identity = load_candidates()["muse-standard"]
    policies = _policy_with_unsupported_setting()
    import scripts.agent_os_model_reasoning_eval.runner as runner_module

    monkeypatch.setattr(runner_module, "load_policies", lambda: policies)
    report = EvaluationRunner().run(
        [MockModelProvider(identity, policies["muse-standard"])], packets
    )
    assert report.unsupported_configurations == ()
    assert report.aggregate.n_valid == len(packets)


# ---------------------------------------------------------------------------
# Metrics recording
# ---------------------------------------------------------------------------


def test_run_metrics_recorded_for_valid_transcript():
    packets = load_packets()
    packet = next(p for p in packets if p.packet_id == "t1-extract-01")
    provider = provider_for("gpt-5.6-sol-low")
    observation = provider.run(packet)
    metrics = score_run(packet, observation, latency_ms_measured=1.5)
    assert metrics.valid is True
    assert metrics.cost_usd_measured == 0.0
    assert metrics.cost_basis == COST_BASIS
    assert metrics.latency_ms_measured == 1.5
    assert 0.0 <= metrics.accuracy <= 1.0


def test_measured_zero_cost_never_projected():
    packets = load_packets()
    candidates = load_candidates()
    providers = [provider_for(identity_id, candidates) for identity_id in candidates]
    report = EvaluationRunner().run(providers, packets)
    assert report.aggregate.total_cost_usd_measured == 0.0
    assert report.aggregate.cost_basis == COST_BASIS
    for record in report.runs:
        assert record.metrics.cost_usd_measured == 0.0
        assert record.metrics.cost_basis == COST_BASIS


def test_keyset_scoring_fractional():
    packets = load_packets()
    packet = next(p for p in packets if p.packet_id == "t3-implement-01")
    field = next(f for f in packet.scored_fields if f.name == "algorithm")
    assert score_field(field, "sha256 canonical sort_keys") == 1.0
    assert score_field(field, "sha256 only") == pytest.approx(1 / 3)


def test_authority_bearing_output_fails_closed():
    packets = load_packets()
    packet = next(p for p in packets if p.packet_id == "t5-architect-01")
    provider = provider_for("gpt-6-astra-maximum")
    observation = provider.run(packet)
    assert detect_authority_bearing(observation.output_fields) is True
    metrics = score_run(packet, observation, latency_ms_measured=2.0)
    assert metrics.valid is False
    assert metrics.exclusion_reason == "authority-bearing-output"
    assert metrics.governance_adherence == 0.0


def test_contaminated_run_excluded_explicitly():
    packets = load_packets()
    packet = next(p for p in packets if p.packet_id == "t6-review-02")
    provider = provider_for("claude-fable-maximum")
    observation = provider.run(packet)
    assert observation.contaminated is True
    metrics = score_run(packet, observation, latency_ms_measured=2.0)
    assert metrics.valid is False
    assert metrics.exclusion_reason == "contaminated-run"


def test_aggregate_reports_denominators_and_exclusions():
    packets = load_packets()
    candidates = load_candidates()
    providers = [provider_for(identity_id, candidates) for identity_id in candidates]
    report = EvaluationRunner().run(providers, packets)
    aggregate = report.aggregate
    assert aggregate.n_total == aggregate.n_valid + aggregate.n_excluded
    assert aggregate.n_excluded >= 2  # authority-bearing + contaminated fixtures
    reasons = dict(aggregate.exclusions)
    assert "authority-bearing-output" in reasons
    assert "contaminated-run" in reasons
    assert "component evidence only" in DISCLAIMER.lower()


def test_report_renders_without_universal_best_score():
    packets = load_packets()
    candidates = load_candidates()
    providers = [provider_for(identity_id, candidates) for identity_id in candidates]
    report = EvaluationRunner().run(providers, packets)
    payload = render_report(report)
    serialized = str(payload).lower()
    # The disclaimer names "best model" only to disavow it; the report must
    # carry no ranking field or winner claim of its own.
    assert '"best_model"' not in serialized
    assert '"winner"' not in serialized
    assert '"ranking"' not in serialized
    assert payload["disclaimer"] == DISCLAIMER
    assert payload["comparability"] == "comparable"
    assert len(payload["per_family"]) == 7
