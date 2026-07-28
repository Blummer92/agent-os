import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_memory_context_manager import (  # noqa: E402
    CACHE_ENTRY_VERSION_V2,
    CACHE_KEY_VERSION_V2,
    CACHE_NAMESPACE_VERSION_V2,
    RENDERER_VERSION,
    SUPPORTED_PACKET_SCHEMA_VERSION,
    build_handoff_packet,
    build_handoff_packet_cache_key,
    build_handoff_packet_cache_key_v2,
    handoff_packet_source_fingerprint,
)
from agent_memory_context_manager import cache_key as cache_key_module  # noqa: E402


def sample_packet():
    return build_handoff_packet(
        objective="Build deterministic cache keys",
        current_phase="Memory 1E",
        branch="claude/agent-memory-context-manager-1e-cache-key-helpers",
        pr_number=0,
        changed_files=["cache_key.py", "test_cache_key.py"],
        allowed_inspect_first=["cache_key.py"],
        forbidden_unless_needed=["Workflow Scheduler source"],
        known_facts=["Memory 1D summary cache helpers are merged"],
        prior_decisions=["Cache keys should use stable handoff fields"],
        acceptance_criteria=["Equivalent packets produce matching keys"],
        validation_commands=["PYTHONPATH=src python -m pytest tests/test_cache_key.py -q"],
        stop_conditions=["Need Scheduler integration"],
    )


def test_valid_packet_returns_string():
    key = build_handoff_packet_cache_key(sample_packet())

    assert isinstance(key, str)


def test_key_starts_with_default_prefix():
    key = build_handoff_packet_cache_key(sample_packet())

    assert key.startswith("handoff-summary:1.0:")


def test_same_packet_produces_same_key():
    packet = sample_packet()

    assert build_handoff_packet_cache_key(packet) == build_handoff_packet_cache_key(packet)


def test_equivalent_packet_with_reordered_compute_limit_keys_produces_same_key():
    packet = sample_packet()
    reordered_packet = copy.deepcopy(packet)
    reordered_packet["compute_limits"] = {
        key: packet["compute_limits"][key]
        for key in reversed(list(packet["compute_limits"].keys()))
    }

    assert build_handoff_packet_cache_key(packet) == build_handoff_packet_cache_key(
        reordered_packet
    )


def test_changing_objective_changes_key():
    packet = sample_packet()
    changed_packet = copy.deepcopy(packet)
    changed_packet["objective"] = "Different objective"

    assert build_handoff_packet_cache_key(packet) != build_handoff_packet_cache_key(
        changed_packet
    )


def test_changing_changed_files_changes_key():
    packet = sample_packet()
    changed_packet = copy.deepcopy(packet)
    changed_packet["changed_files"].append("another-file.py")

    assert build_handoff_packet_cache_key(packet) != build_handoff_packet_cache_key(
        changed_packet
    )


def test_invalid_packet_raises_value_error():
    packet = sample_packet()
    del packet["objective"]

    with pytest.raises(ValueError, match="Invalid handoff packet"):
        build_handoff_packet_cache_key(packet)


def test_function_does_not_mutate_packet():
    packet = sample_packet()
    original_packet = copy.deepcopy(packet)

    build_handoff_packet_cache_key(packet)

    assert packet == original_packet


# --- Cache contract v2 -------------------------------------------------------


def v2_packet(**overrides):
    fields = {
        "objective": "Implement cache contract v2",
        "current_phase": "Memory H3",
        "branch": None,
        "pr_number": None,
        "changed_files": ["cache_key.py"],
        "allowed_inspect_first": ["summary_cache.py"],
        "forbidden_unless_needed": ["Workflow Scheduler source"],
        "known_facts": ["Memory H2 is merged"],
        "prior_decisions": ["Reuse H2 canonical identities"],
        "acceptance_criteria": ["No v1 fallback exists"],
        "validation_commands": ["PYTHONPATH=src python -m pytest tests -q"],
        "stop_conditions": ["Needs a scope decision"],
    }
    fields.update(overrides)
    return build_handoff_packet(**fields)


V2_KEY_PREFIX = f"handoff-summary-v2:{CACHE_KEY_VERSION_V2}:"


def test_v2_key_uses_fixed_prefix_and_sha256_digest():
    key = build_handoff_packet_cache_key_v2(v2_packet())

    assert key.startswith(V2_KEY_PREFIX)
    digest = key[len(V2_KEY_PREFIX) :]
    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")


def test_v2_key_is_deterministic_for_identical_input():
    packet = v2_packet()

    assert build_handoff_packet_cache_key_v2(packet) == build_handoff_packet_cache_key_v2(
        copy.deepcopy(packet)
    )


def test_v2_key_differs_from_v1_key():
    packet = v2_packet()

    assert build_handoff_packet_cache_key_v2(packet) != build_handoff_packet_cache_key(
        packet
    )


def test_v2_key_binds_h2_source_fingerprint():
    packet = v2_packet()
    fingerprint = handoff_packet_source_fingerprint(packet)

    assert len(fingerprint) == 64
    assert build_handoff_packet_cache_key_v2(
        packet
    ) == cache_key_module.build_cache_key_v2_from_source_fingerprint(fingerprint)


@pytest.mark.parametrize(
    "field,value",
    [
        ("objective", "A different objective"),
        ("current_phase", "A different phase"),
        ("branch", "agent/631-cache-contract-v2-cutover"),
        ("pr_number", 631),
        ("changed_files", ["cache_key.py", "summary_cache.py"]),
        ("allowed_inspect_first", ["summary_cache_lookup.py"]),
        ("forbidden_unless_needed", ["Workflow Scheduler source", "Registry files"]),
        ("known_facts", ["Memory H2 is merged", "PR 627 is merged"]),
        ("prior_decisions", ["Reuse H2 canonical identities", "No metadata"]),
        ("acceptance_criteria", ["No v1 fallback exists", "Atomic publication"]),
        ("validation_commands", ["python -m compileall -q src tests"]),
        ("stop_conditions", ["Needs a scope decision", "Predecessor defect"]),
        ("compute_limits", {"max_files_to_inspect": 12}),
    ],
)
def test_every_canonical_packet_field_changes_the_v2_key(field, value):
    baseline = build_handoff_packet_cache_key_v2(v2_packet())

    assert build_handoff_packet_cache_key_v2(v2_packet(**{field: value})) != baseline


def test_forbidden_unless_needed_and_acceptance_criteria_bind_v2_identity():
    """These two fields are omitted from the v1 key and must bind v2 identity."""
    baseline_v1 = build_handoff_packet_cache_key(v2_packet())
    baseline_v2 = build_handoff_packet_cache_key_v2(v2_packet())

    changed = v2_packet(
        forbidden_unless_needed=["something else"],
        acceptance_criteria=["something else"],
    )

    assert build_handoff_packet_cache_key(changed) == baseline_v1
    assert build_handoff_packet_cache_key_v2(changed) != baseline_v2


def test_null_branch_is_distinct_from_string_values():
    null_key = build_handoff_packet_cache_key_v2(v2_packet(branch=None))

    assert null_key != build_handoff_packet_cache_key_v2(v2_packet(branch="main"))
    assert null_key != build_handoff_packet_cache_key_v2(v2_packet(branch="None"))
    assert null_key != build_handoff_packet_cache_key_v2(v2_packet(branch="null"))


def test_null_pr_number_is_distinct_from_legacy_sentinels():
    null_key = build_handoff_packet_cache_key_v2(v2_packet(pr_number=None))

    assert null_key != build_handoff_packet_cache_key_v2(v2_packet(pr_number=0))
    assert null_key != build_handoff_packet_cache_key_v2(v2_packet(pr_number=1))
    assert null_key != build_handoff_packet_cache_key_v2(v2_packet(pr_number=False))


def test_compute_limit_key_order_does_not_change_v2_identity():
    packet = v2_packet()
    reordered = copy.deepcopy(packet)
    reordered["compute_limits"] = {
        key: packet["compute_limits"][key]
        for key in reversed(list(packet["compute_limits"]))
    }

    assert build_handoff_packet_cache_key_v2(packet) == build_handoff_packet_cache_key_v2(
        reordered
    )


@pytest.mark.parametrize(
    "constant_name",
    [
        "CACHE_KEY_VERSION_V2",
        "CACHE_ENTRY_VERSION_V2",
        "CACHE_NAMESPACE_VERSION_V2",
        "SUPPORTED_PACKET_SCHEMA_VERSION",
        "RENDERER_VERSION",
        "SOURCE_FINGERPRINT_VERSION",
    ],
)
def test_every_bound_version_changes_the_v2_key(monkeypatch, constant_name):
    fingerprint = handoff_packet_source_fingerprint(v2_packet())
    baseline = cache_key_module.build_cache_key_v2_from_source_fingerprint(fingerprint)

    monkeypatch.setattr(cache_key_module, constant_name, "drifted-identity")

    assert (
        cache_key_module.build_cache_key_v2_from_source_fingerprint(fingerprint)
        != baseline
    )


def test_changing_source_fingerprint_changes_the_v2_key():
    baseline = cache_key_module.build_cache_key_v2_from_source_fingerprint("a" * 64)

    assert (
        cache_key_module.build_cache_key_v2_from_source_fingerprint("b" * 64) != baseline
    )


def test_bound_version_values_are_the_canonical_h2_identities():
    assert SUPPORTED_PACKET_SCHEMA_VERSION == "handoff-packet-v2"
    assert RENDERER_VERSION == "packet-summary-h2"
    assert CACHE_KEY_VERSION_V2 == "2.0"
    assert CACHE_ENTRY_VERSION_V2 == "2.0"
    assert CACHE_NAMESPACE_VERSION_V2 == "2.0"


def test_invalid_packet_raises_value_error_through_canonical_validator():
    packet = v2_packet()
    del packet["objective"]

    with pytest.raises(ValueError, match="Invalid handoff packet"):
        build_handoff_packet_cache_key_v2(packet)


def test_packet_exceeding_h2_resource_limits_is_ineligible():
    packet = v2_packet(changed_files=["file"] * 5_000)

    with pytest.raises(ValueError, match="not eligible for a v2 cache identity"):
        build_handoff_packet_cache_key_v2(packet)


def test_v2_key_builder_does_not_mutate_packet():
    packet = v2_packet()
    original = copy.deepcopy(packet)

    build_handoff_packet_cache_key_v2(packet)
    handoff_packet_source_fingerprint(packet)

    assert packet == original


@pytest.mark.parametrize(
    "candidate",
    [
        "/etc/passwd",
        "../../etc/passwd",
        f"{V2_KEY_PREFIX}../../etc/passwd",
        f"{V2_KEY_PREFIX}..",
        f"{V2_KEY_PREFIX}/absolute",
        f"{V2_KEY_PREFIX}C:\\Windows\\system32",
        f"{V2_KEY_PREFIX}\\\\server\\share",
        f"{V2_KEY_PREFIX}CON",
        f"{V2_KEY_PREFIX}nul",
        f"{V2_KEY_PREFIX}{'a' * 63}.",
        f"{V2_KEY_PREFIX}{'a' * 63} ",
        f"{V2_KEY_PREFIX}{'a' * 63}\x00",
        f"{V2_KEY_PREFIX}{'A' * 64}",
        f"{V2_KEY_PREFIX}{'a' * 63}",
        f"{V2_KEY_PREFIX}{'a' * 65}",
        f"handoff-summary:1.0:{'a' * 64}",
        "",
        None,
        b"handoff-summary-v2:2.0:" + b"a" * 64,
        12345,
    ],
)
def test_cache_key_v2_digest_rejects_unsafe_or_foreign_keys(candidate):
    assert cache_key_module.cache_key_v2_digest(candidate) is None


def test_cache_key_v2_digest_accepts_a_generated_key():
    key = build_handoff_packet_cache_key_v2(v2_packet())

    assert cache_key_module.cache_key_v2_digest(key) == key[len(V2_KEY_PREFIX) :]


def test_build_from_source_fingerprint_rejects_non_digest_input():
    for candidate in ("", "not-hex", "A" * 64, "a" * 63, None, 5):
        with pytest.raises(ValueError):
            cache_key_module.build_cache_key_v2_from_source_fingerprint(candidate)
