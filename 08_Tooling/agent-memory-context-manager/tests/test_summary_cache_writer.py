import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_memory_context_manager import (  # noqa: E402
    build_handoff_packet,
    build_handoff_packet_cache_key,
    read_summary_cache_entry,
    write_summary_cache_for_packet,
)


def sample_packet():
    return build_handoff_packet(
        objective="Write reusable summary cache entries",
        current_phase="Memory 1G",
        branch="claude/agent-memory-context-manager-1g-summary-cache-write-from-packet",
        pr_number=0,
        changed_files=["summary_cache_writer.py", "test_summary_cache_writer.py"],
        allowed_inspect_first=["summary_cache_writer.py"],
        forbidden_unless_needed=["Workflow Scheduler source"],
        known_facts=["Memory 1F summary cache lookup helpers are merged"],
        prior_decisions=["Use deterministic handoff packet cache keys"],
        acceptance_criteria=["Cache entries are written from packets"],
        validation_commands=[
            "PYTHONPATH=src python -m pytest tests/test_summary_cache_writer.py -q"
        ],
        stop_conditions=["Need Scheduler integration"],
    )


def test_writes_cache_file_for_valid_packet(tmp_path):
    path, _entry = write_summary_cache_for_packet(
        tmp_path,
        sample_packet(),
        "Reusable summary text",
    )

    assert path.is_file()


def test_returned_path_is_under_cache_dir(tmp_path):
    path, _entry = write_summary_cache_for_packet(
        tmp_path,
        sample_packet(),
        "Reusable summary text",
    )

    assert path.parent == tmp_path


def test_returned_entry_has_deterministic_cache_key(tmp_path):
    packet = sample_packet()
    expected_cache_key = build_handoff_packet_cache_key(packet)

    _path, entry = write_summary_cache_for_packet(
        tmp_path,
        packet,
        "Reusable summary text",
    )

    assert entry["cache_key"] == expected_cache_key


def test_written_file_can_be_read_back_and_matches_returned_entry(tmp_path):
    path, entry = write_summary_cache_for_packet(
        tmp_path,
        sample_packet(),
        "Reusable summary text",
    )

    assert read_summary_cache_entry(path) == entry


def test_metadata_is_included(tmp_path):
    _path, entry = write_summary_cache_for_packet(
        tmp_path,
        sample_packet(),
        "Reusable summary text",
        metadata={"source": "test"},
    )

    assert entry["metadata"] == {"source": "test"}


def test_input_packet_is_not_mutated(tmp_path):
    packet = sample_packet()
    original_packet = copy.deepcopy(packet)

    write_summary_cache_for_packet(tmp_path, packet, "Reusable summary text")

    assert packet == original_packet


def test_input_metadata_is_not_mutated(tmp_path):
    metadata = {"labels": ["memory", "writer"]}
    original_metadata = copy.deepcopy(metadata)

    _path, entry = write_summary_cache_for_packet(
        tmp_path,
        sample_packet(),
        "Reusable summary text",
        metadata=metadata,
    )
    entry["metadata"]["labels"].append("mutated")

    assert metadata == original_metadata


def test_invalid_packet_raises_value_error(tmp_path):
    packet = sample_packet()
    del packet["objective"]

    with pytest.raises(ValueError, match="Invalid handoff packet"):
        write_summary_cache_for_packet(tmp_path, packet, "Reusable summary text")


def test_empty_summary_raises_value_error(tmp_path):
    with pytest.raises(ValueError, match="summary must be a non-empty string"):
        write_summary_cache_for_packet(tmp_path, sample_packet(), "")
