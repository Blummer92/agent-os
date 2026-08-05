"""Summary cache writer helpers for Agent Memory handoff packets.

The v1 writer below is retained unchanged. The v2 writer is canonical: it calls
the merged H2 ``summarize_handoff_packet`` itself and will not accept arbitrary
summary text or an externally assembled rendered-result object as reusable cache
content. Only a complete, supported, matching H2 result whose trust status is
exactly ``current`` may be published.
"""

import os
from pathlib import Path
from typing import Any

from .cache_key import (
    build_cache_key_v2_from_source_fingerprint,
    build_handoff_packet_cache_key,
)
from .packet_summary import TRUST_CURRENT, RenderingEvidence, summarize_handoff_packet
from .summary_cache import (
    MISS_LOCAL_IO_UNAVAILABLE,
    MISS_MALFORMED_OR_OVERSIZED,
    MISS_TRUST_NOT_CURRENT,
    MISS_UNSAFE_PATH_OR_ENTRY,
    SummaryCacheWriteError,
    _publish_cache_entry_v2,
    _reject_symlink,
    _serialize_cache_entry_v2,
    _StrictJsonError,
    build_summary_cache_entry,
    build_summary_cache_entry_v2,
    write_summary_cache_entry,
)
from .summary_cache_lookup import (
    build_summary_cache_namespace_v2,
    build_summary_cache_path,
    build_summary_cache_path_v2,
)


def write_summary_cache_for_packet(
    cache_dir: str | Path,
    packet: dict[str, Any],
    summary: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Write a summary cache entry for packet and return its path and entry."""
    cache_key = build_handoff_packet_cache_key(packet)
    entry = build_summary_cache_entry(
        cache_key=cache_key,
        summary=summary,
        source_packet=packet,
        metadata=metadata,
    )
    path = build_summary_cache_path(cache_dir, cache_key)

    write_summary_cache_entry(path, entry)

    return path, entry


# --- Cache contract v2 -------------------------------------------------------


def write_summary_cache_v2(
    cache_root: str | Path,
    packet: dict[str, Any],
    *,
    evidence: RenderingEvidence,
) -> tuple[Path, dict[str, Any]]:
    """Render packet through H2 and atomically publish a reusable v2 entry.

    The writer produces the H2 result itself from the packet and the caller's
    explicit rendering evidence. Arbitrary summary strings and caller-assembled
    result objects are not accepted.

    Raises ``SummaryCacheWriteError`` (a ``ValueError``) carrying one stable
    public reason when the result is not reusable or the entry cannot be
    published. The reason never contains caller data, decoder text, exception
    text, filesystem paths, or temporary filenames.

    ``KeyboardInterrupt``, ``SystemExit``, and ``GeneratorExit`` propagate.
    """
    if type(evidence) is not RenderingEvidence:
        raise SummaryCacheWriteError(MISS_TRUST_NOT_CURRENT)

    rendered = summarize_handoff_packet(packet, evidence=evidence)
    if rendered.trust_status != TRUST_CURRENT:
        raise SummaryCacheWriteError(MISS_TRUST_NOT_CURRENT)

    try:
        cache_key = build_cache_key_v2_from_source_fingerprint(
            rendered.source_fingerprint
        )
        final_path = build_summary_cache_path_v2(cache_root, cache_key)
        namespace = build_summary_cache_namespace_v2(cache_root)
    except (ValueError, TypeError) as error:
        raise SummaryCacheWriteError(MISS_UNSAFE_PATH_OR_ENTRY) from error

    entry = build_summary_cache_entry_v2(
        cache_key=cache_key,
        producer=rendered.producer,
        provenance_status=rendered.provenance_status,
        source_fingerprint=rendered.source_fingerprint,
        summary_fingerprint=rendered.summary_fingerprint,
        trust_status=rendered.trust_status,
        summary=rendered.text,
        source_packet=packet,
    )

    try:
        payload = _serialize_cache_entry_v2(entry)
    except _StrictJsonError as error:
        raise SummaryCacheWriteError(MISS_MALFORMED_OR_OVERSIZED) from error

    try:
        _reject_symlink(namespace)
        _reject_symlink(final_path)
    except _StrictJsonError as error:
        raise SummaryCacheWriteError(MISS_UNSAFE_PATH_OR_ENTRY) from error

    try:
        os.makedirs(os.fspath(namespace), exist_ok=True)
    except OSError as error:
        raise SummaryCacheWriteError(MISS_LOCAL_IO_UNAVAILABLE) from error

    try:
        _reject_symlink(namespace)
    except _StrictJsonError as error:
        raise SummaryCacheWriteError(MISS_UNSAFE_PATH_OR_ENTRY) from error

    try:
        _publish_cache_entry_v2(namespace, final_path, payload)
    except OSError as error:
        raise SummaryCacheWriteError(MISS_LOCAL_IO_UNAVAILABLE) from error

    return final_path, entry
