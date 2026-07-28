import copy
import inspect
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import agent_memory_context_manager as package  # noqa: E402
from agent_memory_context_manager import (  # noqa: E402
    CACHE_NAMESPACE_V2,
    MISS_LOCAL_IO_UNAVAILABLE,
    MISS_MALFORMED_OR_OVERSIZED,
    MISS_TRUST_NOT_CURRENT,
    MISS_UNSAFE_PATH_OR_ENTRY,
    RENDERER_VERSION,
    SUMMARY_CACHE_MISS_REASONS,
    SUPPORTED_PACKET_SCHEMA_VERSION,
    RenderingEvidence,
    SummaryCacheWriteError,
    build_handoff_packet,
    build_handoff_packet_cache_key,
    build_handoff_packet_cache_key_v2,
    build_summary_cache_path_v2,
    handoff_packet_source_fingerprint,
    lookup_summary_cache_entry,
    lookup_summary_cache_v2,
    read_summary_cache_entry,
    summarize_handoff_packet,
    write_summary_cache_for_packet,
    write_summary_cache_v2,
)
from agent_memory_context_manager import summary_cache as summary_cache_module  # noqa: E402
from agent_memory_context_manager import (  # noqa: E402
    summary_cache_writer as writer_module,
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


# --- Cache contract v2 -------------------------------------------------------


def v2_packet(**overrides):
    fields = {
        "objective": "Implement cache contract v2",
        "current_phase": "Memory H3",
        "branch": None,
        "pr_number": None,
        "changed_files": ["summary_cache_writer.py"],
        "allowed_inspect_first": ["cache_key.py"],
        "forbidden_unless_needed": ["Workflow Scheduler source"],
        "known_facts": ["Memory H2 is merged"],
        "prior_decisions": ["Reuse H2 canonical identities"],
        "acceptance_criteria": ["Writes are atomic"],
        "validation_commands": ["PYTHONPATH=src python -m pytest tests -q"],
        "stop_conditions": ["Needs a scope decision"],
    }
    fields.update(overrides)
    return build_handoff_packet(**fields)


def current_evidence(packet=None, producer="memory-h3-test", **overrides):
    packet = packet if packet is not None else v2_packet()
    fields = {
        "producer": producer,
        "packet_schema_version": SUPPORTED_PACKET_SCHEMA_VERSION,
        "renderer_version": RENDERER_VERSION,
        "provenance_status": "supplied",
        "source_fingerprint": handoff_packet_source_fingerprint(packet),
    }
    fields.update(overrides)
    return RenderingEvidence(**fields)


def namespace_files(cache_root):
    namespace = Path(cache_root) / CACHE_NAMESPACE_V2
    if not namespace.is_dir():
        return []
    return sorted(p.name for p in namespace.iterdir())


# --- Canonical writer admission ---------------------------------------------


def test_writer_renders_the_summary_itself_and_takes_no_summary_argument():
    parameters = inspect.signature(write_summary_cache_v2).parameters

    assert "summary" not in parameters
    assert "rendered" not in parameters
    assert "metadata" not in parameters
    assert set(parameters) == {"cache_root", "packet", "evidence"}


def test_writer_produces_the_canonical_h2_result(tmp_path):
    packet = v2_packet()
    evidence = current_evidence(packet)
    expected = summarize_handoff_packet(packet, evidence=evidence)

    _path, entry = write_summary_cache_v2(tmp_path, packet, evidence=evidence)

    assert entry["summary"] == expected.text
    assert entry["summary_fingerprint"] == expected.summary_fingerprint
    assert entry["source_fingerprint"] == expected.source_fingerprint
    assert entry["trust_status"] == "current"


@pytest.mark.parametrize(
    "bogus_evidence",
    [
        "an arbitrary summary string",
        b"arbitrary bytes",
        {"producer": "memory-h3-test"},
        None,
        42,
    ],
)
def test_arbitrary_values_cannot_be_written_as_reusable_content(tmp_path, bogus_evidence):
    with pytest.raises(SummaryCacheWriteError) as excinfo:
        write_summary_cache_v2(tmp_path, v2_packet(), evidence=bogus_evidence)

    assert excinfo.value.reason == MISS_TRUST_NOT_CURRENT
    assert namespace_files(tmp_path) == []


def test_an_externally_assembled_rendered_result_cannot_be_written(tmp_path):
    packet = v2_packet()
    fabricated = summarize_handoff_packet(packet, evidence=current_evidence(packet))
    assert fabricated.trust_status == "current"

    with pytest.raises(SummaryCacheWriteError) as excinfo:
        write_summary_cache_v2(tmp_path, packet, evidence=fabricated)

    assert excinfo.value.reason == MISS_TRUST_NOT_CURRENT
    assert namespace_files(tmp_path) == []


@pytest.mark.parametrize(
    "override",
    [
        {"source_fingerprint": "a" * 64},
        {"source_fingerprint": None},
        {"source_fingerprint": "not-a-digest"},
        {"packet_schema_version": "handoff-packet-v1"},
        {"renderer_version": "packet-summary-h1"},
        {"provenance_status": "missing"},
        {"provenance_status": "malformed"},
        {"provenance_status": "contradictory"},
        {"provenance_status": "detached"},
        {"producer": ""},
    ],
)
def test_only_current_trust_may_be_written(tmp_path, override):
    packet = v2_packet()
    evidence = current_evidence(packet, **override)
    assert summarize_handoff_packet(packet, evidence=evidence).trust_status != "current"

    with pytest.raises(SummaryCacheWriteError) as excinfo:
        write_summary_cache_v2(tmp_path, packet, evidence=evidence)

    assert excinfo.value.reason == MISS_TRUST_NOT_CURRENT
    assert namespace_files(tmp_path) == []


def test_stale_evidence_for_another_packet_cannot_be_written(tmp_path):
    packet = v2_packet()
    stale = current_evidence(v2_packet(objective="a previous objective"))

    with pytest.raises(SummaryCacheWriteError):
        write_summary_cache_v2(tmp_path, packet, evidence=stale)

    assert namespace_files(tmp_path) == []


def test_invalid_packet_raises_through_the_canonical_validator(tmp_path):
    packet = v2_packet()
    evidence = current_evidence(packet)
    del packet["objective"]

    with pytest.raises(ValueError, match="Invalid handoff packet"):
        write_summary_cache_v2(tmp_path, packet, evidence=evidence)


def test_write_rejection_reasons_are_in_the_public_vocabulary(tmp_path):
    with pytest.raises(SummaryCacheWriteError) as excinfo:
        write_summary_cache_v2(tmp_path, v2_packet(), evidence=None)

    assert excinfo.value.reason in SUMMARY_CACHE_MISS_REASONS
    assert str(tmp_path) not in str(excinfo.value)


def test_writer_does_not_mutate_the_packet(tmp_path):
    packet = v2_packet()
    original = copy.deepcopy(packet)

    _path, entry = write_summary_cache_v2(tmp_path, packet, evidence=current_evidence(packet))
    entry["source_packet"]["known_facts"].append("mutated")

    assert packet == original


# --- Determinism -------------------------------------------------------------


def test_identical_inputs_produce_identical_path_entry_and_bytes(tmp_path):
    packet = v2_packet()
    evidence = current_evidence(packet)

    first_root = tmp_path / "a"
    second_root = tmp_path / "b"
    first_path, first_entry = write_summary_cache_v2(first_root, packet, evidence=evidence)
    second_path, second_entry = write_summary_cache_v2(second_root, packet, evidence=evidence)

    assert first_path.name == second_path.name
    assert first_entry == second_entry
    assert first_path.read_bytes() == second_path.read_bytes()


def test_repeated_identical_writes_leave_one_byte_identical_entry(tmp_path):
    packet = v2_packet()
    evidence = current_evidence(packet)

    path, _entry = write_summary_cache_v2(tmp_path, packet, evidence=evidence)
    first_bytes = path.read_bytes()
    for _ in range(3):
        write_summary_cache_v2(tmp_path, packet, evidence=evidence)

    assert namespace_files(tmp_path) == [path.name]
    assert path.read_bytes() == first_bytes
    assert lookup_summary_cache_v2(tmp_path, packet).hit is True


def test_a_concurrent_identical_publication_leaves_one_valid_entry(tmp_path, monkeypatch):
    """Deterministically interleave a second complete write before os.replace."""
    packet = v2_packet()
    evidence = current_evidence(packet)
    real_replace = os.replace
    reentered = {"done": False}

    def interleaving_replace(src, dst):
        if not reentered["done"]:
            reentered["done"] = True
            write_summary_cache_v2(tmp_path, packet, evidence=evidence)
        return real_replace(src, dst)

    monkeypatch.setattr(summary_cache_module.os, "replace", interleaving_replace)
    path, _entry = write_summary_cache_v2(tmp_path, packet, evidence=evidence)
    monkeypatch.undo()

    assert reentered["done"] is True
    assert namespace_files(tmp_path) == [path.name]
    assert lookup_summary_cache_v2(tmp_path, packet).hit is True


# --- Atomic publication ------------------------------------------------------


def test_publication_uses_a_temporary_file_and_never_the_final_path(tmp_path, monkeypatch):
    packet = v2_packet()
    opened = []
    real_fdopen = os.fdopen

    def recording_fdopen(descriptor, *args, **kwargs):
        opened.append(descriptor)
        return real_fdopen(descriptor, *args, **kwargs)

    created = []
    real_mkstemp = summary_cache_module.tempfile.mkstemp

    def recording_mkstemp(*args, **kwargs):
        descriptor, name = real_mkstemp(*args, **kwargs)
        created.append(name)
        return descriptor, name

    monkeypatch.setattr(summary_cache_module.os, "fdopen", recording_fdopen)
    monkeypatch.setattr(summary_cache_module.tempfile, "mkstemp", recording_mkstemp)
    path, _entry = write_summary_cache_v2(tmp_path, packet, evidence=current_evidence(packet))
    monkeypatch.undo()

    assert len(created) == 1
    assert created[0] != os.fspath(path)
    assert Path(created[0]).parent == path.parent
    assert Path(created[0]).name.startswith(".tmp-")
    assert not Path(created[0]).exists()
    assert namespace_files(tmp_path) == [path.name]


def test_failure_at_replace_leaves_no_entry_and_no_temporary_file(tmp_path, monkeypatch):
    def failing_replace(src, dst):
        raise OSError("replace failed for /some/internal/path")

    monkeypatch.setattr(summary_cache_module.os, "replace", failing_replace)

    with pytest.raises(SummaryCacheWriteError) as excinfo:
        write_summary_cache_v2(tmp_path, v2_packet(), evidence=current_evidence())
    monkeypatch.undo()

    assert excinfo.value.reason == MISS_LOCAL_IO_UNAVAILABLE
    assert namespace_files(tmp_path) == []


@pytest.mark.parametrize("stage", ["serialize", "mkstemp", "write", "flush", "replace"])
def test_failure_before_publication_preserves_an_existing_valid_entry(
    tmp_path, monkeypatch, stage
):
    packet = v2_packet()
    path, _entry = write_summary_cache_v2(
        tmp_path, packet, evidence=current_evidence(packet, producer="original-producer")
    )
    preserved = path.read_bytes()

    # A different producer yields different bytes at the same cache key.
    replacement_evidence = current_evidence(packet, producer="replacement-producer")

    if stage == "serialize":
        def boom(entry):
            raise summary_cache_module._StrictJsonError

        monkeypatch.setattr(writer_module, "_serialize_cache_entry_v2", boom)
        expected_reason = MISS_MALFORMED_OR_OVERSIZED
    elif stage == "mkstemp":
        def boom(*args, **kwargs):
            raise OSError("mkstemp failed")

        monkeypatch.setattr(summary_cache_module.tempfile, "mkstemp", boom)
        expected_reason = MISS_LOCAL_IO_UNAVAILABLE
    elif stage == "replace":
        def boom(src, dst):
            raise OSError("replace failed")

        monkeypatch.setattr(summary_cache_module.os, "replace", boom)
        expected_reason = MISS_LOCAL_IO_UNAVAILABLE
    else:
        real_fdopen = os.fdopen

        class FailingHandle:
            def __init__(self, wrapped):
                self._wrapped = wrapped

            def write(self, payload):
                if stage == "write":
                    raise OSError("write failed")
                return self._wrapped.write(payload)

            def flush(self):
                raise OSError("flush failed")

            def close(self):
                return self._wrapped.close()

        def failing_fdopen(descriptor, *args, **kwargs):
            return FailingHandle(real_fdopen(descriptor, *args, **kwargs))

        monkeypatch.setattr(summary_cache_module.os, "fdopen", failing_fdopen)
        expected_reason = MISS_LOCAL_IO_UNAVAILABLE

    with pytest.raises(SummaryCacheWriteError) as excinfo:
        write_summary_cache_v2(tmp_path, packet, evidence=replacement_evidence)
    monkeypatch.undo()

    assert excinfo.value.reason == expected_reason
    assert path.read_bytes() == preserved
    assert namespace_files(tmp_path) == [path.name]
    assert lookup_summary_cache_v2(tmp_path, packet).hit is True


def test_a_successful_rewrite_replaces_the_entry_atomically(tmp_path):
    packet = v2_packet()
    path, first = write_summary_cache_v2(
        tmp_path, packet, evidence=current_evidence(packet, producer="producer-one")
    )
    first_bytes = path.read_bytes()

    second_path, second = write_summary_cache_v2(
        tmp_path, packet, evidence=current_evidence(packet, producer="producer-two")
    )

    assert second_path == path
    assert path.read_bytes() != first_bytes
    assert first != second
    assert namespace_files(tmp_path) == [path.name]
    assert lookup_summary_cache_v2(tmp_path, packet).entry == second


# --- Symlink and path boundary ----------------------------------------------


def symlink_or_skip(link, target):
    try:
        os.symlink(os.fspath(target), os.fspath(link))
    except (OSError, NotImplementedError, AttributeError):
        pytest.skip("this platform does not support creating symlinks in this test")


def test_write_rejects_a_symlinked_namespace(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    cache_root = tmp_path / "root"
    cache_root.mkdir()
    symlink_or_skip(cache_root / CACHE_NAMESPACE_V2, real)

    with pytest.raises(SummaryCacheWriteError) as excinfo:
        write_summary_cache_v2(cache_root, v2_packet(), evidence=current_evidence())

    assert excinfo.value.reason == MISS_UNSAFE_PATH_OR_ENTRY
    assert list(real.iterdir()) == []


def test_write_rejects_a_symlinked_destination(tmp_path):
    packet = v2_packet()
    target = build_summary_cache_path_v2(tmp_path, build_handoff_packet_cache_key_v2(packet))
    target.parent.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_text("untouched", encoding="utf-8")
    symlink_or_skip(target, outside)

    with pytest.raises(SummaryCacheWriteError) as excinfo:
        write_summary_cache_v2(tmp_path, packet, evidence=current_evidence(packet))

    assert excinfo.value.reason == MISS_UNSAFE_PATH_OR_ENTRY
    assert outside.read_text(encoding="utf-8") == "untouched"


# --- v1 isolation ------------------------------------------------------------


def test_v2_write_leaves_v1_files_untouched(tmp_path):
    packet = v2_packet()
    v1_path, v1_entry = write_summary_cache_for_packet(tmp_path, packet, "legacy summary")
    before = v1_path.read_bytes()

    write_summary_cache_v2(tmp_path, packet, evidence=current_evidence(packet))

    assert v1_path.is_file()
    assert v1_path.read_bytes() == before
    assert read_summary_cache_entry(v1_path) == v1_entry
    assert lookup_summary_cache_entry(tmp_path, packet) == v1_entry


def test_v2_and_v1_entries_occupy_separate_namespaces(tmp_path):
    packet = v2_packet()
    v1_path, _v1 = write_summary_cache_for_packet(tmp_path, packet, "legacy summary")
    v2_path, _v2 = write_summary_cache_v2(tmp_path, packet, evidence=current_evidence(packet))

    assert v1_path.parent == tmp_path
    assert v2_path.parent == tmp_path / CACHE_NAMESPACE_V2
    assert v1_path != v2_path


# --- Exports, version, and boundary consistency -----------------------------


def test_public_exports_are_sorted_unique_and_importable():
    assert package.__all__ == sorted(package.__all__)
    assert len(package.__all__) == len(set(package.__all__))
    for name in package.__all__:
        assert hasattr(package, name), name


def test_v2_public_surface_is_exported():
    expected = {
        "CACHE_ENTRY_V2_FIELDS",
        "CACHE_ENTRY_VERSION_V2",
        "CACHE_KEY_VERSION_V2",
        "CACHE_NAMESPACE_V2",
        "CACHE_NAMESPACE_VERSION_V2",
        "MAX_CACHE_ENTRY_BYTES",
        "SUMMARY_CACHE_MISS_REASONS",
        "SummaryCacheLookupResultV2",
        "SummaryCacheWriteError",
        "build_handoff_packet_cache_key_v2",
        "build_summary_cache_entry_v2",
        "build_summary_cache_path_v2",
        "handoff_packet_source_fingerprint",
        "lookup_summary_cache_v2",
        "validate_summary_cache_entry_v2",
        "write_summary_cache_v2",
    }

    assert expected <= set(package.__all__)


def test_v1_public_surface_is_unchanged():
    v1_surface = {
        "DEFAULT_CACHE_KEY_VERSION",
        "DEFAULT_SUMMARY_CACHE_FILENAME",
        "DEFAULT_SUMMARY_CACHE_VERSION",
        "build_handoff_packet_cache_key",
        "build_summary_cache_entry",
        "build_summary_cache_path",
        "lookup_summary_cache_entry",
        "read_summary_cache_entry",
        "summary_cache_entry_exists",
        "write_summary_cache_entry",
        "write_summary_cache_for_packet",
    }

    assert v1_surface <= set(package.__all__)


def test_internal_helpers_are_not_exported():
    for name in package.__all__:
        assert not name.startswith("_")
    for private in ("_parse_cache_entry_v2_bytes", "_serialize_cache_entry_v2"):
        assert private not in package.__all__


def test_package_version_matches_the_documented_cutover_version():
    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)

    assert match is not None
    assert match.group(1) == "0.2.0"


def test_no_dependency_was_added():
    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
        encoding="utf-8"
    )

    assert "dependencies = []" in text


def test_v2_modules_introduce_no_external_or_scheduler_behavior():
    sources = [
        (Path(__file__).resolve().parents[1] / "src" / "agent_memory_context_manager" / name).read_text(
            encoding="utf-8"
        )
        for name in (
            "cache_key.py",
            "summary_cache.py",
            "summary_cache_lookup.py",
            "summary_cache_writer.py",
        )
    ]
    forbidden = (
        "import requests",
        "import urllib",
        "import socket",
        "import subprocess",
        "import threading",
        "import time",
        "import datetime",
        "import random",
        "http",
        "github",
        "Scheduler",
        "getenv",
        "environ",
        "shutil.rmtree",
    )

    for source in sources:
        for token in forbidden:
            assert token not in source, token
