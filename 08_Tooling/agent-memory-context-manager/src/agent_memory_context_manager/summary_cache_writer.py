"""Summary cache writer helpers for Agent Memory handoff packets."""

from pathlib import Path
from typing import Any

from .cache_key import build_handoff_packet_cache_key
from .summary_cache import build_summary_cache_entry, write_summary_cache_entry
from .summary_cache_lookup import build_summary_cache_path


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
