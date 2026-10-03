"""Governed teacher visual-decision record contract (#3252).

A ``TeacherVisualDecisionRecord`` captures one teacher's per-role visual
choice: who decided, when, for which role/slot, which asset was selected
(with Lane-D content/revision identity), what the planner recommended, and
the exact candidate set the choice was made against. Decisions are
evaluated at use time — never silently honored, never silently replaced:

- valid   → the decision's asset is honored for its role;
- invalid → the role is blocked with an explicit reason code.

This module is pure (no I/O, no network). Persistence lives in
``instructional_materials_coach.teacher_decisions`` (JSON files under
``reports/teacher-decisions/``); evaluation is consumed by
``plan_governed_visual_reuse`` via ``evaluate_decision_validity``.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from typing import Any, Collection, Mapping

from .asset_content_identity import validate_content_identity

TEACHER_VISUAL_DECISION_CONTRACT_ID = "teacher-visual-decision-v1"

INVALIDATION_RULE_CANDIDATE_SET_OR_CONTENT_CHANGE = "candidate-set-or-content-change"
INVALIDATION_RULES = (INVALIDATION_RULE_CANDIDATE_SET_OR_CONTENT_CHANGE,)

# Machine-readable invalidation reason codes. Every invalidation carries one
# of these plus a human-readable detail; a bare boolean is a violation.
REASON_CANDIDATE_SET_CHANGED = "candidate-set-changed"
REASON_ASSET_CONTENT_CHANGED = "asset-content-changed"
REASON_ASSET_NO_LONGER_ELIGIBLE = "asset-no-longer-eligible"
REASON_SOURCE_REVISION_MOVED = "source-revision-moved"
REASON_ROLE_RETIRED = "role-retired"
REASON_SUPERSEDED = "superseded"

DECISION_STATUSES = ("active", "invalidated", "superseded")
DECISION_SCOPES = ("unit", "coursewide", "global")

_REQUIRED_FIELDS = frozenset(
    {
        "contract_id",
        "decision_id",
        "actor",
        "decided_at",
        "requirement_id",
        "source_revision",
        "role",
        "slot",
        "selected_asset",
        "overridden_recommendation",
        "candidate_set_fingerprint",
        "scope",
        "invalidation_rule",
        "status",
    }
)
_SELECTED_ASSET_FIELDS = frozenset(
    {
        "asset_id",
        "provider_file_id",
        "content_identity",
        "revision_identity",
        "provenance",
    }
)
_SHA256_RE_LEN = 64


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _SHA256_RE_LEN
        and all(c in "0123456789abcdef" for c in value)
    )


def _require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if len(value) > 512:
        raise ValueError(f"{name} exceeds the length bound")
    return value


@dataclasses.dataclass(frozen=True)
class SelectedAssetIdentity:
    """The exact selected content: logical asset + Lane-D identities."""

    asset_id: str
    provider_file_id: str
    content_identity: Mapping[str, Any]
    revision_identity: str
    provenance: Mapping[str, Any]

    def __post_init__(self) -> None:
        _require_text(self.asset_id, "selected_asset.asset_id")
        _require_text(self.provider_file_id, "selected_asset.provider_file_id")
        if not isinstance(self.content_identity, Mapping) or not self.content_identity:
            raise ValueError("selected_asset.content_identity must be a non-empty mapping")
        try:
            validate_content_identity(self.content_identity)
        except (TypeError, ValueError) as exc:
            raise ValueError("selected_asset.content_identity is not governed-verifiable") from exc
        _require_text(self.revision_identity, "selected_asset.revision_identity")
        if not isinstance(self.provenance, Mapping):
            raise ValueError("selected_asset.provenance must be a mapping")

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "provider_file_id": self.provider_file_id,
            "content_identity": dict(self.content_identity),
            "revision_identity": self.revision_identity,
            "provenance": dict(self.provenance),
        }


@dataclasses.dataclass(frozen=True)
class TeacherVisualDecisionRecord:
    """One governed teacher visual choice. Immutable; invalidation is
    evaluated at read time, never by mutating the record."""

    decision_id: str
    actor: str
    decided_at: str
    requirement_id: str
    source_revision: str
    role: str
    slot: int
    selected_asset: SelectedAssetIdentity
    overridden_recommendation: str | None
    candidate_set_fingerprint: str
    scope: str
    invalidation_rule: str
    status: str = "active"
    invalidation: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        _require_text(self.decision_id, "decision_id")
        _require_text(self.actor, "actor")
        _require_text(self.decided_at, "decided_at")
        _require_text(self.requirement_id, "requirement_id")
        _require_text(self.source_revision, "source_revision")
        _require_text(self.role, "role")
        if not isinstance(self.slot, int) or isinstance(self.slot, bool) or self.slot < 0:
            raise ValueError("slot must be a non-negative integer")
        if self.overridden_recommendation is not None:
            _require_text(self.overridden_recommendation, "overridden_recommendation")
        if not _is_sha256(self.candidate_set_fingerprint):
            raise ValueError("candidate_set_fingerprint must be lowercase SHA-256")
        if self.scope not in DECISION_SCOPES:
            raise ValueError(f"scope must be one of {DECISION_SCOPES}")
        if self.invalidation_rule not in INVALIDATION_RULES:
            raise ValueError(f"invalidation_rule must be one of {INVALIDATION_RULES}")
        if self.status not in DECISION_STATUSES:
            raise ValueError(f"status must be one of {DECISION_STATUSES}")
        if self.invalidation is not None and not isinstance(self.invalidation, Mapping):
            raise ValueError("invalidation must be a mapping or null")

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": TEACHER_VISUAL_DECISION_CONTRACT_ID,
            "decision_id": self.decision_id,
            "actor": self.actor,
            "decided_at": self.decided_at,
            "requirement_id": self.requirement_id,
            "source_revision": self.source_revision,
            "role": self.role,
            "slot": self.slot,
            "selected_asset": self.selected_asset.to_dict(),
            "overridden_recommendation": self.overridden_recommendation,
            "candidate_set_fingerprint": self.candidate_set_fingerprint,
            "scope": self.scope,
            "invalidation_rule": self.invalidation_rule,
            "status": self.status,
            "invalidation": (
                None if self.invalidation is None else dict(self.invalidation)
            ),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TeacherVisualDecisionRecord":
        """Build from a plain mapping; raises ValueError on any violation."""
        if not isinstance(value, Mapping):
            raise ValueError("decision record must be a mapping")
        missing = _REQUIRED_FIELDS - set(value.keys())
        if missing:
            raise ValueError(f"decision record missing fields: {sorted(missing)}")
        if value.get("contract_id") != TEACHER_VISUAL_DECISION_CONTRACT_ID:
            raise ValueError(
                f"contract_id must be {TEACHER_VISUAL_DECISION_CONTRACT_ID}"
            )
        selected = value.get("selected_asset")
        if not isinstance(selected, Mapping):
            raise ValueError("selected_asset must be a mapping")
        missing_asset = _SELECTED_ASSET_FIELDS - set(selected.keys())
        if missing_asset:
            raise ValueError(
                f"selected_asset missing fields: {sorted(missing_asset)}"
            )
        return cls(
            decision_id=value["decision_id"],
            actor=value["actor"],
            decided_at=value["decided_at"],
            requirement_id=value["requirement_id"],
            source_revision=value["source_revision"],
            role=value["role"],
            slot=value["slot"],
            selected_asset=SelectedAssetIdentity(
                asset_id=selected["asset_id"],
                provider_file_id=selected["provider_file_id"],
                content_identity=selected["content_identity"],
                revision_identity=selected["revision_identity"],
                provenance=selected["provenance"],
            ),
            overridden_recommendation=value["overridden_recommendation"],
            candidate_set_fingerprint=value["candidate_set_fingerprint"],
            scope=value["scope"],
            invalidation_rule=value["invalidation_rule"],
            status=value.get("status", "active"),
            invalidation=value.get("invalidation"),
        )


@dataclasses.dataclass(frozen=True)
class DecisionValidity:
    """The outcome of evaluating one decision against current evidence."""

    valid: bool
    reason_code: str | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        if self.valid and (self.reason_code is not None or self.detail is not None):
            raise ValueError("a valid decision carries no reason")
        if not self.valid and not self.reason_code:
            raise ValueError("an invalid decision requires a reason_code")


def canonical_candidate_set_fingerprint(candidates: object) -> str:
    """SHA-256 over the canonical candidate set.

    The fingerprint binds asset identity (asset ID, Notion page ID, Drive
    file ID), sorted — never byte order, never content bytes. A content
    revision therefore does NOT move this fingerprint; it is detected by
    the separate content-identity comparison (``asset-content-changed``).
    Unrelated requirement revisions never touch the candidate list, so they
    never invalidate.
    """
    items: list[dict[str, Any]] = []
    if isinstance(candidates, (list, tuple)):
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            evidence = candidate.get("compatibility_evidence")
            if not isinstance(evidence, Mapping):
                continue
            asset_reference = evidence.get("asset_reference")
            library_reference = evidence.get("library_reference")
            items.append(
                {
                    "asset_id": (
                        asset_reference.get("asset_id")
                        if isinstance(asset_reference, Mapping)
                        else None
                    ),
                    "page_id": (
                        library_reference.get("page_id")
                        if isinstance(library_reference, Mapping)
                        else None
                    ),
                    "drive_file_id": (
                        library_reference.get("drive_file_id")
                        if isinstance(library_reference, Mapping)
                        else None
                    ),
                }
            )
    items.sort(key=lambda item: json.dumps(item, sort_keys=True))
    canonical = json.dumps(items, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def evaluate_decision_validity(
    decision: Mapping[str, Any],
    *,
    candidate_set_fingerprint: str | None,
    eligible_asset_ids: Collection[str],
    current_content_identities: Mapping[str, Mapping[str, Any] | None],
    source_revision: str | None,
    active_roles: Collection[str] | None = None,
) -> DecisionValidity:
    """Evaluate one decision record against current governed evidence.

    Checks run in a fixed order; the first failure wins. Never raises for
    evidence gaps — an unverifiable decision fails closed with an explicit
    reason, it never becomes a silent honor.
    """
    role = decision.get("role")
    if active_roles is not None and role not in active_roles:
        return DecisionValidity(
            valid=False,
            reason_code=REASON_ROLE_RETIRED,
            detail=f"role {role!r} no longer exists in the requirement",
        )

    recorded_fingerprint = decision.get("candidate_set_fingerprint")
    if candidate_set_fingerprint is None:
        recorded_revision = decision.get("source_revision")
        if (
            source_revision is not None
            and recorded_revision is not None
            and source_revision != recorded_revision
        ):
            return DecisionValidity(
                valid=False,
                reason_code=REASON_SOURCE_REVISION_MOVED,
                detail=(
                    f"evidence source moved {recorded_revision!r} -> "
                    f"{source_revision!r} and the candidate set cannot be re-verified"
                ),
            )
        return DecisionValidity(
            valid=False,
            reason_code=REASON_CANDIDATE_SET_CHANGED,
            detail="current candidate set is unavailable; the decision cannot be verified",
        )
    if candidate_set_fingerprint != recorded_fingerprint:
        return DecisionValidity(
            valid=False,
            reason_code=REASON_CANDIDATE_SET_CHANGED,
            detail=(
                f"candidate set changed: recorded "
                f"{str(recorded_fingerprint)[:12]} != current "
                f"{candidate_set_fingerprint[:12]}"
            ),
        )

    selected = decision.get("selected_asset")
    asset_id = selected.get("asset_id") if isinstance(selected, Mapping) else None
    if asset_id not in eligible_asset_ids:
        return DecisionValidity(
            valid=False,
            reason_code=REASON_ASSET_NO_LONGER_ELIGIBLE,
            detail=f"asset {asset_id!r} is not in the current eligible set",
        )

    recorded_identity = (
        selected.get("content_identity") if isinstance(selected, Mapping) else None
    )
    current_identity = current_content_identities.get(asset_id)  # type: ignore[arg-type]
    if current_identity is None:
        return DecisionValidity(
            valid=False,
            reason_code=REASON_ASSET_CONTENT_CHANGED,
            detail=(
                f"current content identity for asset {asset_id!r} is "
                "unverifiable; the decision cannot be honored"
            ),
        )
    if _canonical_json(current_identity) != _canonical_json(recorded_identity):
        return DecisionValidity(
            valid=False,
            reason_code=REASON_ASSET_CONTENT_CHANGED,
            detail=(
                f"content identity for asset {asset_id!r} changed since the "
                "decision; the teacher must re-confirm"
            ),
        )

    return DecisionValidity(valid=True)
