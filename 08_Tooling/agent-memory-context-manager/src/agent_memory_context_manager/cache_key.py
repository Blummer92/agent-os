"""Deterministic cache key helpers for Agent Memory handoff packets.

Two contracts live here. The ``1.0`` contract is the original v1 cache key and
is retained unchanged. The ``2.0`` contract is the Memory H3 cache identity: it
consumes the merged H2 canonical source fingerprint from ``packet_summary`` and
binds it to the cache-key, cache-entry, namespace, packet-schema, and renderer
identities so an entry can never be reused across contract versions.

H3 does not maintain its own packet-field list, packet canonicalization, packet
validation, trust classification, or reason vocabulary. Every packet-derived
identity value comes from the H2 public contract.
"""

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .packet_summary import (
    REASON_PACKET_CONTENT_UNSAFE,
    REASON_PACKET_RESOURCE_LIMIT_EXCEEDED,
    RENDERER_VERSION,
    SOURCE_FINGERPRINT_VERSION,
    SUPPORTED_PACKET_SCHEMA_VERSION,
    summarize_handoff_packet,
)
from .packet_validation import assert_valid_handoff_packet

DEFAULT_CACHE_KEY_VERSION = "1.0"

# --- Cache contract v2 identities -------------------------------------------

CACHE_KEY_VERSION_V2 = "2.0"
CACHE_ENTRY_VERSION_V2 = "2.0"
CACHE_NAMESPACE_VERSION_V2 = "2.0"

# Single fixed child directory name for every v2 entry, relative to the
# caller-supplied cache root. It is a constant, never caller-derived.
CACHE_NAMESPACE_V2 = "v2"

CACHE_KEY_V2_PREFIX = "handoff-summary-v2"
_CACHE_KEY_V2_PREFIX_FULL = f"{CACHE_KEY_V2_PREFIX}:{CACHE_KEY_VERSION_V2}:"

_HEX_DIGITS = frozenset("0123456789abcdef")
_SHA256_HEX_CHARS = 64

# H2 reasons that mean the returned source fingerprint is a fixed failure
# constant or does not faithfully identify the packet. Such a packet must never
# receive a v2 cache identity, because distinct packets would otherwise collide.
_INELIGIBLE_SOURCE_REASONS = frozenset(
    {REASON_PACKET_CONTENT_UNSAFE, REASON_PACKET_RESOURCE_LIMIT_EXCEEDED}
)

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


def is_sha256_hex(value: Any) -> bool:
    """Return whether value is exactly a lowercase SHA-256 hex digest."""
    return (
        type(value) is str
        and len(value) == _SHA256_HEX_CHARS
        and all(char in _HEX_DIGITS for char in value)
    )


def handoff_packet_source_fingerprint(packet: Mapping[str, Any]) -> str:
    """Return the canonical H2 source fingerprint for a validated packet.

    The fingerprint is produced by the merged H2 renderer, so it binds every
    canonical packet field -- including ``forbidden_unless_needed``,
    ``acceptance_criteria``, nullable ``branch``/``pr_number`` state, and
    compute limits -- without H3 restating the packet schema.

    Raises ValueError when the packet is invalid (through the canonical #265
    validator) or when H2 reports that the packet cannot be fingerprinted
    faithfully. The message is a fixed non-sensitive string.
    """
    rendered = summarize_handoff_packet(packet)
    if rendered.trust_reason in _INELIGIBLE_SOURCE_REASONS:
        raise ValueError("handoff packet is not eligible for a v2 cache identity")
    if not is_sha256_hex(rendered.source_fingerprint):
        raise ValueError("handoff packet is not eligible for a v2 cache identity")
    return rendered.source_fingerprint


def build_cache_key_v2_from_source_fingerprint(source_fingerprint: str) -> str:
    """Build the v2 cache key bound to an H2 source fingerprint.

    The digest binds the cache-key algorithm version, cache-entry schema
    version, namespace version, supported packet schema version, supported
    renderer version, the H2 source-fingerprint algorithm version, and the
    complete source fingerprint. Changing any one of them changes the key.
    """
    if not is_sha256_hex(source_fingerprint):
        raise ValueError("source_fingerprint must be a lowercase SHA-256 hex digest")

    payload = {
        "cache_key_version": CACHE_KEY_VERSION_V2,
        "cache_entry_version": CACHE_ENTRY_VERSION_V2,
        "cache_namespace_version": CACHE_NAMESPACE_VERSION_V2,
        "packet_schema_version": SUPPORTED_PACKET_SCHEMA_VERSION,
        "renderer_version": RENDERER_VERSION,
        "source_fingerprint_version": SOURCE_FINGERPRINT_VERSION,
        "source_fingerprint": source_fingerprint,
    }
    encoded_payload = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    digest = hashlib.sha256(encoded_payload.encode("utf-8")).hexdigest()

    return f"{_CACHE_KEY_V2_PREFIX_FULL}{digest}"


def build_handoff_packet_cache_key_v2(packet: Mapping[str, Any]) -> str:
    """Build the deterministic v2 cache key for a validated handoff packet."""
    return build_cache_key_v2_from_source_fingerprint(
        handoff_packet_source_fingerprint(packet)
    )


def cache_key_v2_digest(cache_key: Any) -> str | None:
    """Return the fixed-format digest of a v2 cache key, or None if invalid.

    This is the only sanctioned way to derive a filename component from a cache
    key. It accepts exactly ``<prefix>:<version>:<64 lowercase hex>`` and so
    structurally excludes absolute paths, ``..``, slash and backslash variants,
    drive-letter and UNC forms, null characters, reserved platform names, and
    trailing dot or space ambiguities.
    """
    if type(cache_key) is not str:
        return None
    if not cache_key.startswith(_CACHE_KEY_V2_PREFIX_FULL):
        return None
    digest = cache_key[len(_CACHE_KEY_V2_PREFIX_FULL) :]
    if not is_sha256_hex(digest):
        return None
    return digest
