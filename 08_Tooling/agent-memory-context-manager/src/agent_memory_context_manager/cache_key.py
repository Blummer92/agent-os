"""Deterministic cache key helpers for Agent Memory handoff packets."""

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .packet_validation import assert_valid_handoff_packet

DEFAULT_CACHE_KEY_VERSION = "1.0"

_STABLE_CACHE_KEY_FIELDS = (
    "objective",
    "current_phase",
    "branch",
    "pr_number",
    "changed_files",
    "allowed_inspect_first",
    "known_facts",
    "prior_decisions",
    "validation_commands",
    "stop_conditions",
    "compute_limits",
)


def build_handoff_packet_cache_key(
    packet: Mapping[str, Any],
    *,
    version: str = DEFAULT_CACHE_KEY_VERSION,
) -> str:
    """Build a deterministic cache key for a validated handoff packet."""
    assert_valid_handoff_packet(packet)

    payload = {"version": version}
    for field in _STABLE_CACHE_KEY_FIELDS:
        payload[field] = packet[field]

    encoded_payload = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(encoded_payload.encode("utf-8")).hexdigest()

    return f"handoff-summary:{version}:{digest}"
