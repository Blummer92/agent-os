import builtins
import copy
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_memory_context_manager import (  # noqa: E402
    CACHE_NAMESPACE_V2,
    MAX_CACHE_ENTRY_BYTES,
    MISS_IDENTITY_MISMATCH,
    MISS_LOCAL_IO_UNAVAILABLE,
    MISS_MALFORMED_OR_OVERSIZED,
    MISS_NOT_FOUND,
    MISS_TRUST_NOT_CURRENT,
    MISS_UNSAFE_PATH_OR_ENTRY,
    MISS_UNSUPPORTED_VERSION,
    RENDERER_VERSION,
    SUMMARY_CACHE_MISS_REASONS,
    SUPPORTED_PACKET_SCHEMA_VERSION,
    RenderingEvidence,
    build_handoff_packet,
    build_handoff_packet_cache_key,
    build_handoff_packet_cache_key_v2,
    build_summary_cache_entry,
    build_summary_cache_namespace_v2,
    build_summary_cache_path,
    build_summary_cache_path_v2,
    handoff_packet_source_fingerprint,
    lookup_summary_cache_entry,
    lookup_summary_cache_v2,
    write_summary_cache_entry,
    write_summary_cache_for_packet,
    write_summary_cache_v2,
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


def test_cache_path_replaces_windows_reserved_chars(tmp_path):
    path = build_summary_cache_path(tmp_path, "handoff-summary:1.0:key")

    assert path == tmp_path / "handoff-summary_1.0_key.json"


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


# --- Cache contract v2 -------------------------------------------------------


SECRET_MARKER = "SUPER-SECRET-CALLER-VALUE"


def v2_packet(**overrides):
    fields = {
        "objective": "Implement cache contract v2",
        "current_phase": "Memory H3",
        "branch": None,
        "pr_number": None,
        "changed_files": ["summary_cache_lookup.py"],
        "allowed_inspect_first": ["cache_key.py"],
        "forbidden_unless_needed": ["Workflow Scheduler source"],
        "known_facts": ["Memory H2 is merged"],
        "prior_decisions": ["Reuse H2 canonical identities"],
        "acceptance_criteria": ["Lookup verifies fail closed"],
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


def seed_entry(cache_root, packet=None, producer="memory-h3-test"):
    packet = packet if packet is not None else v2_packet()
    return write_summary_cache_v2(cache_root, packet, evidence=current_evidence(packet, producer))


def rewrite_entry(path, mutate):
    entry = json.loads(Path(path).read_text(encoding="utf-8"))
    mutate(entry)
    Path(path).write_text(
        json.dumps(entry, separators=(",", ":"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


class RecordingOpen:
    """Wrap builtins.open so tests can prove exactly what lookup touches."""

    def __init__(self):
        self.paths = []
        self._real = builtins.open

    def __call__(self, file, *args, **kwargs):
        self.paths.append(os.fspath(file))
        return self._real(file, *args, **kwargs)


# --- Namespace and path containment -----------------------------------------


def test_v2_namespace_is_a_fixed_child_of_the_cache_root(tmp_path):
    assert build_summary_cache_namespace_v2(tmp_path) == tmp_path / CACHE_NAMESPACE_V2


def test_v2_path_is_the_digest_inside_the_namespace(tmp_path):
    key = build_handoff_packet_cache_key_v2(v2_packet())
    digest = key.rsplit(":", 1)[1]

    path = build_summary_cache_path_v2(tmp_path, key)

    assert path == tmp_path / CACHE_NAMESPACE_V2 / f"{digest}.json"
    assert path.parent.parent == tmp_path


def test_v2_path_never_derives_from_arbitrary_caller_text(tmp_path):
    key = build_handoff_packet_cache_key_v2(v2_packet(objective=SECRET_MARKER))

    path = build_summary_cache_path_v2(tmp_path, key)

    assert SECRET_MARKER not in str(path)


@pytest.mark.parametrize(
    "cache_key",
    [
        "/etc/passwd",
        "../../etc/passwd",
        "handoff-summary-v2:2.0:../../etc/passwd",
        "handoff-summary-v2:2.0:..",
        "handoff-summary-v2:2.0:/absolute",
        "handoff-summary-v2:2.0:sub/dir",
        "handoff-summary-v2:2.0:sub\\dir",
        "handoff-summary-v2:2.0:C:\\Windows",
        "handoff-summary-v2:2.0:\\\\server\\share",
        "handoff-summary-v2:2.0:CON",
        "handoff-summary-v2:2.0:" + "a" * 63 + ".",
        "handoff-summary-v2:2.0:" + "a" * 63 + " ",
        "handoff-summary-v2:2.0:" + "a" * 63 + "\x00",
        "handoff-summary:1.0:" + "a" * 64,
        "",
    ],
)
def test_unsafe_cache_keys_are_rejected_for_path_derivation(tmp_path, cache_key):
    with pytest.raises(ValueError):
        build_summary_cache_path_v2(tmp_path, cache_key)


def test_written_entry_stays_inside_the_v2_namespace(tmp_path):
    path, _entry = seed_entry(tmp_path)

    assert path.parent == tmp_path / CACHE_NAMESPACE_V2
    assert path.is_file()
    written = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert written == [path]


# --- Successful verified reuse ----------------------------------------------


def test_lookup_returns_the_written_entry(tmp_path):
    _path, entry = seed_entry(tmp_path)

    result = lookup_summary_cache_v2(tmp_path, v2_packet())

    assert result.hit is True
    assert result.miss_reason is None
    assert result.entry == entry


def test_lookup_round_trip_does_not_mutate_the_packet(tmp_path):
    packet = v2_packet()
    original = copy.deepcopy(packet)
    seed_entry(tmp_path, packet)

    lookup_summary_cache_v2(tmp_path, packet)

    assert packet == original


def test_lookup_is_deterministic_across_repeated_calls(tmp_path):
    seed_entry(tmp_path)
    packet = v2_packet()

    first = lookup_summary_cache_v2(tmp_path, packet)
    second = lookup_summary_cache_v2(tmp_path, packet)

    assert first == second


def test_missing_entry_is_a_plain_not_found_miss(tmp_path):
    result = lookup_summary_cache_v2(tmp_path, v2_packet())

    assert result.hit is False
    assert result.miss_reason == MISS_NOT_FOUND


def test_a_different_packet_does_not_hit_a_stored_entry(tmp_path):
    seed_entry(tmp_path)

    result = lookup_summary_cache_v2(tmp_path, v2_packet(objective="something else"))

    assert result.hit is False
    assert result.miss_reason == MISS_NOT_FOUND


# --- Fail-closed verification ------------------------------------------------


@pytest.mark.parametrize(
    "field,value,expected",
    [
        ("cache_entry_version", "1.0", MISS_UNSUPPORTED_VERSION),
        ("cache_key_version", "1.0", MISS_UNSUPPORTED_VERSION),
        ("cache_namespace_version", "1.0", MISS_UNSUPPORTED_VERSION),
        ("packet_schema_version", "handoff-packet-v1", MISS_UNSUPPORTED_VERSION),
        ("renderer_version", "packet-summary-h1", MISS_UNSUPPORTED_VERSION),
        ("trust_status", "stale", MISS_TRUST_NOT_CURRENT),
        ("trust_status", "unsupported", MISS_TRUST_NOT_CURRENT),
        ("trust_status", "unverifiable", MISS_TRUST_NOT_CURRENT),
        # A fingerprint that no longer matches the stored packet is classified
        # stale by the canonical H2 renderer, so reuse is refused as not-current.
        ("source_fingerprint", "a" * 64, MISS_TRUST_NOT_CURRENT),
        ("summary_fingerprint", "b" * 64, MISS_IDENTITY_MISMATCH),
        ("summary", "a detached but plausible summary", MISS_IDENTITY_MISMATCH),
        ("producer", "a-different-producer", MISS_IDENTITY_MISMATCH),
        ("provenance_status", "detached", MISS_TRUST_NOT_CURRENT),
        ("cache_key", "handoff-summary-v2:2.0:" + "c" * 64, MISS_IDENTITY_MISMATCH),
    ],
)
def test_every_tampered_binding_fails_closed(tmp_path, field, value, expected):
    path, _entry = seed_entry(tmp_path)
    rewrite_entry(path, lambda entry: entry.__setitem__(field, value))

    result = lookup_summary_cache_v2(tmp_path, v2_packet())

    assert result.hit is False
    assert result.miss_reason == expected


def test_tampered_source_packet_fails_closed(tmp_path):
    """Swapping the stored packet detaches it from its fingerprint and summary."""
    path, _entry = seed_entry(tmp_path)
    rewrite_entry(
        path, lambda entry: entry["source_packet"].__setitem__("objective", "swapped")
    )

    result = lookup_summary_cache_v2(tmp_path, v2_packet())

    assert result.hit is False
    assert result.miss_reason == MISS_TRUST_NOT_CURRENT


def test_packet_swapped_together_with_its_fingerprint_still_fails_closed(tmp_path):
    """A self-consistent entry for a different packet must not satisfy this key."""
    other = v2_packet(objective="a different objective entirely")
    other_path, other_entry = seed_entry(tmp_path, other)
    target_path = build_summary_cache_path_v2(
        tmp_path, build_handoff_packet_cache_key_v2(v2_packet())
    )
    target_path.write_bytes(other_path.read_bytes())

    result = lookup_summary_cache_v2(tmp_path, v2_packet())

    assert result.hit is False
    assert result.miss_reason == MISS_IDENTITY_MISMATCH


def test_entry_whose_stored_packet_is_invalid_fails_closed(tmp_path):
    path, _entry = seed_entry(tmp_path)
    rewrite_entry(path, lambda entry: entry["source_packet"].pop("objective"))

    result = lookup_summary_cache_v2(tmp_path, v2_packet())

    assert result.hit is False
    assert result.miss_reason == MISS_MALFORMED_OR_OVERSIZED


def test_entry_with_a_removed_field_fails_closed(tmp_path):
    path, _entry = seed_entry(tmp_path)
    rewrite_entry(path, lambda entry: entry.pop("summary_fingerprint"))

    result = lookup_summary_cache_v2(tmp_path, v2_packet())

    assert result.miss_reason == MISS_MALFORMED_OR_OVERSIZED


def test_entry_with_an_extra_field_fails_closed(tmp_path):
    path, _entry = seed_entry(tmp_path)
    rewrite_entry(path, lambda entry: entry.__setitem__("metadata", {"a": "b"}))

    result = lookup_summary_cache_v2(tmp_path, v2_packet())

    assert result.miss_reason == MISS_MALFORMED_OR_OVERSIZED


@pytest.mark.parametrize(
    "raw",
    [
        b"not json at all",
        b'{"cache_entry_version": ',
        b'["a","list"]',
        b'{"a": NaN}',
        b'{"a": 1.5}',
        b'{"a": "\xff"}',
        b'{"trust_status":"current","trust_status":"current"}',
        b"",
    ],
)
def test_corrupt_entry_documents_fail_closed(tmp_path, raw):
    path, _entry = seed_entry(tmp_path)
    path.write_bytes(raw)

    result = lookup_summary_cache_v2(tmp_path, v2_packet())

    assert result.hit is False
    assert result.miss_reason == MISS_MALFORMED_OR_OVERSIZED


def test_oversized_entry_file_fails_closed(tmp_path):
    path, _entry = seed_entry(tmp_path)
    path.write_bytes(b"{" + b" " * (MAX_CACHE_ENTRY_BYTES + 8))

    result = lookup_summary_cache_v2(tmp_path, v2_packet())

    assert result.miss_reason == MISS_MALFORMED_OR_OVERSIZED


def test_directory_at_the_entry_path_fails_closed(tmp_path):
    key = build_handoff_packet_cache_key_v2(v2_packet())
    path = build_summary_cache_path_v2(tmp_path, key)
    path.mkdir(parents=True)

    result = lookup_summary_cache_v2(tmp_path, v2_packet())

    assert result.miss_reason == MISS_UNSAFE_PATH_OR_ENTRY


def test_ineligible_packet_fails_closed_without_touching_the_filesystem(tmp_path):
    result = lookup_summary_cache_v2(tmp_path, v2_packet(changed_files=["f"] * 5_000))

    assert result.hit is False
    assert result.miss_reason == MISS_UNSAFE_PATH_OR_ENTRY


def test_invalid_packet_is_a_bounded_miss_and_never_a_hit(tmp_path):
    """Lookup is a query: an unusable packet yields a bounded miss, not an entry."""
    seed_entry(tmp_path)
    packet = v2_packet()
    del packet["objective"]

    result = lookup_summary_cache_v2(tmp_path, packet)

    assert result.entry is None
    assert result.miss_reason == MISS_UNSAFE_PATH_OR_ENTRY
    assert "objective" not in result.miss_reason


def test_local_io_failure_fails_closed(tmp_path, monkeypatch):
    seed_entry(tmp_path)

    def deny(*args, **kwargs):
        raise PermissionError("permission denied for /secret/path")

    monkeypatch.setattr(builtins, "open", deny)
    result = lookup_summary_cache_v2(tmp_path, v2_packet())

    assert result.miss_reason == MISS_LOCAL_IO_UNAVAILABLE


# --- No v1 or unversioned fallback ------------------------------------------


def test_v2_lookup_never_opens_a_root_level_v1_entry(tmp_path, monkeypatch):
    packet = v2_packet()
    v1_path, _v1_entry = write_summary_cache_for_packet(
        tmp_path, packet, "legacy v1 summary text"
    )
    assert v1_path.is_file()

    recorder = RecordingOpen()
    monkeypatch.setattr(builtins, "open", recorder)
    result = lookup_summary_cache_v2(tmp_path, packet)
    monkeypatch.undo()

    assert result.hit is False
    assert result.miss_reason == MISS_NOT_FOUND
    assert os.fspath(v1_path) not in recorder.paths
    assert all(CACHE_NAMESPACE_V2 in p for p in recorder.paths)


def test_v2_lookup_leaves_v1_files_untouched(tmp_path):
    packet = v2_packet()
    v1_path, v1_entry = write_summary_cache_for_packet(
        tmp_path, packet, "legacy v1 summary text"
    )
    before_bytes = v1_path.read_bytes()
    before_stat = v1_path.stat().st_mtime_ns

    seed_entry(tmp_path, packet)
    lookup_summary_cache_v2(tmp_path, packet)

    assert v1_path.is_file()
    assert v1_path.read_bytes() == before_bytes
    assert v1_path.stat().st_mtime_ns == before_stat
    assert lookup_summary_cache_entry(tmp_path, packet) == v1_entry


def test_v2_lookup_ignores_an_unversioned_entry_at_the_root(tmp_path):
    packet = v2_packet()
    _path, entry = seed_entry(tmp_path)
    key = build_handoff_packet_cache_key_v2(packet)
    digest = key.rsplit(":", 1)[1]
    root_copy = tmp_path / f"{digest}.json"
    root_copy.write_text(
        json.dumps(entry, separators=(",", ":"), ensure_ascii=False), encoding="utf-8"
    )
    (tmp_path / CACHE_NAMESPACE_V2 / f"{digest}.json").unlink()

    result = lookup_summary_cache_v2(tmp_path, packet)

    assert result.hit is False
    assert result.miss_reason == MISS_NOT_FOUND
    assert root_copy.is_file()


def test_v2_lookup_does_not_scan_the_namespace_directory(tmp_path):
    packet = v2_packet()
    _path, entry = seed_entry(tmp_path)
    namespace = tmp_path / CACHE_NAMESPACE_V2
    (namespace / f"{'d' * 64}.json").write_text(
        json.dumps(entry, separators=(",", ":"), ensure_ascii=False), encoding="utf-8"
    )
    (namespace / build_summary_cache_path_v2(tmp_path, entry["cache_key"]).name).unlink()

    result = lookup_summary_cache_v2(tmp_path, packet)

    assert result.hit is False
    assert result.miss_reason == MISS_NOT_FOUND


# --- Single bounded open, no check-then-read --------------------------------


def test_lookup_opens_the_entry_exactly_once_on_a_hit(tmp_path, monkeypatch):
    path, _entry = seed_entry(tmp_path)

    recorder = RecordingOpen()
    monkeypatch.setattr(builtins, "open", recorder)
    result = lookup_summary_cache_v2(tmp_path, v2_packet())
    monkeypatch.undo()

    assert result.hit is True
    assert recorder.paths == [os.fspath(path)]


def test_lookup_opens_the_entry_exactly_once_on_a_miss(tmp_path, monkeypatch):
    key = build_handoff_packet_cache_key_v2(v2_packet())
    expected = build_summary_cache_path_v2(tmp_path, key)

    recorder = RecordingOpen()
    monkeypatch.setattr(builtins, "open", recorder)
    result = lookup_summary_cache_v2(tmp_path, v2_packet())
    monkeypatch.undo()

    assert result.miss_reason == MISS_NOT_FOUND
    assert recorder.paths == [os.fspath(expected)]


def test_lookup_never_uses_an_existence_check_before_reading(tmp_path, monkeypatch):
    seed_entry(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("v2 lookup must not gate its read on an existence check")

    monkeypatch.setattr(Path, "exists", forbidden)
    monkeypatch.setattr(Path, "is_file", forbidden)
    monkeypatch.setattr(os.path, "exists", forbidden)

    assert lookup_summary_cache_v2(tmp_path, v2_packet()).hit is True
    assert lookup_summary_cache_v2(tmp_path, v2_packet(objective="absent")).hit is False


# --- Symlink boundary --------------------------------------------------------


def symlink_or_skip(link, target):
    try:
        os.symlink(os.fspath(target), os.fspath(link))
    except (OSError, NotImplementedError, AttributeError):
        pytest.skip("this platform does not support creating symlinks in this test")


def test_symlinked_entry_path_is_rejected(tmp_path):
    seed_entry(tmp_path)
    key = build_handoff_packet_cache_key_v2(v2_packet())
    path = build_summary_cache_path_v2(tmp_path, key)
    real = tmp_path / "elsewhere.json"
    real.write_bytes(path.read_bytes())
    path.unlink()
    symlink_or_skip(path, real)

    result = lookup_summary_cache_v2(tmp_path, v2_packet())

    assert result.miss_reason == MISS_UNSAFE_PATH_OR_ENTRY


def test_symlinked_namespace_is_rejected(tmp_path):
    real_root = tmp_path / "real"
    seed_entry(real_root)
    cache_root = tmp_path / "linked"
    cache_root.mkdir()
    symlink_or_skip(cache_root / CACHE_NAMESPACE_V2, real_root / CACHE_NAMESPACE_V2)

    result = lookup_summary_cache_v2(cache_root, v2_packet())

    assert result.miss_reason == MISS_UNSAFE_PATH_OR_ENTRY


# --- Bounded, non-sensitive public misses -----------------------------------


@pytest.mark.parametrize(
    "corrupt",
    [
        b"not json " + SECRET_MARKER.encode(),
        b'{"secret": "' + SECRET_MARKER.encode() + b'"}',
        b'{"a": NaN, "b": "' + SECRET_MARKER.encode() + b'"}',
    ],
)
def test_public_misses_never_leak_sensitive_detail(tmp_path, corrupt):
    packet = v2_packet(known_facts=[SECRET_MARKER])
    path, _entry = seed_entry(tmp_path, packet)
    path.write_bytes(corrupt)

    result = lookup_summary_cache_v2(tmp_path, packet)

    assert result.entry is None
    assert result.miss_reason in SUMMARY_CACHE_MISS_REASONS
    reason = result.miss_reason
    assert SECRET_MARKER not in reason
    assert str(tmp_path) not in reason
    assert ".tmp-" not in reason
    for forbidden in ("Expecting", "line 1", "column", "Traceback", "0x", "json", "<"):
        assert forbidden not in reason


def test_every_reachable_miss_reason_is_in_the_public_vocabulary(tmp_path):
    seen = set()
    packet = v2_packet()

    seen.add(lookup_summary_cache_v2(tmp_path, packet).miss_reason)
    path, _entry = seed_entry(tmp_path, packet)
    path.write_bytes(b"corrupt")
    seen.add(lookup_summary_cache_v2(tmp_path, packet).miss_reason)
    rewrite_entry_after_reset(tmp_path, packet, "cache_entry_version", "1.0")
    seen.add(lookup_summary_cache_v2(tmp_path, packet).miss_reason)
    rewrite_entry_after_reset(tmp_path, packet, "trust_status", "stale")
    seen.add(lookup_summary_cache_v2(tmp_path, packet).miss_reason)
    rewrite_entry_after_reset(tmp_path, packet, "summary", "detached")
    seen.add(lookup_summary_cache_v2(tmp_path, packet).miss_reason)

    assert seen <= set(SUMMARY_CACHE_MISS_REASONS)
    assert seen == {
        MISS_NOT_FOUND,
        MISS_MALFORMED_OR_OVERSIZED,
        MISS_UNSUPPORTED_VERSION,
        MISS_TRUST_NOT_CURRENT,
        MISS_IDENTITY_MISMATCH,
    }


def rewrite_entry_after_reset(cache_root, packet, field, value):
    path, _entry = seed_entry(cache_root, packet)
    rewrite_entry(path, lambda entry: entry.__setitem__(field, value))


# --- BaseException propagation ----------------------------------------------


@pytest.mark.parametrize("exception", [KeyboardInterrupt, SystemExit, GeneratorExit])
def test_base_exceptions_propagate_out_of_lookup(tmp_path, monkeypatch, exception):
    seed_entry(tmp_path)

    def interrupt(*args, **kwargs):
        raise exception()

    monkeypatch.setattr(builtins, "open", interrupt)

    with pytest.raises(exception):
        lookup_summary_cache_v2(tmp_path, v2_packet())
