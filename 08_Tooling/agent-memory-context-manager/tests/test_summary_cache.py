import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_memory_context_manager import (  # noqa: E402
    CACHE_ENTRY_V2_FIELDS,
    CACHE_ENTRY_VERSION_V2,
    DEFAULT_SUMMARY_CACHE_VERSION,
    MAX_CACHE_ENTRY_BYTES,
    MAX_CACHE_ENTRY_COLLECTION_ENTRIES,
    MAX_CACHE_ENTRY_DEPTH,
    MAX_CACHE_ENTRY_STRING_CHARS,
    MISS_MALFORMED_OR_OVERSIZED,
    MISS_TRUST_NOT_CURRENT,
    MISS_UNSAFE_PATH_OR_ENTRY,
    MISS_UNSUPPORTED_VERSION,
    RENDERER_VERSION,
    SUMMARY_CACHE_MISS_REASONS,
    SUPPORTED_PACKET_SCHEMA_VERSION,
    RenderingEvidence,
    SummaryCacheWriteError,
    build_handoff_packet,
    build_handoff_packet_cache_key_v2,
    build_summary_cache_entry,
    build_summary_cache_entry_v2,
    handoff_packet_source_fingerprint,
    read_summary_cache_entry,
    summarize_handoff_packet,
    summary_cache_entry_exists,
    validate_summary_cache_entry_v2,
    write_summary_cache_entry,
)
from agent_memory_context_manager import summary_cache as summary_cache_module  # noqa: E402
from agent_memory_context_manager.summary_cache import (  # noqa: E402
    _parse_cache_entry_v2_bytes,
    _serialize_cache_entry_v2,
    _StrictJsonError,
)


def sample_packet():
    return build_handoff_packet(
        objective="Cache compact handoff summaries",
        current_phase="Memory 1D",
        branch="claude/agent-memory-context-manager-1d-summary-cache-helpers",
        pr_number=0,
        changed_files=["summary_cache.py", "test_summary_cache.py"],
        allowed_inspect_first=["summary_cache.py"],
        forbidden_unless_needed=["Workflow Scheduler source"],
        known_facts=["Memory 1C summary helpers are merged"],
        prior_decisions=["Use JSON cache storage"],
        acceptance_criteria=["Cache entries round-trip through JSON"],
        validation_commands=["PYTHONPATH=src python -m pytest tests/test_summary_cache.py -q"],
        stop_conditions=["Need Scheduler integration"],
    )


def test_building_cache_entry_with_required_fields():
    packet = sample_packet()

    entry = build_summary_cache_entry(
        cache_key="memory-1d",
        summary="Compact summary text",
        source_packet=packet,
        metadata={"source": "test"},
    )

    assert entry["version"] == DEFAULT_SUMMARY_CACHE_VERSION
    assert entry["cache_key"] == "memory-1d"
    assert entry["summary"] == "Compact summary text"
    assert entry["source_packet"] == packet
    assert entry["metadata"] == {"source": "test"}


def test_metadata_defaults_to_empty_dict():
    entry = build_summary_cache_entry(
        cache_key="memory-1d",
        summary="Compact summary text",
        source_packet=sample_packet(),
    )

    assert entry["metadata"] == {}


def test_input_metadata_is_not_mutated():
    metadata = {"labels": ["memory", "cache"]}
    original_metadata = copy.deepcopy(metadata)

    entry = build_summary_cache_entry(
        cache_key="memory-1d",
        summary="Compact summary text",
        source_packet=sample_packet(),
        metadata=metadata,
    )
    entry["metadata"]["labels"].append("mutated")

    assert metadata == original_metadata


def test_input_source_packet_is_not_mutated():
    packet = sample_packet()
    original_packet = copy.deepcopy(packet)

    entry = build_summary_cache_entry(
        cache_key="memory-1d",
        summary="Compact summary text",
        source_packet=packet,
    )
    entry["source_packet"]["known_facts"].append("mutated")

    assert packet == original_packet


def test_invalid_empty_cache_key_raises_value_error():
    with pytest.raises(ValueError, match="cache_key must be a non-empty string"):
        build_summary_cache_entry(
            cache_key="",
            summary="Compact summary text",
            source_packet=sample_packet(),
        )


def test_invalid_empty_summary_raises_value_error():
    with pytest.raises(ValueError, match="summary must be a non-empty string"):
        build_summary_cache_entry(
            cache_key="memory-1d",
            summary="",
            source_packet=sample_packet(),
        )


def test_non_dict_like_source_packet_raises_value_error():
    with pytest.raises(ValueError, match="source_packet must be a dict-like mapping"):
        build_summary_cache_entry(
            cache_key="memory-1d",
            summary="Compact summary text",
            source_packet="not a packet",
        )


def test_write_creates_parent_directories(tmp_path):
    entry = build_summary_cache_entry(
        cache_key="memory-1d",
        summary="Compact summary text",
        source_packet=sample_packet(),
    )
    path = tmp_path / "nested" / "cache" / "entry.json"

    write_summary_cache_entry(path, entry)

    assert path.is_file()


def test_read_returns_written_entry(tmp_path):
    entry = build_summary_cache_entry(
        cache_key="memory-1d",
        summary="Compact summary text",
        source_packet=sample_packet(),
        metadata={"source": "test"},
    )
    path = tmp_path / "entry.json"

    write_summary_cache_entry(path, entry)

    assert read_summary_cache_entry(path) == entry


def test_exists_returns_false_before_write_and_true_after_write(tmp_path):
    path = tmp_path / "entry.json"

    assert summary_cache_entry_exists(path) is False

    entry = build_summary_cache_entry(
        cache_key="memory-1d",
        summary="Compact summary text",
        source_packet=sample_packet(),
    )
    write_summary_cache_entry(path, entry)

    assert summary_cache_entry_exists(path) is True


# --- Cache contract v2 -------------------------------------------------------


def v2_packet(**overrides):
    fields = {
        "objective": "Implement cache contract v2",
        "current_phase": "Memory H3",
        "branch": None,
        "pr_number": None,
        "changed_files": ["summary_cache.py"],
        "allowed_inspect_first": ["cache_key.py"],
        "forbidden_unless_needed": ["Workflow Scheduler source"],
        "known_facts": ["Memory H2 is merged"],
        "prior_decisions": ["Reuse H2 canonical identities"],
        "acceptance_criteria": ["Entries verify fail closed"],
        "validation_commands": ["PYTHONPATH=src python -m pytest tests -q"],
        "stop_conditions": ["Needs a scope decision"],
    }
    fields.update(overrides)
    return build_handoff_packet(**fields)


def current_evidence(packet, producer="memory-h3-test"):
    return RenderingEvidence(
        producer=producer,
        packet_schema_version=SUPPORTED_PACKET_SCHEMA_VERSION,
        renderer_version=RENDERER_VERSION,
        provenance_status="supplied",
        source_fingerprint=handoff_packet_source_fingerprint(packet),
    )


def valid_v2_entry(packet=None, producer="memory-h3-test"):
    packet = packet if packet is not None else v2_packet()
    rendered = summarize_handoff_packet(packet, evidence=current_evidence(packet, producer))
    assert rendered.trust_status == "current"
    return build_summary_cache_entry_v2(
        cache_key=build_handoff_packet_cache_key_v2(packet),
        producer=rendered.producer,
        provenance_status=rendered.provenance_status,
        source_fingerprint=rendered.source_fingerprint,
        summary_fingerprint=rendered.summary_fingerprint,
        trust_status=rendered.trust_status,
        summary=rendered.text,
        source_packet=packet,
    )


def test_valid_v2_entry_passes_shared_validation():
    assert validate_summary_cache_entry_v2(valid_v2_entry()) is None


def test_v2_entry_has_exactly_the_required_field_set():
    entry = valid_v2_entry()

    assert sorted(entry) == sorted(CACHE_ENTRY_V2_FIELDS)


def test_v2_entry_carries_no_metadata_field():
    """The v1 optional metadata contract is deliberately not carried forward."""
    assert "metadata" not in valid_v2_entry()
    assert "metadata" not in CACHE_ENTRY_V2_FIELDS


def test_v2_entry_binds_every_required_identity():
    entry = valid_v2_entry()

    assert entry["cache_entry_version"] == CACHE_ENTRY_VERSION_V2
    assert entry["packet_schema_version"] == SUPPORTED_PACKET_SCHEMA_VERSION
    assert entry["renderer_version"] == RENDERER_VERSION
    assert entry["trust_status"] == "current"
    assert entry["provenance_status"] == "supplied"
    assert len(entry["source_fingerprint"]) == 64
    assert len(entry["summary_fingerprint"]) == 64
    assert entry["source_packet"] == v2_packet()


def test_v2_entry_build_does_not_mutate_source_packet():
    packet = v2_packet()
    original = copy.deepcopy(packet)

    entry = valid_v2_entry(packet)
    entry["source_packet"]["known_facts"].append("mutated")

    assert packet == original


@pytest.mark.parametrize("field", CACHE_ENTRY_V2_FIELDS)
def test_missing_required_field_is_rejected(field):
    entry = valid_v2_entry()
    del entry[field]

    assert validate_summary_cache_entry_v2(entry) == MISS_MALFORMED_OR_OVERSIZED


def test_unexpected_field_is_rejected():
    entry = valid_v2_entry()
    entry["metadata"] = {"source": "test"}

    assert validate_summary_cache_entry_v2(entry) == MISS_MALFORMED_OR_OVERSIZED


@pytest.mark.parametrize(
    "field,value",
    [
        ("cache_entry_version", 2),
        ("cache_key", None),
        ("producer", ["memory-h3"]),
        ("summary", 42),
        ("source_fingerprint", True),
        ("source_packet", "not-a-packet"),
        ("source_packet", []),
        ("trust_status", 1),
    ],
)
def test_wrong_exact_types_are_rejected(field, value):
    entry = valid_v2_entry()
    entry[field] = value

    assert validate_summary_cache_entry_v2(entry) == MISS_MALFORMED_OR_OVERSIZED


@pytest.mark.parametrize(
    "field",
    [
        "cache_entry_version",
        "cache_key_version",
        "cache_namespace_version",
        "packet_schema_version",
        "renderer_version",
    ],
)
def test_unsupported_version_bindings_are_rejected(field):
    entry = valid_v2_entry()
    entry[field] = "9.9-unsupported"

    assert validate_summary_cache_entry_v2(entry) == MISS_UNSUPPORTED_VERSION


@pytest.mark.parametrize("trust_status", ["stale", "unsupported", "unverifiable", "CURRENT"])
def test_non_current_trust_status_is_rejected(trust_status):
    entry = valid_v2_entry()
    entry["trust_status"] = trust_status

    assert validate_summary_cache_entry_v2(entry) == MISS_TRUST_NOT_CURRENT


def test_unsafe_cache_key_shape_is_rejected():
    entry = valid_v2_entry()
    entry["cache_key"] = "handoff-summary-v2:2.0:../../etc/passwd"

    assert validate_summary_cache_entry_v2(entry) == MISS_UNSAFE_PATH_OR_ENTRY


@pytest.mark.parametrize("field", ["source_fingerprint", "summary_fingerprint"])
def test_malformed_fingerprints_are_rejected(field):
    entry = valid_v2_entry()
    entry[field] = "not-a-sha256-digest"

    assert validate_summary_cache_entry_v2(entry) == MISS_MALFORMED_OR_OVERSIZED


@pytest.mark.parametrize("producer", ["", "   ", " leading", "trailing ", "a\x00b", "x" * 129])
def test_unsafe_producer_values_are_rejected(producer):
    entry = valid_v2_entry()
    entry["producer"] = producer

    assert validate_summary_cache_entry_v2(entry) == MISS_MALFORMED_OR_OVERSIZED


def test_empty_summary_is_rejected():
    entry = valid_v2_entry()
    entry["summary"] = ""

    assert validate_summary_cache_entry_v2(entry) == MISS_MALFORMED_OR_OVERSIZED


def test_builder_raises_fail_closed_for_an_invalid_entry():
    packet = v2_packet()
    with pytest.raises(SummaryCacheWriteError) as excinfo:
        build_summary_cache_entry_v2(
            cache_key="not-a-v2-key",
            producer="memory-h3-test",
            provenance_status="supplied",
            source_fingerprint="a" * 64,
            summary_fingerprint="b" * 64,
            trust_status="current",
            summary="text",
            source_packet=packet,
        )

    assert excinfo.value.reason in SUMMARY_CACHE_MISS_REASONS


def test_non_dict_entry_is_rejected():
    assert validate_summary_cache_entry_v2(["not", "a", "dict"]) == MISS_MALFORMED_OR_OVERSIZED
    assert validate_summary_cache_entry_v2(None) == MISS_MALFORMED_OR_OVERSIZED


# --- Deterministic serialization --------------------------------------------


def test_serialization_is_byte_identical_for_identical_entries():
    assert _serialize_cache_entry_v2(valid_v2_entry()) == _serialize_cache_entry_v2(
        valid_v2_entry()
    )


def test_serialized_entry_round_trips_exactly():
    entry = valid_v2_entry()

    assert _parse_cache_entry_v2_bytes(_serialize_cache_entry_v2(entry)) == entry


def test_serialization_preserves_compute_limit_key_order():
    """H2 renders compute limits in insertion order, so order is stored evidence."""
    packet = v2_packet()
    packet["compute_limits"] = {
        key: packet["compute_limits"][key]
        for key in reversed(list(packet["compute_limits"]))
    }
    entry = valid_v2_entry(packet)

    parsed = _parse_cache_entry_v2_bytes(_serialize_cache_entry_v2(entry))

    assert list(parsed["source_packet"]["compute_limits"]) == list(
        packet["compute_limits"]
    )


def test_serialization_rejects_an_oversized_entry():
    entry = valid_v2_entry()
    entry["summary"] = "x" * (MAX_CACHE_ENTRY_BYTES + 10)

    with pytest.raises(_StrictJsonError):
        _serialize_cache_entry_v2(entry)


# --- Strict bounded JSON boundary -------------------------------------------


def test_oversized_bytes_are_rejected_before_any_parsing(monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("json.loads must not be reached for oversized input")

    monkeypatch.setattr(summary_cache_module.json, "loads", explode)
    payload = b"[" + b"0," * MAX_CACHE_ENTRY_BYTES + b"]"
    assert len(payload) > MAX_CACHE_ENTRY_BYTES

    with pytest.raises(_StrictJsonError):
        _parse_cache_entry_v2_bytes(payload)


def test_byte_gate_is_inclusive_at_the_limit_and_exclusive_above_it(monkeypatch):
    """A document of exactly MAX bytes reaches the parser; one byte more does not."""
    calls = []

    def spy(text, **kwargs):
        calls.append(len(text))
        raise _StrictJsonError

    monkeypatch.setattr(summary_cache_module.json, "loads", spy)

    at_limit = b'{"a":"' + b"x" * (MAX_CACHE_ENTRY_BYTES - 8) + b'"}'
    assert len(at_limit) == MAX_CACHE_ENTRY_BYTES
    with pytest.raises(_StrictJsonError):
        _parse_cache_entry_v2_bytes(at_limit)
    assert calls == [MAX_CACHE_ENTRY_BYTES]

    over_limit = at_limit + b" "
    with pytest.raises(_StrictJsonError):
        _parse_cache_entry_v2_bytes(over_limit)
    assert calls == [MAX_CACHE_ENTRY_BYTES]


def test_a_real_entry_stays_far_below_the_byte_limit():
    payload = _serialize_cache_entry_v2(valid_v2_entry())

    assert 0 < len(payload) < MAX_CACHE_ENTRY_BYTES // 4


def test_invalid_utf8_is_rejected():
    with pytest.raises(_StrictJsonError):
        _parse_cache_entry_v2_bytes(b'{"a": "\xff\xfe"}')


def test_duplicate_object_names_are_rejected():
    with pytest.raises(_StrictJsonError):
        _parse_cache_entry_v2_bytes(b'{"trust_status":"current","trust_status":"stale"}')


def test_nested_duplicate_object_names_are_rejected():
    with pytest.raises(_StrictJsonError):
        _parse_cache_entry_v2_bytes(b'{"a": {"b": 1, "b": 2}}')


@pytest.mark.parametrize("literal", [b"NaN", b"Infinity", b"-Infinity"])
def test_non_finite_numbers_are_rejected(literal):
    with pytest.raises(_StrictJsonError):
        _parse_cache_entry_v2_bytes(b'{"a": ' + literal + b"}")


def test_floats_are_rejected():
    with pytest.raises(_StrictJsonError):
        _parse_cache_entry_v2_bytes(b'{"a": 1.5}')


@pytest.mark.parametrize("payload", [b'["a"]', b'"a"', b"12", b"null", b"true"])
def test_non_dict_top_level_documents_are_rejected(payload):
    with pytest.raises(_StrictJsonError):
        _parse_cache_entry_v2_bytes(payload)


def test_malformed_json_is_rejected():
    with pytest.raises(_StrictJsonError):
        _parse_cache_entry_v2_bytes(b'{"a": ')


def test_excessive_depth_is_rejected():
    depth = MAX_CACHE_ENTRY_DEPTH + 2
    payload = b'{"a":' + b"[" * depth + b"]" * depth + b"}"

    with pytest.raises(_StrictJsonError):
        _parse_cache_entry_v2_bytes(payload)


def test_deeply_nested_document_does_not_reach_the_parser(monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("json.loads must not be reached for over-deep input")

    monkeypatch.setattr(summary_cache_module.json, "loads", explode)
    depth = 5_000
    payload = b"[" * depth + b"]" * depth

    with pytest.raises(_StrictJsonError):
        _parse_cache_entry_v2_bytes(payload)


def test_depth_prescan_ignores_brackets_inside_strings():
    payload = b'{"a": "[[[[[[[[[[[[[[[[ \\" {{{{{{{{{{"}'

    assert _parse_cache_entry_v2_bytes(payload) == {"a": '[[[[[[[[[[[[[[[[ " {{{{{{{{{{'}


def test_excessive_collection_entries_are_rejected():
    count = MAX_CACHE_ENTRY_COLLECTION_ENTRIES + 1
    payload = b'{"a": [' + b",".join(b"0" for _ in range(count)) + b"]}"

    with pytest.raises(_StrictJsonError):
        _parse_cache_entry_v2_bytes(payload)


def test_excessive_node_count_is_rejected(monkeypatch):
    monkeypatch.setattr(summary_cache_module, "MAX_CACHE_ENTRY_NODES", 10)
    payload = b'{"a": [' + b",".join(b"0" for _ in range(50)) + b"]}"

    with pytest.raises(_StrictJsonError):
        _parse_cache_entry_v2_bytes(payload)


def test_excessive_string_length_is_rejected():
    payload = b'{"a": "' + b"x" * (MAX_CACHE_ENTRY_STRING_CHARS + 1) + b'"}'

    with pytest.raises(_StrictJsonError):
        _parse_cache_entry_v2_bytes(payload)


def test_excessive_total_string_content_is_rejected(monkeypatch):
    monkeypatch.setattr(summary_cache_module, "MAX_CACHE_ENTRY_TOTAL_STRING_BYTES", 32)
    payload = b'{"a": "' + b"x" * 20 + b'", "b": "' + b"y" * 20 + b'"}'

    with pytest.raises(_StrictJsonError):
        _parse_cache_entry_v2_bytes(payload)


def test_exact_builtin_types_are_enforced_for_parsed_documents():
    assert _parse_cache_entry_v2_bytes(
        b'{"s": "t", "i": 3, "b": true, "n": null, "l": [1], "d": {"k": "v"}}'
    ) == {"s": "t", "i": 3, "b": True, "n": None, "l": [1], "d": {"k": "v"}}


def test_bounded_structure_rejects_non_builtin_values():
    class Hostile:
        def __repr__(self):
            raise AssertionError("repr must never be invoked")

    with pytest.raises(_StrictJsonError):
        summary_cache_module._assert_bounded_structure({"a": Hostile()})


def test_bounded_structure_rejects_non_string_mapping_keys():
    with pytest.raises(_StrictJsonError):
        summary_cache_module._assert_bounded_structure({1: "value"})


def test_bounded_structure_rejects_int_subclass_values():
    class SneakyInt(int):
        pass

    with pytest.raises(_StrictJsonError):
        summary_cache_module._assert_bounded_structure({"a": SneakyInt(1)})
