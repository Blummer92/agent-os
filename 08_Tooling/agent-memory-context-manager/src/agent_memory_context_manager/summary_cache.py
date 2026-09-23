"""Summary cache helpers for Agent Memory handoff summaries.

The ``1.0`` entry helpers are the original v1 contract and are retained
unchanged. The ``2.0`` contract is the Memory H3 reusable-entry schema, its one
shared bounded validation path, its strict bounded JSON boundary, and its atomic
publication sequence.

Threat model: v2 detects accidental corruption, stale content, incompatible
versions, detached entries, malformed or oversized files, partial writes, and
unsafe fallback. It does **not** authenticate the cache writer. A process with
write access to the trusted cache root can fabricate an internally consistent
entry and recompute ordinary hashes. Fingerprints are deterministic integrity
and equality evidence only -- never signatures, approval, or authorization.
"""

import copy
import json
import os
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .cache_key import (
    CACHE_ENTRY_VERSION_V2,
    CACHE_KEY_VERSION_V2,
    CACHE_NAMESPACE_VERSION_V2,
    cache_key_v2_digest,
    is_sha256_hex,
)
from .packet_summary import (
    RENDERER_VERSION,
    SUPPORTED_PACKET_SCHEMA_VERSION,
    TRUST_CURRENT,
)

DEFAULT_SUMMARY_CACHE_VERSION = "1.0"

# --- Cache contract v2 -------------------------------------------------------

# Strict bounded limits for a v2 entry. Every limit sits above the ceiling a
# writable entry can reach (H2 caps packet string content at 50,000 UTF-8 bytes
# and displayed summary content well below these values), so a valid entry is
# never rejected while a hostile or corrupt file always is.
MAX_CACHE_ENTRY_BYTES = 524_288
MAX_CACHE_ENTRY_DEPTH = 8
MAX_CACHE_ENTRY_NODES = 20_000
MAX_CACHE_ENTRY_COLLECTION_ENTRIES = 1_000
MAX_CACHE_ENTRY_STRING_CHARS = 40_000
MAX_CACHE_ENTRY_TOTAL_STRING_BYTES = 400_000

# Finite, stable, non-sensitive public rejection vocabulary. These values never
# carry decoder text, exception text, filesystem paths, temporary filenames,
# object representations, caller strings, or partial entry content.
MISS_NOT_FOUND = "not_found"
MISS_MALFORMED_OR_OVERSIZED = "malformed_or_oversized"
MISS_UNSUPPORTED_VERSION = "unsupported_version"
MISS_IDENTITY_MISMATCH = "identity_mismatch"
MISS_TRUST_NOT_CURRENT = "trust_not_current"
MISS_UNSAFE_PATH_OR_ENTRY = "unsafe_path_or_entry"
MISS_LOCAL_IO_UNAVAILABLE = "local_io_unavailable"

SUMMARY_CACHE_MISS_REASONS: tuple[str, ...] = (
    MISS_NOT_FOUND,
    MISS_MALFORMED_OR_OVERSIZED,
    MISS_UNSUPPORTED_VERSION,
    MISS_IDENTITY_MISMATCH,
    MISS_TRUST_NOT_CURRENT,
    MISS_UNSAFE_PATH_OR_ENTRY,
    MISS_LOCAL_IO_UNAVAILABLE,
)

# Exact required field set. Missing or unexpected names are rejected.
CACHE_ENTRY_V2_FIELDS: tuple[str, ...] = (
    "cache_entry_version",
    "cache_key",
    "cache_key_version",
    "cache_namespace_version",
    "packet_schema_version",
    "producer",
    "provenance_status",
    "renderer_version",
    "source_fingerprint",
    "source_packet",
    "summary",
    "summary_fingerprint",
    "trust_status",
)

_CACHE_ENTRY_V2_FIELD_SET = frozenset(CACHE_ENTRY_V2_FIELDS)
_CACHE_ENTRY_V2_STRING_FIELDS = frozenset(
    field for field in CACHE_ENTRY_V2_FIELDS if field != "source_packet"
)

_MAX_IDENTITY_CHARS = 128


class SummaryCacheWriteError(ValueError):
    """Fail-closed v2 write rejection carrying one stable public reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _StrictJsonError(Exception):
    """Internal signal for a rejected v2 entry document."""


def build_summary_cache_entry(
    *,
    cache_key: str,
    summary: str,
    source_packet: Mapping[str, Any],
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a JSON-serializable summary cache entry."""
    if not isinstance(cache_key, str) or not cache_key.strip():
        raise ValueError("cache_key must be a non-empty string")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("summary must be a non-empty string")
    if not isinstance(source_packet, Mapping):
        raise ValueError("source_packet must be a dict-like mapping")

    return {
        "version": DEFAULT_SUMMARY_CACHE_VERSION,
        "cache_key": cache_key,
        "summary": summary,
        "source_packet": copy.deepcopy(dict(source_packet)),
        "metadata": copy.deepcopy(dict(metadata or {})),
    }


def write_summary_cache_entry(path: str | Path, entry: Mapping[str, Any]) -> None:
    """Write a summary cache entry as JSON, creating parents as needed."""
    cache_path = Path(path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(dict(entry), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_summary_cache_entry(path: str | Path) -> dict[str, Any]:
    """Read a summary cache entry from JSON storage."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def summary_cache_entry_exists(path: str | Path) -> bool:
    """Return whether a summary cache entry exists at path."""
    return Path(path).is_file()


# --- v2 entry construction and shared bounded validation ---------------------


def build_summary_cache_entry_v2(
    *,
    cache_key: str,
    producer: str,
    provenance_status: str,
    source_fingerprint: str,
    summary_fingerprint: str,
    trust_status: str,
    summary: str,
    source_packet: Mapping[str, Any],
) -> dict[str, Any]:
    """Build and validate a canonical v2 cache entry.

    Every caller (build, write, and lookup) validates through the same bounded
    path, so there is exactly one v2 entry validator.
    """
    entry = {
        "cache_entry_version": CACHE_ENTRY_VERSION_V2,
        "cache_key": cache_key,
        "cache_key_version": CACHE_KEY_VERSION_V2,
        "cache_namespace_version": CACHE_NAMESPACE_VERSION_V2,
        "packet_schema_version": SUPPORTED_PACKET_SCHEMA_VERSION,
        "producer": producer,
        "provenance_status": provenance_status,
        "renderer_version": RENDERER_VERSION,
        "source_fingerprint": source_fingerprint,
        "source_packet": copy.deepcopy(dict(source_packet)),
        "summary": summary,
        "summary_fingerprint": summary_fingerprint,
        "trust_status": trust_status,
    }
    reason = validate_summary_cache_entry_v2(entry)
    if reason is not None:
        raise SummaryCacheWriteError(reason)
    return entry


def validate_summary_cache_entry_v2(entry: Any) -> str | None:
    """Return a stable public rejection reason for entry, or None when valid.

    This checks structure, exact types, bounded content, and every self-contained
    version binding. Cross-checks against a caller's packet and against the H2
    renderer are performed by the lookup contract.
    """
    if type(entry) is not dict:
        return MISS_MALFORMED_OR_OVERSIZED
    if frozenset(entry) != _CACHE_ENTRY_V2_FIELD_SET:
        return MISS_MALFORMED_OR_OVERSIZED

    for field in _CACHE_ENTRY_V2_STRING_FIELDS:
        if type(entry[field]) is not str:
            return MISS_MALFORMED_OR_OVERSIZED
    if type(entry["source_packet"]) is not dict:
        return MISS_MALFORMED_OR_OVERSIZED

    try:
        _assert_bounded_structure(entry)
    except _StrictJsonError:
        return MISS_MALFORMED_OR_OVERSIZED

    if (
        entry["cache_entry_version"] != CACHE_ENTRY_VERSION_V2
        or entry["cache_key_version"] != CACHE_KEY_VERSION_V2
        or entry["cache_namespace_version"] != CACHE_NAMESPACE_VERSION_V2
        or entry["packet_schema_version"] != SUPPORTED_PACKET_SCHEMA_VERSION
        or entry["renderer_version"] != RENDERER_VERSION
    ):
        return MISS_UNSUPPORTED_VERSION

    if cache_key_v2_digest(entry["cache_key"]) is None:
        return MISS_UNSAFE_PATH_OR_ENTRY

    if not is_sha256_hex(entry["source_fingerprint"]) or not is_sha256_hex(
        entry["summary_fingerprint"]
    ):
        return MISS_MALFORMED_OR_OVERSIZED

    if _normalized_identity(entry["producer"]) is None:
        return MISS_MALFORMED_OR_OVERSIZED
    if _normalized_identity(entry["provenance_status"]) is None:
        return MISS_MALFORMED_OR_OVERSIZED
    if not entry["summary"]:
        return MISS_MALFORMED_OR_OVERSIZED

    if entry["trust_status"] != TRUST_CURRENT:
        return MISS_TRUST_NOT_CURRENT

    return None


def _normalized_identity(value: str) -> str | None:
    if not value or len(value) > _MAX_IDENTITY_CHARS or value != value.strip():
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    return value


def _assert_bounded_structure(value: Any) -> None:
    """Enforce exact built-in types plus depth, node, collection, and string limits."""
    budget = {"nodes": 0, "string_bytes": 0}
    _walk_bounded(value, depth=1, budget=budget)


def _walk_bounded(value: Any, *, depth: int, budget: dict[str, int]) -> None:
    if depth > MAX_CACHE_ENTRY_DEPTH:
        raise _StrictJsonError
    budget["nodes"] += 1
    if budget["nodes"] > MAX_CACHE_ENTRY_NODES:
        raise _StrictJsonError

    if value is None or type(value) is bool:
        return
    if type(value) is int:
        return
    if type(value) is str:
        if len(value) > MAX_CACHE_ENTRY_STRING_CHARS:
            raise _StrictJsonError
        try:
            encoded_length = len(value.encode("utf-8"))
        except UnicodeEncodeError as error:
            raise _StrictJsonError from error
        budget["string_bytes"] += encoded_length
        if budget["string_bytes"] > MAX_CACHE_ENTRY_TOTAL_STRING_BYTES:
            raise _StrictJsonError
        return
    if type(value) is list:
        if len(value) > MAX_CACHE_ENTRY_COLLECTION_ENTRIES:
            raise _StrictJsonError
        for item in value:
            _walk_bounded(item, depth=depth + 1, budget=budget)
        return
    if type(value) is dict:
        if len(value) > MAX_CACHE_ENTRY_COLLECTION_ENTRIES:
            raise _StrictJsonError
        for key, item in value.items():
            if type(key) is not str:
                raise _StrictJsonError
            _walk_bounded(key, depth=depth + 1, budget=budget)
            _walk_bounded(item, depth=depth + 1, budget=budget)
        return

    raise _StrictJsonError


# --- Strict bounded JSON boundary -------------------------------------------


def _serialize_cache_entry_v2(entry: Mapping[str, Any]) -> bytes:
    """Serialize a validated entry to deterministic bounded strict JSON bytes.

    Mapping key order is preserved rather than sorted. The canonical H2 renderer
    displays ``compute_limits`` in insertion order, so re-sorting the stored
    packet would change the rendered text and summary fingerprint on re-render
    and make every entry unverifiable. Order is therefore part of the stored
    evidence: the entry's own field order is fixed by construction, and the
    source packet's order is round-tripped exactly. Packet content equality
    remains order independent because the H2 source fingerprint canonicalizes
    mappings.
    """
    try:
        text = json.dumps(
            dict(entry),
            sort_keys=False,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        payload = (text + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise _StrictJsonError from error
    if len(payload) > MAX_CACHE_ENTRY_BYTES:
        raise _StrictJsonError
    return payload


def _reject_duplicate_names(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    for key, _value in pairs:
        if key in seen:
            raise _StrictJsonError
        seen.add(key)
    return dict(pairs)


def _reject_constant(_name: str) -> Any:
    # Rejects NaN, Infinity, and -Infinity before they become float values.
    raise _StrictJsonError


def _reject_float(_text: str) -> Any:
    raise _StrictJsonError


def _assert_bounded_text_depth(text: str) -> None:
    """Reject excessive nesting before handing the document to the JSON parser."""
    depth = 0
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            if depth > MAX_CACHE_ENTRY_DEPTH:
                raise _StrictJsonError
        elif char in "]}":
            depth -= 1


def _parse_cache_entry_v2_bytes(payload: bytes) -> dict[str, Any]:
    """Parse bounded entry bytes under the strict v2 JSON contract."""
    if len(payload) > MAX_CACHE_ENTRY_BYTES:
        raise _StrictJsonError
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise _StrictJsonError from error

    _assert_bounded_text_depth(text)

    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_names,
            parse_constant=_reject_constant,
            parse_float=_reject_float,
        )
    except _StrictJsonError:
        raise
    except (ValueError, RecursionError) as error:
        raise _StrictJsonError from error

    if type(parsed) is not dict:
        raise _StrictJsonError
    _assert_bounded_structure(parsed)
    return parsed


# --- Atomic publication ------------------------------------------------------


def _publish_cache_entry_v2(namespace_dir: Path, final_path: Path, payload: bytes) -> None:
    """Write payload to a temporary file in namespace_dir and atomically publish it.

    A failure at any stage before ``os.replace`` leaves any previously published
    entry at ``final_path`` untouched. The final path is never opened for
    writing directly.
    """
    handle = None
    temp_name = None
    try:
        descriptor, temp_name = tempfile.mkstemp(
            dir=os.fspath(namespace_dir), prefix=".tmp-", suffix=".json"
        )
        handle = os.fdopen(descriptor, "wb")
        handle.write(payload)
        handle.flush()
        handle.close()
        handle = None
        os.replace(temp_name, os.fspath(final_path))
        temp_name = None
    finally:
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass
        if temp_name is not None:
            try:
                os.unlink(temp_name)
            except OSError:
                pass


def _reject_symlink(path: Path) -> None:
    """Reject a symlink at path where the portable check supports it."""
    try:
        mode = os.lstat(os.fspath(path)).st_mode
    except FileNotFoundError:
        return
    except OSError as error:
        raise _StrictJsonError from error
    if stat.S_ISLNK(mode):
        raise _StrictJsonError
