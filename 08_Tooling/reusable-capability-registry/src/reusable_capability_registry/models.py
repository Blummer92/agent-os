from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
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


# ---------------------------------------------------------------------------
# RC4 report-only validation models (#494 under the #254 binding contract).
# Distinct from the RC3 discovery Confidence: evidence confidence and validation
# severity are independent axes and are never inter-converted.
# ---------------------------------------------------------------------------

VALIDATION_REPORT_VERSION = "1.0"
VALIDATION_INFORMATIONAL_NOTICE = (
    "Static report-only validation evidence; it does not authorize implementation, "
    "registry mutation, repository writes, readiness changes, approval, or merge. "
    "Matching registry provenance proves only that discovery and validation used the "
    "same canonical registry snapshot; it does not prove correctness, compatibility, "
    "ownership validity, readiness, or authorization."
)


class EvidenceConfidence(str, Enum):
    VERIFIED = "verified"
    PROBABLE = "probable"
    UNVERIFIED = "unverified"
    CONTRADICTED = "contradicted"
    MANUAL_REVIEW = "manual-review"


class ValidationSeverity(str, Enum):
    PASS = "pass"
    WARN = "warn"
    MANUAL_REVIEW = "manual-review"
    FAIL = "fail"


_SEVERITY_RANK = {
    ValidationSeverity.PASS: 0,
    ValidationSeverity.WARN: 1,
    ValidationSeverity.MANUAL_REVIEW: 2,
    ValidationSeverity.FAIL: 3,
}


def _none_first(value: object) -> tuple[int, object]:
    """Sort key placing ``None`` before populated values without comparing across types."""
    return (1, value) if value is not None else (0, "")


def _aggregate_severity(findings: Iterable["ValidationFinding"]) -> ValidationSeverity:
    severity = ValidationSeverity.PASS
    for finding in findings:
        if _SEVERITY_RANK[finding.severity] > _SEVERITY_RANK[severity]:
            severity = finding.severity
    return severity


@dataclass(frozen=True, slots=True)
class ValidationEvidence:
    path: str | None
    line: int | None
    symbol: str | None
    source_type: str
    detail: str

    def __post_init__(self) -> None:
        if self.path is not None and (
            not isinstance(self.path, str) or not self.path or self.path.startswith("/") or "\\" in self.path
        ):
            raise ValueError("evidence path must be a non-empty repository-relative POSIX path")
        if self.line is not None and (not isinstance(self.line, int) or isinstance(self.line, bool) or self.line <= 0):
            raise ValueError("evidence line must be a positive integer when present")
        if self.symbol is not None and (not isinstance(self.symbol, str) or not self.symbol):
            raise ValueError("evidence symbol must be a non-empty string when present")
        if not isinstance(self.source_type, str) or not self.source_type:
            raise ValueError("evidence source_type must be a non-empty string")
        if not isinstance(self.detail, str) or not self.detail:
            raise ValueError("evidence detail must be a non-empty string")

    def sort_key(self) -> tuple:
        return (_none_first(self.path), _none_first(self.line), _none_first(self.symbol), self.source_type, self.detail)


@dataclass(frozen=True, slots=True)
class ValidationFinding:
    code: str
    confidence: EvidenceConfidence
    severity: ValidationSeverity
    capability_id: str | None
    surface: str
    message: str
    evidence: tuple[ValidationEvidence, ...] = ()
    manual_review_reason: str | None = None

    def __post_init__(self) -> None:
        for name in ("code", "surface", "message"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"finding {name} must be a non-empty string")
        if not isinstance(self.confidence, EvidenceConfidence):
            raise ValueError("finding confidence must be an EvidenceConfidence")
        if not isinstance(self.severity, ValidationSeverity):
            raise ValueError("finding severity must be a ValidationSeverity")
        if self.capability_id is not None and (not isinstance(self.capability_id, str) or not self.capability_id):
            raise ValueError("finding capability_id must be a non-empty string or None")
        if not isinstance(self.evidence, tuple):
            raise ValueError("finding evidence must be a tuple")
        needs_reason = self.severity is ValidationSeverity.MANUAL_REVIEW
        has_reason = bool(self.manual_review_reason)
        if needs_reason and not has_reason:
            raise ValueError("manual-review findings require a manual_review_reason")
        if not needs_reason and self.manual_review_reason is not None:
            raise ValueError("manual_review_reason is only allowed on manual-review findings")

    def normalized(self) -> "ValidationFinding":
        return replace(self, evidence=tuple(sorted(self.evidence, key=lambda item: item.sort_key())))

    def sort_key(self) -> tuple:
        first = self.evidence[0] if self.evidence else None
        first_path = first.path if first is not None else None
        first_line = first.line if first is not None else None
        return (
            -_SEVERITY_RANK[self.severity],
            _none_first(self.capability_id),
            self.code,
            self.surface,
            _none_first(first_path),
            _none_first(first_line),
            self.message,
        )


@dataclass(frozen=True, slots=True)
class ValidationReport:
    report_version: str
    severity: ValidationSeverity
    provenance: RegistryProvenance | None
    capabilities_checked: int
    checks_run: int
    confidence_counts: tuple[tuple[str, int], ...]
    severity_counts: tuple[tuple[str, int], ...]
    findings: tuple[ValidationFinding, ...]
    informational_notice: str

    def __post_init__(self) -> None:
        if self.report_version != VALIDATION_REPORT_VERSION:
            raise ValueError("report_version must be '1.0'")
        if not isinstance(self.severity, ValidationSeverity):
            raise ValueError("report severity must be a ValidationSeverity")
        if self.provenance is not None and not isinstance(self.provenance, RegistryProvenance):
            raise ValueError("report provenance must be a RegistryProvenance or None")
        for name in ("capabilities_checked", "checks_run"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if not isinstance(self.findings, tuple):
            raise ValueError("findings must be a tuple")
        if self.severity is not _aggregate_severity(self.findings):
            raise ValueError("report severity must equal the aggregated finding severity")
        if not isinstance(self.informational_notice, str) or not self.informational_notice:
            raise ValueError("informational_notice must be a non-empty string")

    @classmethod
    def from_findings(
        cls,
        findings: Iterable["ValidationFinding"],
        *,
        provenance: "RegistryProvenance | None",
        capabilities_checked: int,
        checks_run: int,
        informational_notice: str = VALIDATION_INFORMATIONAL_NOTICE,
    ) -> "ValidationReport":
        """The single construction path: normalizes/orders once and derives severity+counts."""
        normalized = tuple(sorted((item.normalized() for item in findings), key=lambda item: item.sort_key()))
        confidence_counts = tuple(
            (member.value, sum(1 for finding in normalized if finding.confidence is member))
            for member in sorted(EvidenceConfidence, key=lambda member: member.value)
        )
        severity_counts = tuple(
            (member.value, sum(1 for finding in normalized if finding.severity is member))
            for member in sorted(ValidationSeverity, key=lambda member: member.value)
        )
        return cls(
            report_version=VALIDATION_REPORT_VERSION,
            severity=_aggregate_severity(normalized),
            provenance=provenance,
            capabilities_checked=capabilities_checked,
            checks_run=checks_run,
            confidence_counts=confidence_counts,
            severity_counts=severity_counts,
            findings=normalized,
            informational_notice=informational_notice,
        )
