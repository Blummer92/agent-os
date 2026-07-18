from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Confidence(str, Enum):
    VERIFIED = "verified"
    PROBABLE = "probable"
    UNVERIFIED = "unverified"
    MANUAL_REVIEW = "manual-review"


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


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    capability: CapabilityRecord
    confidence: Confidence
    evidence_basis: tuple[str, ...]
    warnings: tuple[str, ...]
    manual_review_reasons: tuple[str, ...]
