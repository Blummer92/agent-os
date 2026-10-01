"""Mission-level reliability measurement for issue #2766 (read-only).

Derivation layer: pure functions over normalized mission records; see
README.md for metric definitions, derivation sources, and confidence rules.

Acquire read-only records via github_source.acquire_mission_records, then
project the minimal measurement set via derive.derive_mission_reliability.
"""
from __future__ import annotations

from .derive import SCHEMA_VERSION, derive_mission_reliability
from .github_source import acquire_mission_records

__all__ = (
    "SCHEMA_VERSION",
    "acquire_mission_records",
    "derive_mission_reliability",
)
