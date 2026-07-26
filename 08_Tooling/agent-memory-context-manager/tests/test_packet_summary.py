import copy
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_memory_context_manager import (  # noqa: E402
    build_handoff_packet,
    summarize_handoff_packet,
)
from agent_memory_context_manager.packet_summary import (  # noqa: E402
    RENDERER_VERSION,
    REASON_PRODUCER_INVALID,
    REASON_PROVENANCE_CONTRADICTORY,
    REASON_PROVENANCE_DETACHED,
    REASON_PROVENANCE_MALFORMED,
    REASON_PROVENANCE_MISSING,
    REASON_PROVENANCE_STATUS_INVALID,
    REASON_RENDERER_VERSION_UNSUPPORTED,
    REASON_SCHEMA_VERSION_UNSUPPORTED,
    REASON_SOURCE_FINGERPRINT_MISMATCH,
    SUPPORTED_PACKET_SCHEMA_VERSION,
    TRUST_CURRENT,
    TRUST_STALE,
    TRUST_UNSUPPORTED,
    TRUST_UNVERIFIABLE,
    RenderingEvidence,
)


def sample_packet(**overrides):
    fields = dict(
        objective="Summarize packets for lower-compute agent handoffs",
        current_phase="Memory H2",
        branch="claude/agent-memory-context-manager-1c-packet-summary-helpers",
        pr_number=0,
        changed_files=[
            "file-1.py",
            "file-2.py",
            "file-3.py",
            "file-4.py",
        ],
        allowed_inspect_first=[
            "README.md",
            "handoff_packet.py",
            "packet_validation.py",
            "packet_summary.py",
        ],
        forbidden_unless_needed=[
            "Workflow Scheduler source",
            "Executor",
            "TaskAdapter",
        ],
        known_facts=[
            "Memory 1A packet generator is merged",
            "Memory 1B packet validation is merged",
            "Memory H2 summary rendering is in progress",
            "Broad scans should be avoided",
        ],
        prior_decisions=[
            "No Scheduler integration in Memory H2",
            "No connector calls in summary helpers",
            "Keep summaries deterministic",
            "Use targeted tests only",
        ],
        acceptance_criteria=[
            "Summary returns rendering-evidence contract",
            "Forbidden paths and acceptance criteria are visible",
        ],
        validation_commands=[
            "PYTHONPATH=src python -m pytest tests/test_packet_summary.py -q",
            "PYTHONPATH=src python -m pytest tests/test_handoff_packet.py tests/test_packet_validation.py tests/test_packet_summary.py -q",
            "Do not run broad repo tests",
            "Review PR changed files",
        ],
        stop_conditions=[
            "Need to inspect unrelated files",
            "Need Workflow Scheduler integration",
            "Need repo scanning",
            "Need connector calls",
        ],
    )
    fields.update(overrides)
    return build_handoff_packet(**fields)


def current_evidence(packet, **overrides):
    from agent_memory_context_manager.packet_summary import _fingerprint_value

    fields = dict(
        producer="google-workspace-automation-engineer",
        packet_schema_version=SUPPORTED_PACKET_SCHEMA_VERSION,
        renderer_version=RENDERER_VERSION,
        provenance_status="supplied",
        source_fingerprint=_fingerprint_value(packet),
    )
    fields.update(overrides)
    return RenderingEvidence(**fields)


CANONICAL_SECTION_ORDER = [
    "Objective:",
    "Current phase:",
    "Branch:",
    "PR number:",
    "Changed files:",
    "Allowed inspect first:",
    "Forbidden unless needed:",
    "Known facts:",
    "Prior decisions:",
    "Acceptance criteria:",
    "Validation commands:",
    "Compute limits:",
    "Stop conditions:",
]


def test_summary_returns_rendered_result():
    result = summarize_handoff_packet(sample_packet())

    assert isinstance(result.text, str)


def test_canonical_sections_appear_in_deterministic_order():
    result = summarize_handoff_packet(sample_packet())

    positions = [result.text.index(section) for section in CANONICAL_SECTION_ORDER]

    assert positions == sorted(positions)


def test_summary_includes_objective_phase_branch_and_pr_number():
    result = summarize_handoff_packet(sample_packet())

    assert "Objective: Summarize packets for lower-compute agent handoffs" in result.text
    assert "Current phase: Memory H2" in result.text
    assert "Branch: claude/agent-memory-context-manager-1c-packet-summary-helpers" in result.text
    assert "PR number: 0" in result.text


def test_summary_includes_forbidden_unless_needed_and_acceptance_criteria():
    result = summarize_handoff_packet(sample_packet())

    assert "Forbidden unless needed:" in result.text
    assert "- Workflow Scheduler source" in result.text
    assert "Acceptance criteria:" in result.text
    assert "- Summary returns rendering-evidence contract" in result.text


def test_branch_and_pr_number_none_render_truthfully():
    packet = sample_packet(branch=None, pr_number=None)
    result = summarize_handoff_packet(packet)

    assert "Branch: None" in result.text
    assert "PR number: None" in result.text


def test_summary_includes_changed_files():
    result = summarize_handoff_packet(sample_packet())

    assert "Changed files:" in result.text
    assert "- file-1.py" in result.text


def test_summary_respects_list_limit():
    result = summarize_handoff_packet(sample_packet(), list_limit=2)

    assert "- file-1.py" in result.text
    assert "- file-2.py" in result.text
    assert "- file-3.py" not in result.text


def test_summary_includes_and_more_when_list_items_are_truncated():
    result = summarize_handoff_packet(sample_packet(), list_limit=2)

    assert "...and 2 more" in result.text


def test_empty_safety_sections_remain_visible():
    packet = sample_packet(forbidden_unless_needed=[], acceptance_criteria=[])
    result = summarize_handoff_packet(packet)

    assert "Forbidden unless needed:" in result.text
    assert "Acceptance criteria:" in result.text


def test_invalid_packet_raises_value_error():
    packet = sample_packet()
    del packet["objective"]

    with pytest.raises(ValueError, match="Invalid handoff packet"):
        summarize_handoff_packet(packet)


def test_summarization_does_not_mutate_packet():
    packet = sample_packet()
    original_packet = copy.deepcopy(packet)

    summarize_handoff_packet(packet)

    assert packet == original_packet


def test_identical_inputs_produce_byte_identical_output_and_fingerprints():
    packet = sample_packet()
    evidence = current_evidence(packet)

    first = summarize_handoff_packet(packet, evidence=evidence)
    second = summarize_handoff_packet(packet, evidence=evidence)

    assert first.text == second.text
    assert first.source_fingerprint == second.source_fingerprint
    assert first.summary_fingerprint == second.summary_fingerprint


def test_source_fingerprint_changes_when_safety_field_changes():
    base = summarize_handoff_packet(sample_packet())
    changed = summarize_handoff_packet(
        sample_packet(forbidden_unless_needed=["Different forbidden path"])
    )

    assert base.source_fingerprint != changed.source_fingerprint
    assert base.summary_fingerprint != changed.summary_fingerprint


def test_summary_fingerprint_changes_when_acceptance_criteria_changes():
    base = summarize_handoff_packet(sample_packet())
    changed = summarize_handoff_packet(
        sample_packet(acceptance_criteria=["A different criterion"])
    )

    assert base.summary_fingerprint != changed.summary_fingerprint


def test_output_independent_of_clock_environment_and_process_identity():
    packet = sample_packet()
    os.environ["AGENT_MEMORY_TEST_PROBE"] = "probe-value"
    try:
        with_env = summarize_handoff_packet(packet)
    finally:
        del os.environ["AGENT_MEMORY_TEST_PROBE"]

    without_env = summarize_handoff_packet(packet)

    assert with_env.text == without_env.text
    assert with_env.source_fingerprint == without_env.source_fingerprint
    assert str(os.getpid()) not in with_env.text
    assert str(os.getpid()) not in with_env.source_fingerprint


def test_trust_status_current_requires_complete_matching_evidence():
    packet = sample_packet()
    evidence = current_evidence(packet)

    result = summarize_handoff_packet(packet, evidence=evidence)

    assert result.trust_status == TRUST_CURRENT
    assert result.trust_reason is None


def test_trust_status_stale_on_source_fingerprint_mismatch():
    packet = sample_packet()
    evidence = current_evidence(packet, source_fingerprint="0" * 64)

    result = summarize_handoff_packet(packet, evidence=evidence)

    assert result.trust_status == TRUST_STALE
    assert result.trust_reason == REASON_SOURCE_FINGERPRINT_MISMATCH


def test_trust_status_unsupported_on_unknown_schema_version():
    packet = sample_packet()
    evidence = current_evidence(packet, packet_schema_version="handoff-packet-v99")

    result = summarize_handoff_packet(packet, evidence=evidence)

    assert result.trust_status == TRUST_UNSUPPORTED
    assert result.trust_reason == REASON_SCHEMA_VERSION_UNSUPPORTED


def test_trust_status_unsupported_on_unknown_renderer_version():
    packet = sample_packet()
    evidence = current_evidence(packet, renderer_version="packet-summary-h99")

    result = summarize_handoff_packet(packet, evidence=evidence)

    assert result.trust_status == TRUST_UNSUPPORTED
    assert result.trust_reason == REASON_RENDERER_VERSION_UNSUPPORTED


def test_trust_status_unverifiable_when_no_evidence_supplied():
    result = summarize_handoff_packet(sample_packet())

    assert result.trust_status == TRUST_UNVERIFIABLE
    assert result.trust_reason == REASON_PRODUCER_INVALID


def test_trust_status_unverifiable_for_missing_provenance():
    packet = sample_packet()
    evidence = current_evidence(packet, provenance_status="missing")

    result = summarize_handoff_packet(packet, evidence=evidence)

    assert result.trust_status == TRUST_UNVERIFIABLE
    assert result.trust_reason == REASON_PROVENANCE_MISSING


def test_trust_status_unverifiable_for_malformed_provenance():
    packet = sample_packet()
    evidence = current_evidence(packet, provenance_status="malformed")

    result = summarize_handoff_packet(packet, evidence=evidence)

    assert result.trust_status == TRUST_UNVERIFIABLE
    assert result.trust_reason == REASON_PROVENANCE_MALFORMED


def test_trust_status_unverifiable_for_contradictory_provenance():
    packet = sample_packet()
    evidence = current_evidence(packet, provenance_status="contradictory")

    result = summarize_handoff_packet(packet, evidence=evidence)

    assert result.trust_status == TRUST_UNVERIFIABLE
    assert result.trust_reason == REASON_PROVENANCE_CONTRADICTORY


def test_trust_status_unverifiable_for_detached_provenance():
    packet = sample_packet()
    evidence = current_evidence(packet, provenance_status="detached")

    result = summarize_handoff_packet(packet, evidence=evidence)

    assert result.trust_status == TRUST_UNVERIFIABLE
    assert result.trust_reason == REASON_PROVENANCE_DETACHED


def test_trust_status_unverifiable_for_unrecognized_provenance_status():
    packet = sample_packet()
    evidence = current_evidence(packet, provenance_status="not-a-real-status")

    result = summarize_handoff_packet(packet, evidence=evidence)

    assert result.trust_status == TRUST_UNVERIFIABLE
    assert result.trust_reason == REASON_PROVENANCE_STATUS_INVALID


def test_trust_reason_never_leaks_exception_or_object_text():
    class Unrepresentable:
        def __repr__(self):
            return "<leaked internal object at 0xdeadbeef>"

        def __str__(self):
            raise RuntimeError("should never be surfaced")

    packet = sample_packet()
    evidence = RenderingEvidence(
        producer=Unrepresentable(),  # type: ignore[arg-type]
        packet_schema_version=SUPPORTED_PACKET_SCHEMA_VERSION,
        renderer_version=RENDERER_VERSION,
        provenance_status="supplied",
        source_fingerprint="0" * 64,
    )

    result = summarize_handoff_packet(packet, evidence=evidence)

    assert result.trust_status == TRUST_UNVERIFIABLE
    assert result.trust_reason == REASON_PRODUCER_INVALID
    assert "leaked internal object" not in str(result.trust_reason)
    assert "0xdeadbeef" not in str(result.trust_reason)


@pytest.mark.parametrize(
    "trust_status,evidence_kwargs",
    [
        (TRUST_CURRENT, {}),
        (TRUST_STALE, {"source_fingerprint": "0" * 64}),
        (TRUST_UNSUPPORTED, {"packet_schema_version": "handoff-packet-v99"}),
        (TRUST_UNVERIFIABLE, {"provenance_status": "missing"}),
    ],
)
def test_non_authorization_language_present_for_every_trust_state(
    trust_status, evidence_kwargs
):
    packet = sample_packet()
    evidence = current_evidence(packet, **evidence_kwargs)

    result = summarize_handoff_packet(packet, evidence=evidence)

    assert result.trust_status == trust_status
    assert "not implementation" in result.text
    assert "not proof that the packet is current" in result.text


def test_invalid_packet_still_fails_through_canonical_validator_with_evidence():
    packet = sample_packet()
    del packet["acceptance_criteria"]

    with pytest.raises(ValueError, match="Invalid handoff packet"):
        summarize_handoff_packet(packet, evidence=current_evidence(sample_packet()))


def test_no_cache_scheduler_network_or_execution_symbols_are_imported():
    import ast

    import agent_memory_context_manager.packet_summary as module_under_test

    module_source = Path(module_under_test.__file__).read_text(encoding="utf-8")
    tree = ast.parse(module_source)

    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    forbidden_modules = {
        "subprocess",
        "socket",
        "requests",
        "urllib",
        "urllib.request",
        "os",
        "time",
        "datetime",
        "git",
        ".summary_cache",
        ".summary_cache_writer",
        ".summary_cache_lookup",
        ".cache_key",
    }
    assert imported_modules.isdisjoint(forbidden_modules)
