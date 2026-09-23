"""Deterministic, offline provenance for the reusable-capability registry.

Implements exactly the #471 binding contract (algorithm ``registry-canonical-records``,
version ``1``): canonicalize validated parsed registry records into primitive
data, serialize deterministically to compact canonical JSON, and take a SHA-256
digest. Raw YAML formatting, comments, anchors, key order, and whitespace are
never hashed directly; the digest is computed from parsed records plus the
validated ``registry_version`` only.

Matching provenance proves only that two artifacts were computed from the same
canonical registry snapshot. It does not prove correctness, freshness,
authorship, trustworthiness, authorization, compatibility, test adequacy,
ownership validity, approval, readiness, or permission to execute or write.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import fields
from pathlib import Path

import yaml

from .models import (
    PROVENANCE_ALGORITHM,
    PROVENANCE_ALGORITHM_VERSION,
    CapabilityRecord,
    RegistryProvenance,
)
from .reader import (
    SUPPORTED_REGISTRY_VERSIONS,
    RegistryFormatError,
    RegistryReader,
    UnsupportedRegistryVersion,
    _UniqueKeySafeLoader,
)

# Every CapabilityRecord field participates in provenance, partitioned by
# canonicalization rule per the #474 field table consumed by #471.
_SCALAR_FIELDS: tuple[str, ...] = (
    "capability_id",
    "name",
    "summary",
    "status",
    "owner_agent",
    "reuse_guidance",
)
_OPTIONAL_TEXT_FIELDS: tuple[str, ...] = (
    "known_consumer_exemption",
    "deprecated_by",
)
_SET_LIKE_FIELDS: tuple[str, ...] = (
    "canonical_paths",
    "public_interfaces",
    "known_consumers",
    "tests",
    "keywords",
    "side_effects",
    "supporting_agents",
    "inputs",
    "outputs",
    "extension_points",
    "invariants",
    "failure_modes",
    "compatibility",
    "documentation_handoff",
)

# Integrity guard: the three groups must cover exactly the CapabilityRecord
# fields. If the record schema changes, provenance fails loudly at import rather
# than silently dropping or mis-classifying a governed field.
_CLASSIFIED_FIELDS = frozenset(_SCALAR_FIELDS) | frozenset(_OPTIONAL_TEXT_FIELDS) | frozenset(_SET_LIKE_FIELDS)
_RECORD_FIELDS = frozenset(field.name for field in fields(CapabilityRecord))
if _CLASSIFIED_FIELDS != _RECORD_FIELDS:
    raise RuntimeError(
        "provenance field classification is out of sync with CapabilityRecord: "
        f"missing={sorted(_RECORD_FIELDS - _CLASSIFIED_FIELDS)} "
        f"extra={sorted(_CLASSIFIED_FIELDS - _RECORD_FIELDS)}"
    )


def _canonical_set_like(values: Iterable[str], capability_id: str, field: str) -> list[str]:
    """Sort a governed set-like list by exact Unicode code point.

    Duplicates fail closed (no provenance) rather than being silently
    deduplicated. Uses ``sorted(sequence)``, never ``sorted(set(...))``.
    """
    sequence = tuple(values)
    if len(sequence) != len(set(sequence)):
        raise RegistryFormatError(
            f"{capability_id}: {field} contains a duplicate value; no provenance is produced"
        )
    return sorted(sequence)


def _canonical_record(record: CapabilityRecord) -> dict[str, object]:
    payload: dict[str, object] = {}
    for field in _SCALAR_FIELDS:
        payload[field] = getattr(record, field)
    for field in _OPTIONAL_TEXT_FIELDS:
        payload[field] = getattr(record, field)  # exact trimmed str or None
    for field in _SET_LIKE_FIELDS:
        payload[field] = _canonical_set_like(getattr(record, field), record.capability_id, field)
    return payload


def _snapshot_payload(records: Iterable[CapabilityRecord], registry_version: str) -> dict[str, object]:
    ordered = sorted(records, key=lambda record: record.capability_id)
    ids = [record.capability_id for record in ordered]
    if len(ids) != len(set(ids)):
        raise RegistryFormatError("duplicate capability_id values; no provenance is produced")
    return {
        "provenance_algorithm": PROVENANCE_ALGORITHM,
        "provenance_version": PROVENANCE_ALGORITHM_VERSION,
        "registry_version": registry_version,
        "capabilities": [_canonical_record(record) for record in ordered],
    }


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(payload: object) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def build_registry_provenance(
    records: Iterable[CapabilityRecord], registry_version: str
) -> RegistryProvenance:
    """Compute provenance from validated parsed records and a registry version.

    Pure and offline: independent of the filesystem, network, clock, locale,
    environment, Git, and randomness. Unsupported registry versions produce no
    provenance (fail closed).
    """
    if not isinstance(registry_version, str) or registry_version not in SUPPORTED_REGISTRY_VERSIONS:
        raise UnsupportedRegistryVersion(f"unsupported registry version: {registry_version!r}")
    payload = _snapshot_payload(records, registry_version)
    return RegistryProvenance(
        algorithm=PROVENANCE_ALGORITHM,
        algorithm_version=PROVENANCE_ALGORITHM_VERSION,
        registry_version=registry_version,
        digest=_digest(payload),
    ).require_supported()


def _read_registry_version(registry_path: str | Path) -> str:
    """Recover the validated ``registry_version`` from an already-loaded registry.

    Called only after a ``RegistryReader`` has successfully validated the
    document (rejecting malformed YAML, duplicate keys, unknown top-level keys,
    and unsupported versions), so this parse is guaranteed consistent. It reads a
    parsed scalar value, never raw YAML bytes for hashing.
    """
    try:
        text = Path(registry_path).read_text(encoding="utf-8")
        document = yaml.load(text, Loader=_UniqueKeySafeLoader)
    except OSError as exc:
        raise RegistryFormatError("unable to read registry for provenance") from exc
    except yaml.YAMLError as exc:
        raise RegistryFormatError("registry YAML is malformed") from exc
    version = document.get("registry_version") if isinstance(document, Mapping) else None
    if not isinstance(version, str):
        raise RegistryFormatError("registry_version must be a string")
    return version


def compute_registry_provenance(reader: RegistryReader) -> RegistryProvenance:
    """Compute provenance for the snapshot already validated by ``reader``."""
    version = _read_registry_version(reader.registry_path)
    return build_registry_provenance(reader.records, version)


def provenance_for_registry(registry_path: str | Path | None = None) -> RegistryProvenance:
    """Load and validate a registry, then compute its provenance in one call."""
    reader = RegistryReader(registry_path)
    return compute_registry_provenance(reader)
