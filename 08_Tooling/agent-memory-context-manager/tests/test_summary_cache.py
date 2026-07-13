import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_memory_context_manager import (  # noqa: E402
    DEFAULT_SUMMARY_CACHE_VERSION,
    build_handoff_packet,
    build_summary_cache_entry,
    read_summary_cache_entry,
    summary_cache_entry_exists,
    write_summary_cache_entry,
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
