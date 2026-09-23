"""Summary cache lookup helpers for Agent Memory handoff packets.

The v1 lookup below is retained unchanged. The v2 lookup is a strict fail-closed
cutover: it derives one exact path inside the fixed v2 namespace, performs one
bounded open/read, verifies every version, identity, and rendering binding
through the canonical H2 public contract, and returns one finite non-sensitive
miss reason otherwise. There is no v1, unversioned, or root-namespace fallback,
and no directory scan or alternative-filename search.
"""

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .cache_key import (
    CACHE_NAMESPACE_V2,
    build_handoff_packet_cache_key,
    build_handoff_packet_cache_key_v2,
    cache_key_v2_digest,
)
from .packet_summary import (
    TRUST_CURRENT,
    RenderingEvidence,
    summarize_handoff_packet,
)
from .summary_cache import (
    MAX_CACHE_ENTRY_BYTES,
    MISS_IDENTITY_MISMATCH,
    MISS_LOCAL_IO_UNAVAILABLE,
    MISS_MALFORMED_OR_OVERSIZED,
    MISS_NOT_FOUND,
    MISS_TRUST_NOT_CURRENT,
    MISS_UNSAFE_PATH_OR_ENTRY,
    _parse_cache_entry_v2_bytes,
    _reject_symlink,
    _StrictJsonError,
    read_summary_cache_entry,
    summary_cache_entry_exists,
    validate_summary_cache_entry_v2,
)

DEFAULT_SUMMARY_CACHE_FILENAME = "summary-cache.json"
INVALID_FILENAME_CHARS = set('<>:"/\\|?*')


def build_summary_cache_path(cache_dir: str | Path, cache_key: str) -> Path:
    """Build a portable filesystem path for a summary cache key."""
    safe_cache_key = "".join(
        "_" if char in INVALID_FILENAME_CHARS else char
        for char in cache_key
    )
    return Path(cache_dir) / f"{safe_cache_key}.json"


def lookup_summary_cache_entry(cache_dir: str | Path, packet: dict[str, Any]) -> dict[str, Any] | None:
    """Return a matching summary cache entry for packet, or None."""
    cache_key = build_handoff_packet_cache_key(packet)
    cache_path = build_summary_cache_path(cache_dir, cache_key)

    if not summary_cache_entry_exists(cache_path):
        return None

    entry = read_summary_cache_entry(cache_path)
    if entry.get("cache_key") != cache_key:
        return None

    return entry


# --- Cache contract v2 -------------------------------------------------------


@dataclass(frozen=True)
class SummaryCacheLookupResultV2:
    """Result of a v2 lookup. Exactly one of entry/miss_reason is set."""

    entry: dict[str, Any] | None
    miss_reason: str | None

    @property
    def hit(self) -> bool:
        return self.entry is not None


def build_summary_cache_namespace_v2(cache_root: str | Path) -> Path:
    """Return the fixed v2 namespace directory beneath the caller's cache root."""
    root = Path(cache_root)
    if not os.fspath(root):
        raise ValueError("cache_root must not be empty")
    return root / CACHE_NAMESPACE_V2


def build_summary_cache_path_v2(cache_root: str | Path, cache_key: str) -> Path:
    """Return the exact v2 entry path for a validated v2 cache key.

    The filename is derived only from the validated fixed-format digest, never
    from arbitrary caller text. The lexical result is confirmed to remain
    directly inside the v2 namespace.
    """
    digest = cache_key_v2_digest(cache_key)
    if digest is None:
        raise ValueError("cache_key is not a valid v2 cache key")

    namespace = build_summary_cache_namespace_v2(cache_root)
    filename = f"{digest}.json"
    final_path = namespace / filename

    normalized_namespace = os.path.normpath(os.fspath(namespace))
    expected = os.path.join(normalized_namespace, filename)
    if os.path.normpath(os.fspath(final_path)) != expected:
        raise ValueError("v2 cache path escapes the v2 namespace")
    if final_path.name != filename or final_path.parent.name != CACHE_NAMESPACE_V2:
        raise ValueError("v2 cache path escapes the v2 namespace")

    return final_path


def _read_entry_bytes_v2(final_path: Path, namespace: Path) -> tuple[bytes | None, str | None]:
    """Perform exactly one bounded open/read of the expected v2 path.

    There is no ``exists()`` check before the read, so no check-then-read race
    exists. Symlink and file-type rejection happens on the descriptor and path
    that were actually opened.
    """
    try:
        handle = open(os.fspath(final_path), "rb")
    except FileNotFoundError:
        return None, MISS_NOT_FOUND
    except NotADirectoryError:
        return None, MISS_NOT_FOUND
    except IsADirectoryError:
        return None, MISS_UNSAFE_PATH_OR_ENTRY
    except PermissionError:
        return None, MISS_LOCAL_IO_UNAVAILABLE
    except OSError:
        return None, MISS_LOCAL_IO_UNAVAILABLE
    except ValueError:
        return None, MISS_UNSAFE_PATH_OR_ENTRY

    try:
        with handle:
            try:
                if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                    return None, MISS_UNSAFE_PATH_OR_ENTRY
                payload = handle.read(MAX_CACHE_ENTRY_BYTES + 1)
            except OSError:
                return None, MISS_LOCAL_IO_UNAVAILABLE
    except OSError:
        return None, MISS_LOCAL_IO_UNAVAILABLE

    if len(payload) > MAX_CACHE_ENTRY_BYTES:
        return None, MISS_MALFORMED_OR_OVERSIZED

    try:
        _reject_symlink(namespace)
        _reject_symlink(final_path)
    except _StrictJsonError:
        return None, MISS_UNSAFE_PATH_OR_ENTRY

    return payload, None


def lookup_summary_cache_v2(
    cache_root: str | Path, packet: dict[str, Any]
) -> SummaryCacheLookupResultV2:
    """Return a fully verified reusable v2 entry for packet, or a bounded miss.

    Verification is complete and fail closed. Every version, key, packet,
    renderer, source, summary, provenance, trust, and rendered-text binding is
    checked, and the stored summary is independently reproduced through the
    canonical H2 public renderer. Any inconsistency is a miss, never a partially
    trusted hit.

    ``KeyboardInterrupt``, ``SystemExit``, and ``GeneratorExit`` propagate.
    """
    try:
        expected_key = build_handoff_packet_cache_key_v2(packet)
        final_path = build_summary_cache_path_v2(cache_root, expected_key)
    except ValueError:
        return SummaryCacheLookupResultV2(entry=None, miss_reason=MISS_UNSAFE_PATH_OR_ENTRY)
    except (TypeError, OSError):
        return SummaryCacheLookupResultV2(entry=None, miss_reason=MISS_UNSAFE_PATH_OR_ENTRY)

    namespace = final_path.parent
    payload, miss_reason = _read_entry_bytes_v2(final_path, namespace)
    if payload is None:
        return SummaryCacheLookupResultV2(entry=None, miss_reason=miss_reason)

    try:
        entry = _parse_cache_entry_v2_bytes(payload)
    except _StrictJsonError:
        return SummaryCacheLookupResultV2(
            entry=None, miss_reason=MISS_MALFORMED_OR_OVERSIZED
        )

    reason = validate_summary_cache_entry_v2(entry)
    if reason is not None:
        return SummaryCacheLookupResultV2(entry=None, miss_reason=reason)

    if entry["cache_key"] != expected_key:
        return SummaryCacheLookupResultV2(
            entry=None, miss_reason=MISS_IDENTITY_MISMATCH
        )

    reason = _verify_entry_against_renderer_v2(entry)
    if reason is not None:
        return SummaryCacheLookupResultV2(entry=None, miss_reason=reason)

    return SummaryCacheLookupResultV2(entry=entry, miss_reason=None)


def _verify_entry_against_renderer_v2(entry: dict[str, Any]) -> str | None:
    """Re-render the stored packet through H2 and verify every stored binding.

    Only canonical existing H2 public behavior is used; H3 does not reimplement
    packet canonicalization, schema validation, or trust classification.
    """
    evidence = RenderingEvidence(
        producer=entry["producer"],
        packet_schema_version=entry["packet_schema_version"],
        renderer_version=entry["renderer_version"],
        provenance_status=entry["provenance_status"],
        source_fingerprint=entry["source_fingerprint"],
    )
    try:
        rendered = summarize_handoff_packet(entry["source_packet"], evidence=evidence)
    except ValueError:
        return MISS_MALFORMED_OR_OVERSIZED
    except (TypeError, RecursionError, OverflowError):
        return MISS_MALFORMED_OR_OVERSIZED

    if rendered.trust_status != TRUST_CURRENT:
        return MISS_TRUST_NOT_CURRENT
    if rendered.source_fingerprint != entry["source_fingerprint"]:
        return MISS_IDENTITY_MISMATCH
    if rendered.summary_fingerprint != entry["summary_fingerprint"]:
        return MISS_IDENTITY_MISMATCH
    if rendered.provenance_status != entry["provenance_status"]:
        return MISS_IDENTITY_MISMATCH
    if rendered.producer != entry["producer"]:
        return MISS_IDENTITY_MISMATCH
    if rendered.text != entry["summary"]:
        return MISS_IDENTITY_MISMATCH

    return None
