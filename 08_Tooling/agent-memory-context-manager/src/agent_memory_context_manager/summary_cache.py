"""Summary cache helpers for Agent Memory handoff summaries."""

import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

DEFAULT_SUMMARY_CACHE_VERSION = "1.0"


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
