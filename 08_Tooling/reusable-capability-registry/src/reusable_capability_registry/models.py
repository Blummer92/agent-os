from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

# Canonical identity of the reusable-capability registry provenance algorithm,
# fixed by the #471 binding contract. The algorithm version is bumped only when
# the normalization, serializer, or hash envelope changes (see provenance.py).
PROVENANCE_ALGORITHM = "registry-canonical-records"
PROVENANCE_ALGORITHM_VERSION = 1
SUPPORTED_PROVENANCE_ALGORITHMS = frozenset({PROVENANCE_ALGORITHM})
SUPPORTED_PROVENANCE_VERSIONS = frozenset({PROVENANCE_ALGORITHM_VERSION})
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class Confidence(str, Enum):
    VERIFIED = "verified"
    PROBABLE = "probable"
    UNVERIFIED = "unverified"
    MANUAL_REVIEW = "manual-review"


class UnsupportedProvenanceError(ValueError):
    """Raised when a provenance value claims an unsupported algorithm or version."""


@dataclass(frozen=True, slots=True)
class RegistryProvenance:
    """Immutable, version-aware identity of a canonical registry snapshot.

    Matching provenance proves only that two artifacts were computed from the
    same canonical registry snapshot. It does not prove correctness, freshness,
    authorship, trustworthiness, authorization, compatibility, test adequacy,
    ownership validity, approval, readiness, or permission to execute or write.

    Shape is validated on construction (malformed values fail closed). Support
    for a given algorithm/version is a separate fail-closed gate exposed through
    ``require_supported`` so that unrelated algorithm versions can still be
    represented and compared without being silently treated as valid.
    """

    algorithm: str
    algorithm_version: int
    registry_version: str
    digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.algorithm, str) or not self.algorithm:
            raise ValueError("provenance algorithm must be a non-empty string")
        # bool is an int subclass; reject it explicitly so True/False cannot pose
        # as an algorithm version.
        if not isinstance(self.algorithm_version, int) or isinstance(self.algorithm_version, bool):
            raise ValueError("provenance algorithm_version must be an int")
        if not isinstance(self.registry_version, str) or not self.registry_version:
            raise ValueError("provenance registry_version must be a non-empty string")
        if not isinstance(self.digest, str) or not _DIGEST_RE.fullmatch(self.digest):
            raise ValueError("provenance digest must be 64 lowercase hexadecimal characters")

    @property
    def is_supported(self) -> bool:
        return (
            self.algorithm in SUPPORTED_PROVENANCE_ALGORITHMS
            and self.algorithm_version in SUPPORTED_PROVENANCE_VERSIONS
        )

    def require_supported(self) -> RegistryProvenance:
        """Fail closed unless this provenance uses a supported algorithm/version."""
        if self.algorithm not in SUPPORTED_PROVENANCE_ALGORITHMS:
            raise UnsupportedProvenanceError(f"unsupported provenance algorithm: {self.algorithm!r}")
        if self.algorithm_version not in SUPPORTED_PROVENANCE_VERSIONS:
            raise UnsupportedProvenanceError(
                f"unsupported provenance algorithm_version: {self.algorithm_version!r}"
            )
        return self

    def to_payload(self) -> dict[str, object]:
        """Deterministic serializer projection (key order is irrelevant under sort_keys)."""
        return {
            "algorithm": self.algorithm,
            "algorithm_version": self.algorithm_version,
            "digest": self.digest,
            "registry_version": self.registry_version,
        }


@dataclass(frozen=True, slots=True)
class CapabilityRecord:
    capability_id: str
    name: str
    summary: str
    status: str
    canonical_paths: tuple[str, ...]
    public_interfaces: tuple[str, ...]
    owner_agent: str
    supporting_agents: tuple[str, ...]
    known_consumers: tuple[str, ...]
    known_consumer_exemption: str | None
    tests: tuple[str, ...]
    keywords: tuple[str, ...]
    reuse_guidance: str
    side_effects: tuple[str, ...]
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    extension_points: tuple[str, ...] = ()
    invariants: tuple[str, ...] = ()
    failure_modes: tuple[str, ...] = ()
    compatibility: tuple[str, ...] = ()
    documentation_handoff: tuple[str, ...] = ()
    deprecated_by: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    capability: CapabilityRecord
    confidence: Confidence
    evidence_basis: tuple[str, ...]
    warnings: tuple[str, ...]
    manual_review_reasons: tuple[str, ...]
    # Optional same-snapshot provenance. Absent (None) preserves the approved
    # legacy discovery/serialization output; a populated value is attached
    # identically to every result from one reader snapshot.
    provenance: RegistryProvenance | None = None
