from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .models import CheckResult, Status


CANONICAL_ISSUE_TIERS = {
    "tier:0-small-maintenance",
    "tier:1-standard-implementation",
    "tier:2-governed-cross-system",
}
CANONICAL_READINESS = {"status:ready", "status:blocked", "status:needs-decision"}
CANONICAL_DOCUMENTATION_IMPACT = {
    "docs-required",
    "docs-not-required",
    "docs-needs-decision",
}
CANONICAL_SOURCE_ROUTES = {
    "GitHub",
    "Notion handoff",
    "Google Drive handoff",
    "ChatGPT planning only",
    "needs-decision",
}
CANONICAL_EXTERNAL_WRITE_BOUNDARIES = {
    "no-external-write",
    "external-write-requested",
    "needs-decision",
}

CANDIDATE_ISSUE_TIER_ALIASES = {"tier:2-high-risk-or-governed-change"}
LEGACY_LIFECYCLE_STATUSES = {
    "status:ready-for-planning",
    "status:blocked-human-review",
}
LEGACY_METADATA_PREFIXES = ("risk:", "surface:", "system:", "phase:")
REGISTERED_OWNER_LABELS = {
    "owner:qa-test-agent",
    "owner:github-service-agent",
    "owner:integration-manager",
    "owner:instructional-materials-coach",
    "owner:google-workspace-automation-engineer",
    "owner:teacher-modeling-coach",
}
REGISTRY_ONLY_OWNERS = {
    "ChatGPT Orchestrator",
    "Modeling & Dashboard Governance Agent",
    "Agent Orchestrator",
    "Unit Alignment Agent",
}
APPROVED_OWNER_ALIASES = {"QA Agent"}
GOVERNED_ENUM_FIELDS = {
    "issue_tier",
    "readiness_candidate",
    "documentation_impact",
    "source_route",
    "external_write_boundary",
    "primary_owner",
}


@dataclass(frozen=True)
class MetadataValidationResult:
    field: str
    input_evidence: str
    classification: str
    outcome: Status
    reason: str

    def to_check(self) -> CheckResult:
        return CheckResult(
            f"metadata:{self.field}",
            self.outcome,
            self.reason,
            [
                f"field={self.field}",
                f"input_evidence={self.input_evidence}",
                f"classification={self.classification}",
            ],
        )


def validate_metadata_evidence(field: str, input_evidence: str) -> MetadataValidationResult:
    """Classify one metadata evidence value without live writes or network calls."""
    value = input_evidence.strip()

    if field == "issue_tier":
        return _validate_issue_tier(field, value)
    if field == "readiness_candidate":
        return _validate_readiness_candidate(field, value)
    if field == "lifecycle_status":
        return _validate_lifecycle_status(field, value)
    if field == "documentation_impact":
        return _validate_closed_enum(field, value, CANONICAL_DOCUMENTATION_IMPACT)
    if field == "source_route":
        return _validate_closed_enum(field, value, CANONICAL_SOURCE_ROUTES)
    if field == "external_write_boundary":
        return _validate_closed_enum(field, value, CANONICAL_EXTERNAL_WRITE_BOUNDARIES)
    if field == "primary_owner":
        return _validate_primary_owner(field, value)
    if field == "legacy_metadata":
        return _validate_legacy_metadata(field, value)

    return MetadataValidationResult(
        field,
        value,
        "out-of-scope",
        Status.MANUAL_REVIEW,
        "Metadata field is outside the MD0 v1 validation contract.",
    )


def validate_fixture_case(case: Mapping[str, object]) -> MetadataValidationResult:
    """Evaluate a fixture case using only its observed field and input evidence."""
    return validate_metadata_evidence(str(case["field"]), str(case["input_evidence"]))


def _validate_issue_tier(field: str, value: str) -> MetadataValidationResult:
    if value in CANONICAL_ISSUE_TIERS:
        return _result(field, value, "canonical", Status.PASS, "Exact canonical issue-tier value.")
    if value in CANDIDATE_ISSUE_TIER_ALIASES:
        return _result(
            field,
            value,
            "candidate-alias",
            Status.MANUAL_REVIEW,
            "Candidate issue-tier alias requires human review before normalization.",
        )
    if _is_generic_tier_language(value):
        classification = "legacy-evidence-only" if value.startswith("Tier 3") else "ambiguous"
        return _result(
            field,
            value,
            classification,
            Status.MANUAL_REVIEW,
            "Generic Tier 0-3 language must not silently normalize to issue_tier.",
        )
    return _result(field, value, "invalid", Status.FAIL, "Unknown closed-enum issue-tier value.")


def _validate_readiness_candidate(field: str, value: str) -> MetadataValidationResult:
    conflict = _parse_readiness_conflict(value)
    if conflict is not None:
        body_value, label_value = conflict
        if body_value != label_value:
            return _result(
                field,
                value,
                "ambiguous",
                Status.MANUAL_REVIEW,
                "Conflicting readiness body and label evidence requires manual review.",
            )
    if value in CANONICAL_READINESS:
        return _result(field, value, "canonical", Status.PASS, "Exact canonical readiness value.")
    return _result(field, value, "invalid", Status.FAIL, "Unknown closed-enum readiness value.")


def _validate_lifecycle_status(field: str, value: str) -> MetadataValidationResult:
    if value in CANONICAL_READINESS:
        return _result(field, value, "canonical", Status.PASS, "Exact canonical lifecycle status value.")
    if value in LEGACY_LIFECYCLE_STATUSES:
        return _result(
            field,
            value,
            "legacy-evidence-only",
            Status.MANUAL_REVIEW,
            "Legacy lifecycle status must not silently normalize to canonical readiness.",
        )
    return _result(field, value, "invalid", Status.FAIL, "Unknown closed-enum lifecycle status value.")


def _validate_closed_enum(field: str, value: str, canonical_values: set[str]) -> MetadataValidationResult:
    if value in canonical_values:
        return _result(field, value, "canonical", Status.PASS, "Exact canonical metadata value.")
    return _result(field, value, "invalid", Status.FAIL, "Unknown closed-enum metadata value.")


def _validate_primary_owner(field: str, value: str) -> MetadataValidationResult:
    if value in REGISTERED_OWNER_LABELS:
        return _result(field, value, "canonical", Status.PASS, "Registered owner value.")
    if value in REGISTRY_ONLY_OWNERS:
        return _result(
            field,
            value,
            "canonical",
            Status.WARN,
            "Canonical registry owner is not exposed on the current issue-form surface.",
        )
    if value in APPROVED_OWNER_ALIASES:
        return _result(field, value, "approved-alias", Status.WARN, "Approved owner alias requires canonical writeback.")
    return _result(
        field,
        value,
        "ambiguous",
        Status.MANUAL_REVIEW,
        "Unregistered owner prose must not create a new agent.",
    )


def _validate_legacy_metadata(field: str, value: str) -> MetadataValidationResult:
    if value.startswith(LEGACY_METADATA_PREFIXES):
        return _result(
            field,
            value,
            "legacy-evidence-only",
            Status.MANUAL_REVIEW,
            "Legacy metadata is evidence only and is outside the MD0 v1 enum contract.",
        )
    return _result(field, value, "out-of-scope", Status.MANUAL_REVIEW, "Unrecognized legacy metadata evidence.")


def _result(
    field: str,
    value: str,
    classification: str,
    outcome: Status,
    reason: str,
) -> MetadataValidationResult:
    return MetadataValidationResult(field, value, classification, outcome, reason)


def _is_generic_tier_language(value: str) -> bool:
    return value in {"Tier 0", "Tier 1", "Tier 2"} or value.startswith("Tier 3")


def _parse_readiness_conflict(value: str) -> tuple[str, str] | None:
    parts = dict(
        item.split("=", 1)
        for item in (piece.strip() for piece in value.split(";"))
        if "=" in item
    )
    body_value = parts.get("body")
    label_value = parts.get("label")
    if body_value is None or label_value is None:
        return None
    return body_value.strip(), label_value.strip()
