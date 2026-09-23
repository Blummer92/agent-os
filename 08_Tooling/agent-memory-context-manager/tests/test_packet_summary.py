import copy
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_memory_context_manager import build_handoff_packet, summarize_handoff_packet  # noqa: E402
import agent_memory_context_manager.packet_summary as packet_summary  # noqa: E402
from agent_memory_context_manager.packet_summary import (  # noqa: E402
    MAX_CANONICAL_DEPTH,
    MAX_CANONICAL_NODES,
    MAX_CANONICAL_SERIALIZED_BYTES,
    MAX_COMPUTE_LIMIT_ENTRIES,
    MAX_DICT_ENTRIES_PER_FIELD,
    MAX_DISPLAY_VALUE_CHARS,
    MAX_FINGERPRINT_INPUT_BYTES,
    MAX_INTEGER_BITS,
    MAX_LIST_ENTRIES_PER_FIELD,
    MAX_STRING_CHARS,
    MAX_SUMMARY_LIST_LIMIT,
    MAX_TOTAL_DICT_ENTRIES,
    MAX_TOTAL_LIST_ENTRIES,
    MAX_TOTAL_NODES,
    MAX_TOTAL_STRING_BYTES,
    NON_AUTHORIZATION_NOTICE,
    RENDERER_VERSION,
    REASON_EVIDENCE_INVALID,
    REASON_PACKET_CONTENT_UNSAFE,
    REASON_PACKET_RESOURCE_LIMIT_EXCEEDED,
    REASON_PRODUCER_INVALID,
    REASON_PROVENANCE_CONTRADICTORY,
    REASON_PROVENANCE_DETACHED,
    REASON_PROVENANCE_MALFORMED,
    REASON_PROVENANCE_MISSING,
    REASON_PROVENANCE_STATUS_INVALID,
    REASON_RENDERER_VERSION_UNSUPPORTED,
    REASON_RENDERING_OPTIONS_INVALID,
    REASON_SCHEMA_VERSION_UNSUPPORTED,
    REASON_SOURCE_FINGERPRINT_INVALID,
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
        changed_files=["file-1.py", "file-2.py", "file-3.py", "file-4.py"],
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
            "PYTHONPATH=src python -m pytest tests/test_handoff_packet.py "
            "tests/test_packet_validation.py tests/test_packet_summary.py -q",
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
    fields = dict(
        producer="google-workspace-automation-engineer",
        packet_schema_version=SUPPORTED_PACKET_SCHEMA_VERSION,
        renderer_version=RENDERER_VERSION,
        provenance_status="supplied",
        source_fingerprint=packet_summary._fingerprint_value(packet),
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


class HostileStr(str):
    def strip(self, *args, **kwargs):
        raise RuntimeError("hostile strip leak")

    def __eq__(self, other):
        return True

    def __ne__(self, other):
        return False

    def __str__(self):
        raise RuntimeError("hostile string leak")

    def __repr__(self):
        return "<hostile repr at 0xdeadbeef>"


class HostileObject:
    def __str__(self):
        raise RuntimeError("object string leak")

    def __repr__(self):
        return "<object repr at 0xcafebabe>"


class HostileEvidenceObject:
    def __getattribute__(self, name):
        raise RuntimeError("attribute access leak")


# Existing behavior and canonical rendering.
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
    result = summarize_handoff_packet(sample_packet(branch=None, pr_number=None))
    assert "Branch: None" in result.text
    assert "PR number: None" in result.text


def test_summary_respects_list_limit_and_reports_omissions():
    result = summarize_handoff_packet(sample_packet(), list_limit=2)
    assert "- file-1.py" in result.text
    assert "- file-2.py" in result.text
    assert "- file-3.py" not in result.text
    assert "...and 2 more" in result.text


def test_list_limit_is_capped():
    packet = sample_packet(changed_files=[f"file-{index}.py" for index in range(100)])
    result = summarize_handoff_packet(packet, list_limit=10_000)
    assert result.text.count("- file-") == MAX_SUMMARY_LIST_LIMIT
    assert "...and 75 more" in result.text


def test_invalid_list_limit_fails_closed_without_invoking_object_methods():
    packet = sample_packet()
    result = summarize_handoff_packet(
        packet,
        list_limit=HostileObject(),  # type: ignore[arg-type]
        evidence=current_evidence(packet),
    )
    assert result.trust_status == TRUST_UNVERIFIABLE
    assert result.trust_reason == REASON_RENDERING_OPTIONS_INVALID
    assert "object string leak" not in result.text


def test_empty_safety_sections_remain_visible():
    result = summarize_handoff_packet(
        sample_packet(forbidden_unless_needed=[], acceptance_criteria=[])
    )
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


def test_output_independent_of_environment_and_process_identity():
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


# Complete fingerprint binding.
def test_current_and_stale_evidence_have_different_summary_fingerprints():
    packet = sample_packet()
    current = summarize_handoff_packet(packet, evidence=current_evidence(packet))
    stale = summarize_handoff_packet(
        packet,
        evidence=current_evidence(packet, source_fingerprint="0" * 64),
    )
    assert current.summary_fingerprint != stale.summary_fingerprint


@pytest.mark.parametrize(
    "override",
    [
        {"producer": "qa-test-agent"},
        {"packet_schema_version": "handoff-packet-v99"},
        {"renderer_version": "packet-summary-h99"},
        {"provenance_status": "missing"},
        {"source_fingerprint": "0" * 64},
    ],
)
def test_each_evidence_input_changes_summary_fingerprint(override):
    packet = sample_packet()
    baseline = summarize_handoff_packet(packet, evidence=current_evidence(packet))
    changed = summarize_handoff_packet(packet, evidence=current_evidence(packet, **override))
    assert baseline.summary_fingerprint != changed.summary_fingerprint


def test_notice_change_changes_summary_fingerprint(monkeypatch):
    packet = sample_packet()
    baseline = summarize_handoff_packet(packet, evidence=current_evidence(packet))
    monkeypatch.setattr(
        packet_summary,
        "NON_AUTHORIZATION_NOTICE",
        NON_AUTHORIZATION_NOTICE + " Updated notice contract.",
    )
    changed = summarize_handoff_packet(packet, evidence=current_evidence(packet))
    assert baseline.summary_fingerprint != changed.summary_fingerprint


def test_notice_version_change_changes_summary_fingerprint(monkeypatch):
    packet = sample_packet()
    baseline = summarize_handoff_packet(packet, evidence=current_evidence(packet))
    monkeypatch.setattr(packet_summary, "NON_AUTHORIZATION_NOTICE_VERSION", "v-next")
    changed = summarize_handoff_packet(packet, evidence=current_evidence(packet))
    assert baseline.summary_fingerprint != changed.summary_fingerprint


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("objective", "Different objective"),
        ("current_phase", "Different phase"),
        ("branch", "different-branch"),
        ("pr_number", 42),
        ("changed_files", ["changed.py"]),
        ("allowed_inspect_first", ["allowed.py"]),
        ("forbidden_unless_needed", ["forbidden.py"]),
        ("known_facts", ["Different fact"]),
        ("prior_decisions", ["Different decision"]),
        ("acceptance_criteria", ["Different criterion"]),
        ("validation_commands", ["different command"]),
        ("compute_limits", {"max_files_to_inspect": 9}),
        ("stop_conditions", ["Different stop"]),
    ],
)
def test_every_canonical_packet_field_changes_source_and_summary_fingerprint(
    field, replacement
):
    base = summarize_handoff_packet(sample_packet())
    changed = summarize_handoff_packet(sample_packet(**{field: replacement}))
    assert base.source_fingerprint != changed.source_fingerprint
    assert base.summary_fingerprint != changed.summary_fingerprint


@pytest.mark.parametrize(
    "left,right",
    [
        (None, "None"),
        (True, 1),
        (1, "1"),
        ({1: "x"}, {"1": "x"}),
        ("line\nvalue", "line\\nvalue"),
    ],
)
def test_type_tagged_fingerprint_distinguishes_values(left, right):
    assert packet_summary._fingerprint_value(left) != packet_summary._fingerprint_value(right)


def test_dictionary_fingerprint_is_insertion_order_independent():
    left = {"b": 2, "a": 1}
    right = {"a": 1, "b": 2}
    assert packet_summary._fingerprint_value(left) == packet_summary._fingerprint_value(right)


# Trust-state behavior.
def test_trust_status_current_requires_complete_matching_evidence():
    packet = sample_packet()
    result = summarize_handoff_packet(packet, evidence=current_evidence(packet))
    assert result.trust_status == TRUST_CURRENT
    assert result.trust_reason is None


def test_trust_status_stale_on_source_fingerprint_mismatch_and_shows_both_values():
    packet = sample_packet()
    supplied = "0" * 64
    result = summarize_handoff_packet(
        packet,
        evidence=current_evidence(packet, source_fingerprint=supplied),
    )
    assert result.trust_status == TRUST_STALE
    assert result.trust_reason == REASON_SOURCE_FINGERPRINT_MISMATCH
    assert f"Supplied source fingerprint: {supplied}" in result.text
    assert f"Actual source fingerprint: {result.source_fingerprint}" in result.text
    assert result.supplied_source_fingerprint == supplied


def test_trust_status_unsupported_on_unknown_schema_version():
    packet = sample_packet()
    result = summarize_handoff_packet(
        packet,
        evidence=current_evidence(packet, packet_schema_version="handoff-packet-v99"),
    )
    assert result.trust_status == TRUST_UNSUPPORTED
    assert result.trust_reason == REASON_SCHEMA_VERSION_UNSUPPORTED


def test_trust_status_unsupported_on_unknown_renderer_version():
    packet = sample_packet()
    result = summarize_handoff_packet(
        packet,
        evidence=current_evidence(packet, renderer_version="packet-summary-h99"),
    )
    assert result.trust_status == TRUST_UNSUPPORTED
    assert result.trust_reason == REASON_RENDERER_VERSION_UNSUPPORTED


def test_trust_status_unverifiable_when_no_evidence_supplied():
    result = summarize_handoff_packet(sample_packet())
    assert result.trust_status == TRUST_UNVERIFIABLE
    assert result.trust_reason == REASON_PRODUCER_INVALID


@pytest.mark.parametrize(
    "provenance_status,reason",
    [
        ("missing", REASON_PROVENANCE_MISSING),
        ("malformed", REASON_PROVENANCE_MALFORMED),
        ("contradictory", REASON_PROVENANCE_CONTRADICTORY),
        ("detached", REASON_PROVENANCE_DETACHED),
        ("not-a-real-status", REASON_PROVENANCE_STATUS_INVALID),
    ],
)
def test_provenance_states_fail_closed(provenance_status, reason):
    packet = sample_packet()
    result = summarize_handoff_packet(
        packet,
        evidence=current_evidence(packet, provenance_status=provenance_status),
    )
    assert result.trust_status == TRUST_UNVERIFIABLE
    assert result.trust_reason == reason


# Hostile evidence and packet containment.
@pytest.mark.parametrize(
    "field",
    [
        "producer",
        "packet_schema_version",
        "renderer_version",
        "provenance_status",
        "source_fingerprint",
    ],
)
def test_hostile_string_subclasses_never_classify_current_or_leak(field):
    packet = sample_packet()
    evidence = current_evidence(packet, **{field: HostileStr("hostile")})
    result = summarize_handoff_packet(packet, evidence=evidence)
    assert result.trust_status == TRUST_UNVERIFIABLE
    assert "hostile strip leak" not in result.text
    assert "hostile string leak" not in result.text
    assert "0xdeadbeef" not in result.text


def test_hostile_evidence_object_attribute_access_is_not_invoked():
    packet = sample_packet()
    result = summarize_handoff_packet(
        packet,
        evidence=HostileEvidenceObject(),  # type: ignore[arg-type]
    )
    assert result.trust_status == TRUST_UNVERIFIABLE
    assert result.trust_reason == REASON_EVIDENCE_INVALID
    assert "attribute access leak" not in result.text


def test_overlong_evidence_is_bounded_and_unverifiable():
    packet = sample_packet()
    producer = "x" * 10_000
    result = summarize_handoff_packet(
        packet,
        evidence=current_evidence(packet, producer=producer),
    )
    assert result.trust_status == TRUST_UNVERIFIABLE
    assert len(result.text) < 10_000
    assert producer not in result.text


def test_hostile_branch_value_cannot_escape_canonical_validation_boundary():
    packet = sample_packet()
    packet["branch"] = HostileStr("hostile-branch")
    result = summarize_handoff_packet(packet, evidence=current_evidence(packet))
    assert result.trust_status == TRUST_UNVERIFIABLE
    assert result.trust_reason == REASON_PACKET_CONTENT_UNSAFE
    assert "hostile strip leak" not in result.text
    assert "0xdeadbeef" not in result.text
    assert "context evidence only" in result.text


def test_malformed_exact_source_fingerprint_is_unverifiable_not_missing():
    packet = sample_packet()
    result = summarize_handoff_packet(
        packet,
        evidence=current_evidence(packet, source_fingerprint="not-a-fingerprint"),
    )
    assert result.trust_status == TRUST_UNVERIFIABLE
    assert result.trust_reason == REASON_SOURCE_FINGERPRINT_INVALID


def test_hostile_scalar_packet_value_is_bounded_and_fails_closed():
    packet = sample_packet()
    packet["objective"] = HostileStr("hostile objective")
    result = summarize_handoff_packet(packet, evidence=current_evidence(packet))
    assert result.trust_status == TRUST_UNVERIFIABLE
    assert result.trust_reason == REASON_PACKET_CONTENT_UNSAFE
    assert "Objective: <invalid>" in result.text
    assert "hostile" not in result.text
    assert "0xdeadbeef" not in result.text


def test_hostile_list_entry_is_bounded_and_fails_closed():
    packet = sample_packet()
    packet["known_facts"].append(HostileObject())
    result = summarize_handoff_packet(
        packet,
        list_limit=25,
        evidence=current_evidence(packet),
    )
    assert result.trust_status == TRUST_UNVERIFIABLE
    assert result.trust_reason == REASON_PACKET_CONTENT_UNSAFE
    assert "- <invalid>" in result.text
    assert "object string leak" not in result.text
    assert "0xcafebabe" not in result.text


def test_hostile_compute_limit_key_and_value_are_contained():
    packet = sample_packet()
    packet["compute_limits"][HostileObject()] = HostileObject()
    result = summarize_handoff_packet(packet, evidence=current_evidence(packet))
    assert result.trust_status == TRUST_UNVERIFIABLE
    assert result.trust_reason == REASON_PACKET_CONTENT_UNSAFE
    assert "- <invalid>: <invalid>" in result.text
    assert "object string leak" not in result.text
    assert "0xcafebabe" not in result.text


def test_compute_limit_collection_is_capped_and_reports_omissions():
    packet = sample_packet()
    for index in range(100):
        packet["compute_limits"][f"extra_{index}"] = index
    result = summarize_handoff_packet(packet)
    section = result.text.split("Compute limits:\n", 1)[1].split("\nStop conditions:", 1)[0]
    rendered = [line for line in section.splitlines() if line.startswith("- ")]
    assert len(rendered) == MAX_COMPUTE_LIMIT_ENTRIES
    assert "more compute limits" in section


def test_recursive_list_does_not_recurse_forever_and_fails_closed():
    packet = sample_packet()
    recursive = []
    recursive.append(recursive)
    packet["known_facts"] = recursive
    result = summarize_handoff_packet(packet, evidence=current_evidence(packet))
    assert result.trust_status == TRUST_UNVERIFIABLE
    assert result.trust_reason == REASON_PACKET_CONTENT_UNSAFE
    assert "- <invalid>" in result.text


def test_long_and_multiline_values_are_bounded_and_cannot_inject_lines():
    packet = sample_packet(objective="safe\nInjected: yes\r\n" + "x" * 1_000)
    result = summarize_handoff_packet(packet)
    objective_line = result.text.splitlines()[0]
    assert "\\nInjected: yes\\r\\n" in objective_line
    assert "\nInjected: yes" not in result.text
    assert "<truncated" in objective_line
    assert len(objective_line) < MAX_DISPLAY_VALUE_CHARS + 100


# Authorized resource-limit contract.
def test_resource_limit_constants_match_authorized_contract():
    assert MAX_LIST_ENTRIES_PER_FIELD == 500
    assert MAX_TOTAL_LIST_ENTRIES == 2_000
    assert MAX_DICT_ENTRIES_PER_FIELD == 300
    assert MAX_TOTAL_DICT_ENTRIES == 1_500
    assert MAX_STRING_CHARS == 10_000
    assert MAX_TOTAL_STRING_BYTES == 50_000
    assert MAX_CANONICAL_NODES == 5_000
    assert MAX_CANONICAL_DEPTH == 20
    assert MAX_INTEGER_BITS == 1_024
    assert MAX_CANONICAL_SERIALIZED_BYTES == 100_000
    assert MAX_FINGERPRINT_INPUT_BYTES == 100_000
    assert MAX_TOTAL_NODES == 10_000


def assert_resource_failure(result):
    assert result.trust_status == TRUST_UNVERIFIABLE
    assert result.trust_reason == REASON_PACKET_RESOURCE_LIMIT_EXCEEDED
    assert "Objective: <invalid>" in result.text
    assert "context evidence only" in result.text
    assert "0x" not in result.text


def test_oversized_top_level_list_fails_before_fingerprinting(monkeypatch):
    packet = sample_packet(changed_files=["x"] * (MAX_LIST_ENTRIES_PER_FIELD + 1))

    def should_not_run(*args, **kwargs):
        raise AssertionError("fingerprint traversal started")

    monkeypatch.setattr(packet_summary, "_fingerprint_value_with_safety", should_not_run)
    assert_resource_failure(summarize_handoff_packet(packet))


def test_total_list_entry_budget_cannot_be_distributed_across_fields():
    values = ["x"] * 251
    packet = sample_packet(
        changed_files=list(values),
        allowed_inspect_first=list(values),
        forbidden_unless_needed=list(values),
        known_facts=list(values),
        prior_decisions=list(values),
        acceptance_criteria=list(values),
        validation_commands=list(values),
        stop_conditions=list(values),
    )
    assert_resource_failure(summarize_handoff_packet(packet))


def test_oversized_compute_limit_dictionary_fails_before_display_materialization():
    extras = {f"extra_{index}": index for index in range(MAX_DICT_ENTRIES_PER_FIELD)}
    packet = sample_packet(compute_limits=extras)
    assert dict.__len__(packet["compute_limits"]) > MAX_DICT_ENTRIES_PER_FIELD
    assert_resource_failure(summarize_handoff_packet(packet))


def test_per_string_character_limit_rejects_before_trusted_rendering():
    secret = "s" * (MAX_STRING_CHARS + 1)
    result = summarize_handoff_packet(sample_packet(objective=secret))
    assert_resource_failure(result)
    assert secret[:100] not in result.text


def test_aggregate_utf8_byte_limit_fails_closed():
    chunk = "é" * 4_500
    packet = sample_packet(
        changed_files=[chunk],
        allowed_inspect_first=[chunk],
        forbidden_unless_needed=[chunk],
        known_facts=[chunk],
        prior_decisions=[chunk],
        acceptance_criteria=[chunk],
    )
    assert_resource_failure(summarize_handoff_packet(packet))


def test_integer_bit_limit_fails_closed_before_string_conversion():
    packet = sample_packet(pr_number=1 << MAX_INTEGER_BITS)
    assert_resource_failure(summarize_handoff_packet(packet))


def test_excessive_nested_depth_fails_closed():
    nested = "leaf"
    for _ in range(MAX_CANONICAL_DEPTH + 1):
        nested = [nested]
    packet = sample_packet(known_facts=[nested])
    assert_resource_failure(summarize_handoff_packet(packet))


def test_canonical_node_budget_fails_closed_on_wide_bounded_content():
    nested_dicts = [
        {f"a{index}": index, f"b{index}": index, f"c{index}": index}
        for index in range(490)
    ]
    packet = sample_packet(known_facts=nested_dicts)
    assert_resource_failure(summarize_handoff_packet(packet))


def test_resource_failure_fingerprint_is_deterministic_and_domain_separated():
    first = summarize_handoff_packet(
        sample_packet(changed_files=["x"] * (MAX_LIST_ENTRIES_PER_FIELD + 1))
    )
    second = summarize_handoff_packet(
        sample_packet(changed_files=["y"] * (MAX_LIST_ENTRIES_PER_FIELD + 1))
    )
    valid = summarize_handoff_packet(sample_packet())
    assert first.source_fingerprint == second.source_fingerprint
    assert first.summary_fingerprint == second.summary_fingerprint
    assert first.source_fingerprint != valid.source_fingerprint
    assert first.source_fingerprint != packet_summary._fixed_failure_fingerprint(
        packet_summary._UNSAFE_FAILURE_STATUS
    )


def test_resource_failure_cannot_become_current_with_matching_fixed_fingerprint():
    packet = sample_packet(changed_files=["x"] * (MAX_LIST_ENTRIES_PER_FIELD + 1))
    fixed = packet_summary._fingerprint_value(packet)
    evidence = RenderingEvidence(
        producer="google-workspace-automation-engineer",
        packet_schema_version=SUPPORTED_PACKET_SCHEMA_VERSION,
        renderer_version=RENDERER_VERSION,
        provenance_status="supplied",
        source_fingerprint=fixed,
    )
    assert_resource_failure(summarize_handoff_packet(packet, evidence=evidence))


def test_serialization_buffer_rejects_before_oversized_join():
    with pytest.raises(packet_summary._ResourceLimitExceeded):
        packet_summary._bounded_frame(
            b"test",
            (b"x" * MAX_CANONICAL_SERIALIZED_BYTES,),
        )


def test_internal_programming_error_is_not_masked(monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("internal defect")

    monkeypatch.setattr(packet_summary, "_render_core", broken)
    with pytest.raises(RuntimeError, match="internal defect"):
        summarize_handoff_packet(sample_packet())


def test_validator_internal_programming_error_is_not_masked(monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("validator internal defect")

    monkeypatch.setattr(packet_summary, "assert_valid_handoff_packet", broken)
    with pytest.raises(RuntimeError, match="validator internal defect"):
        summarize_handoff_packet(sample_packet())


@pytest.mark.parametrize("exception_type", [KeyboardInterrupt, SystemExit, GeneratorExit])
def test_base_exceptions_propagate_from_validator(monkeypatch, exception_type):
    def stop(*args, **kwargs):
        raise exception_type()

    monkeypatch.setattr(packet_summary, "assert_valid_handoff_packet", stop)
    with pytest.raises(exception_type):
        summarize_handoff_packet(sample_packet())


def test_no_complete_compute_mapping_materialization_or_complete_packet_json_tree():
    source = Path(packet_summary.__file__).read_text(encoding="utf-8")
    assert "list(dict.items(" not in source
    assert "list(values.items(" not in source
    assert 'json.dumps(\n        {"version": version, "value": canonical}' not in source
    internal_start = source.index("def _fingerprint_internal_payload")
    internal_end = source.index("def _fixed_failure_fingerprint")
    assert "json.dumps" not in source[internal_start:internal_end]


@pytest.mark.parametrize(
    "value,escaped",
    [
        ("\ud800", "\\ud800"),
        ("\udfff", "\\udfff"),
        ("before\ud800after", "before\\ud800after"),
    ],
)
def test_surrogate_objective_is_escaped_utf8_safe_and_unverifiable(value, escaped):
    packet = sample_packet(objective=value)
    result = summarize_handoff_packet(packet, evidence=current_evidence(packet))
    assert escaped in result.text
    result.text.encode("utf-8", errors="strict")
    assert result.trust_status == TRUST_UNVERIFIABLE
    assert result.trust_reason == REASON_PACKET_CONTENT_UNSAFE


def test_surrogate_list_entry_is_escaped_and_summary_is_utf8_safe():
    packet = sample_packet(known_facts=["safe", "\ud800", "safe-again"])
    result = summarize_handoff_packet(
        packet,
        list_limit=25,
        evidence=current_evidence(packet),
    )
    assert "- \\ud800" in result.text
    result.text.encode("utf-8", errors="strict")
    assert result.trust_status == TRUST_UNVERIFIABLE


@pytest.mark.parametrize(
    "compute_limits,escaped",
    [
        ({"\ud800": "value"}, "\\ud800"),
        ({"surrogate_value": "\udfff"}, "\\udfff"),
    ],
)
def test_surrogate_compute_limit_key_or_value_is_utf8_safe_and_unverifiable(
    compute_limits, escaped
):
    packet = sample_packet(compute_limits=compute_limits)
    result = summarize_handoff_packet(packet, evidence=current_evidence(packet))
    assert escaped in result.text
    result.text.encode("utf-8", errors="strict")
    assert result.trust_status == TRUST_UNVERIFIABLE


def test_valid_unicode_and_emoji_remain_visible_and_current():
    packet = sample_packet(objective="normal text ✓ café 😀")
    result = summarize_handoff_packet(packet, evidence=current_evidence(packet))
    assert "normal text ✓ café 😀" in result.text
    result.text.encode("utf-8", errors="strict")
    assert result.trust_status == TRUST_CURRENT


class TrackingDigest:
    def __init__(self):
        self.chunks = []

    def update(self, chunk):
        self.chunks.append(bytes(chunk))

    def hexdigest(self):
        return "a" * 64


def _tracked_internal_payload(monkeypatch, payload, version="v"):
    trackers = []

    def factory():
        tracker = TrackingDigest()
        trackers.append(tracker)
        return tracker

    monkeypatch.setattr(packet_summary.hashlib, "sha256", factory)
    digest = packet_summary._fingerprint_internal_payload(payload, version=version)
    return digest, trackers[-1]


def test_streamed_internal_payload_is_deterministic_for_reordered_dictionary(monkeypatch):
    first, _ = _tracked_internal_payload(
        monkeypatch,
        {"b": "😀 café", "a": 3},
    )
    monkeypatch.undo()
    second, _ = _tracked_internal_payload(
        monkeypatch,
        {"a": 3, "b": "😀 café"},
    )
    assert first == second


def test_streamed_internal_payload_rejects_before_oversized_digest_update(monkeypatch):
    tracker = TrackingDigest()
    monkeypatch.setattr(packet_summary.hashlib, "sha256", lambda: tracker)
    monkeypatch.setattr(packet_summary, "MAX_CANONICAL_SERIALIZED_BYTES", 1_000)
    monkeypatch.setattr(packet_summary, "MAX_FINGERPRINT_INPUT_BYTES", 1_000)

    with pytest.raises(packet_summary._ResourceLimitExceeded):
        packet_summary._fingerprint_internal_payload(
            {"rendered_text_template": "😀" * 1_000},
            version="v",
        )

    assert sum(len(chunk) for chunk in tracker.chunks) <= 1_000
    assert max(map(len, tracker.chunks)) <= 4 * packet_summary._STREAM_TEXT_CHARS


def test_streamed_internal_payload_honors_exact_serialized_boundary(monkeypatch):
    _, tracker = _tracked_internal_payload(monkeypatch, {"text": "café 😀"})
    size = sum(len(chunk) for chunk in tracker.chunks)
    monkeypatch.undo()

    monkeypatch.setattr(packet_summary, "MAX_CANONICAL_SERIALIZED_BYTES", size)
    monkeypatch.setattr(packet_summary, "MAX_FINGERPRINT_INPUT_BYTES", size)
    packet_summary._fingerprint_internal_payload({"text": "café 😀"}, version="v")

    monkeypatch.setattr(packet_summary, "MAX_CANONICAL_SERIALIZED_BYTES", size - 1)
    with pytest.raises(packet_summary._ResourceLimitExceeded):
        packet_summary._fingerprint_internal_payload({"text": "café 😀"}, version="v")


def test_streamed_internal_payload_honors_exact_fingerprint_boundary(monkeypatch):
    _, tracker = _tracked_internal_payload(monkeypatch, {"text": "emoji 😀"})
    size = sum(len(chunk) for chunk in tracker.chunks)
    monkeypatch.undo()

    monkeypatch.setattr(packet_summary, "MAX_CANONICAL_SERIALIZED_BYTES", size + 100)
    monkeypatch.setattr(packet_summary, "MAX_FINGERPRINT_INPUT_BYTES", size)
    packet_summary._fingerprint_internal_payload({"text": "emoji 😀"}, version="v")

    monkeypatch.setattr(packet_summary, "MAX_FINGERPRINT_INPUT_BYTES", size - 1)
    with pytest.raises(packet_summary._ResourceLimitExceeded):
        packet_summary._fingerprint_internal_payload({"text": "emoji 😀"}, version="v")


class HostileClassProbe:
    @property
    def __class__(self):
        raise RuntimeError("SECRET hostile __class__ leak")


@pytest.mark.parametrize(
    "field",
    ["branch", "pr_number", "objective", "current_phase", "changed_files"],
)
def test_hostile_class_probe_in_validator_field_fails_closed_without_leak(field):
    packet = sample_packet()
    packet[field] = HostileClassProbe()
    result = summarize_handoff_packet(packet, evidence=current_evidence(sample_packet()))
    assert result.trust_status == TRUST_UNVERIFIABLE
    assert result.trust_reason == REASON_PACKET_CONTENT_UNSAFE
    assert "SECRET hostile __class__ leak" not in result.text
    assert "context evidence only" in result.text


def test_hostile_class_probe_compute_limits_container_fails_closed_without_leak():
    packet = sample_packet()
    packet["compute_limits"] = HostileClassProbe()
    result = summarize_handoff_packet(packet, evidence=current_evidence(sample_packet()))
    assert result.trust_status == TRUST_UNVERIFIABLE
    assert result.trust_reason == REASON_PACKET_CONTENT_UNSAFE
    assert "SECRET hostile __class__ leak" not in result.text


@pytest.mark.parametrize(
    "field",
    ["max_files_to_inspect", "targeted_tests_only", "no_full_scheduler_suite"],
)
def test_hostile_class_probe_compute_limit_value_fails_closed_without_leak(field):
    packet = sample_packet()
    packet["compute_limits"][field] = HostileClassProbe()
    result = summarize_handoff_packet(packet, evidence=current_evidence(sample_packet()))
    assert result.trust_status == TRUST_UNVERIFIABLE
    assert result.trust_reason == REASON_PACKET_CONTENT_UNSAFE
    assert "SECRET hostile __class__ leak" not in result.text


def test_containment_classifier_never_uses_isinstance():
    import inspect

    source = inspect.getsource(packet_summary._validator_requires_containment)
    assert "isinstance(" not in source


# Full notice coverage.
NOTICE_FRAGMENTS = [
    "context evidence only",
    "implementation",
    "execution",
    "readiness or status changes",
    "external writes",
    "governed-field changes",
    "merge",
    "deployment",
    "production action",
    "does not independently verify provenance",
    "not proof that the packet is current",
    "canonical GitHub issue",
    "approval record",
    "repository state",
]


@pytest.mark.parametrize(
    "trust_status,evidence_kwargs",
    [
        (TRUST_CURRENT, {}),
        (TRUST_STALE, {"source_fingerprint": "0" * 64}),
        (TRUST_UNSUPPORTED, {"packet_schema_version": "handoff-packet-v99"}),
        (TRUST_UNVERIFIABLE, {"provenance_status": "missing"}),
    ],
)
def test_complete_non_authorization_notice_present_for_every_trust_state(
    trust_status, evidence_kwargs
):
    packet = sample_packet()
    result = summarize_handoff_packet(
        packet,
        evidence=current_evidence(packet, **evidence_kwargs),
    )
    assert result.trust_status == trust_status
    for fragment in NOTICE_FRAGMENTS:
        assert fragment in result.text


def test_complete_notice_present_for_resource_failure():
    result = summarize_handoff_packet(
        sample_packet(changed_files=["x"] * (MAX_LIST_ENTRIES_PER_FIELD + 1))
    )
    for fragment in NOTICE_FRAGMENTS:
        assert fragment in result.text


def test_invalid_packet_still_fails_through_canonical_validator_with_evidence():
    packet = sample_packet()
    del packet["acceptance_criteria"]
    with pytest.raises(ValueError, match="Invalid handoff packet"):
        summarize_handoff_packet(packet, evidence=current_evidence(sample_packet()))


def test_no_cache_scheduler_network_or_execution_symbols_are_imported():
    import ast

    module_source = Path(packet_summary.__file__).read_text(encoding="utf-8")
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
