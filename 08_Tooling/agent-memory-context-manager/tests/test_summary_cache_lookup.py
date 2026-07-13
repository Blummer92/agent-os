import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_memory_context_manager import (  # noqa: E402
    build_handoff_packet,
    build_handoff_packet_cache_key,
    build_summary_cache_entry,
    build_summary_cache_path,
    lookup_summary_cache_entry,
    write_summary_cache_entry,
)


def sample_packet():
    return build_handoff_packet(
        objective="Look up reusable summary cache entries",
        current_phase="Memory 1F",
        branch="claude/agent-memory-context-manager-1f-summary-cache-lookup",
        pr_number=0,
        changed_files=["summary_cache_lookup.py", "test_summary_cache_lookup.py"],
        allowed_inspect_first=["summary_cache_lookup.py"],
        forbidden_unless_needed=["Workflow Scheduler source"],
        known_facts=["Memory 1E cache key helpers are merged"],
        prior_decisions=["Use deterministic handoff packet cache keys"],
        acceptance_criteria=["Matching cache entries are returned"],
        validation_commands=[
            "PYTHONPATH=src python -m pytest tests/test_summary_cache_lookup.py -q"
        ],
        stop_conditions=["Need Scheduler integration"],
    )


def test_build_summary_cache_path_returns_path_under_cache_dir(tmp_path):
    path = build_summary_cache_path(tmp_path, "cache-key")

    assert path == tmp_path / "cache-key.json"


def test_cache_path_replaces_slashes_with_underscores(tmp_path):
    path = build_summary_cache_path(tmp_path, "handoff/summary/key")

    assert path == tmp_path / "handoff_summary_key.json"


def test_lookup_returns_none_when_no_cache_file_exists(tmp_path):
    assert lookup_summary_cache_entry(tmp_path, sample_packet()) is None


def test_lookup_returns_entry_when_matching_cache_entry_exists(tmp_path):
    packet = sample_packet()
    cache_key = build_handoff_packet_cache_key(packet)
    entry = build_summary_cache_entry(
        cache_key=cache_key,
        summary="Reusable summary text",
        source_packet=packet,
    )
    path = build_summary_cache_path(tmp_path, cache_key)
    write_summary_cache_entry(path, entry)

    assert lookup_summary_cache_entry(tmp_path, packet) == entry


def test_lookup_returns_none_when_stored_cache_key_does_not_match(tmp_path):
    packet = sample_packet()
    cache_key = build_handoff_packet_cache_key(packet)
    entry = build_summary_cache_entry(
        cache_key="different-cache-key",
        summary="Stale summary text",
        source_packet=packet,
    )
    path = build_summary_cache_path(tmp_path, cache_key)
    write_summary_cache_entry(path, entry)

    assert lookup_summary_cache_entry(tmp_path, packet) is None


def test_lookup_does_not_mutate_packet(tmp_path):
    packet = sample_packet()
    original_packet = copy.deepcopy(packet)
    cache_key = build_handoff_packet_cache_key(packet)
    entry = build_summary_cache_entry(
        cache_key=cache_key,
        summary="Reusable summary text",
        source_packet=packet,
    )
    path = build_summary_cache_path(tmp_path, cache_key)
    write_summary_cache_entry(path, entry)

    lookup_summary_cache_entry(tmp_path, packet)

    assert packet == original_packet
