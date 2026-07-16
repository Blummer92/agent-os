"""Summary cache lookup helpers for Agent Memory handoff packets."""

from pathlib import Path
from typing import Any

from .cache_key import build_handoff_packet_cache_key
from .summary_cache import read_summary_cache_entry, summary_cache_entry_exists

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
