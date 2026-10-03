"""Pure orchestration for governed visual reuse before classroom artifact writes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from instructional_workflow_contracts import ValidationResult, ValidationStatus
from instructional_workflow_contracts.asset_content_identity import (
    content_identity_from_fingerprint,
)
from instructional_workflow_contracts.cohesive_visual_plan import plan_cohesive_visual_set
from instructional_workflow_contracts.material_requirement import validate_material_requirement
from instructional_workflow_contracts.reuse_planner import plan_instructional_artifact_reuse
from instructional_workflow_contracts.teacher_visual_decision import (
    DecisionValidity,
    canonical_candidate_set_fingerprint,
    evaluate_decision_validity,
)
from instructional_workflow_contracts.visual_asset_candidates import (
    V2_CONTRACT_ID as VISUAL_CANDIDATES_V2_CONTRACT_ID,
    filter_approved_visual_candidates,
)
from instructional_workflow_contracts.visual_asset_compatibility import (
    validate_visual_asset_compatibility_evidence,
)
from instructional_workflow_contracts.visual_needs import plan_visual_needs


def _scope_candidates_to_current_assets(
    visual_candidates: object,
    current_asset_evidence: object,
    source_revision: object,
) -> tuple[str, list[object]]:
    """Constrain supplied governed candidates to exact current-unit asset identity.

    Returns (scope_state, scoped_candidates) where scope_state is one of:
    - "ok": candidates scoped (or passed through for offline/planner-only use);
    - "true-zero": evidence was supplied and admitted zero candidates;
    - "no-evidence": no candidate evidence was supplied at all;
    - "malformed": candidate or current-asset evidence is malformed;
    - "identity-conflict": one exact library page + Drive identity maps to two
      competing Asset IDs (fail closed; no precedence invented);
    - "no-read-evidence": zero candidates admitted and no read is identified
      (no source_revision), so absence cannot be proven.

    The caller may omit current asset evidence for existing offline/planner-only
    uses. When current evidence is supplied, candidates are admitted by exact
    asset identity against the scope-eligible evidence set (#3253):
    unit-specific assets match on (Asset ID, page ID, Drive file ID) exactly;
    coursewide/cross-unit/global assets match on (Asset ID, page ID) with an
    optional Drive file ID, since scope-eligible assets are not required to
    carry a unit relation or a Drive binding.
    """
    if visual_candidates is None and current_asset_evidence is None:
        return ("no-evidence", [])
    if visual_candidates is not None and type(visual_candidates) is not list:
        return ("malformed", [])
    if current_asset_evidence is None:
        # Offline/planner-only use: no current-unit scoping requested.
        return ("ok", list(visual_candidates or []))
    if type(current_asset_evidence) is not list:
        return ("malformed", [])

    admitted: set[tuple[str, str, str]] = set()
    asset_ids_by_external_identity: dict[tuple[str, str], set[str]] = {}
    for item in current_asset_evidence:
        if type(item) is not dict:
            continue
        reference = item.get("library_reference")
        if type(reference) is not dict:
            continue
        asset_id = item.get("asset_id")
        page_id = reference.get("page_id")
        drive_file_id = reference.get("drive_file_id")
        # #3253: scope-eligible assets (coursewide/cross-unit/global) are not
        # required to carry a Drive binding; unit-specific assets keep the
        # exact triple requirement (#2816-era strictness, unchanged).
        scope = item.get("reuse_scope", "unit-specific")
        if not isinstance(drive_file_id, str):
            drive_file_id = ""
        if not drive_file_id and scope == "unit-specific":
            continue
        if all(isinstance(value, str) and value for value in (asset_id, page_id)):
            admitted.add((asset_id, page_id, drive_file_id))
            asset_ids_by_external_identity.setdefault((page_id, drive_file_id), set()).add(asset_id)

    if current_asset_evidence and not admitted:
        return ("malformed", [])

    # #3104: one exact library page + Drive identity cannot authorize two
    # competing Asset IDs. Canonical reconciliation belongs to #1387; this
    # consumer must fail closed instead of inventing precedence.
    if any(len(asset_ids) > 1 for asset_ids in asset_ids_by_external_identity.values()):
        return ("identity-conflict", [])

    scoped: list[object] = []
    for candidate in visual_candidates or []:
        if type(candidate) is not dict:
            continue
        evidence = candidate.get("compatibility_evidence")
        if type(evidence) is not dict:
            continue
        asset_reference = evidence.get("asset_reference")
        library_reference = evidence.get("library_reference")
        if type(asset_reference) is not dict or type(library_reference) is not dict:
            continue
        candidate_drive = library_reference.get("drive_file_id")
        if not isinstance(candidate_drive, str):
            candidate_drive = ""
        identity = (
            asset_reference.get("asset_id"),
            library_reference.get("page_id"),
            candidate_drive,
        )
        if (
            isinstance(identity[0], str) and identity[0]
            and isinstance(identity[1], str) and identity[1]
            and identity in admitted
        ):
            scoped.append(candidate)
    if not scoped:
        if not source_revision:
            return ("no-read-evidence", [])
        return ("true-zero", [])
    return ("ok", scoped)


def _candidate_projection_store(visual_candidates: object) -> dict[tuple[str, str], object]:
    """Index validated compatibility records for by-reference filter results.

    The planner resolves each by-reference eligible entry through this
    store, fingerprint-verifying the record before selection. Only
    validated records are indexed; the filter's own classification decides
    eligibility, never this store.
    """
    store: dict[tuple[str, str], object] = {}
    if type(visual_candidates) is not list:
        return store
    for candidate in visual_candidates:
        result = validate_visual_asset_compatibility_evidence(candidate)
        if result.status is ValidationStatus.VALID and result.record is not None:
            store[(result.record.record_id, result.record.fingerprint)] = (
                result.record
            )
    return store


@dataclass(frozen=True)
class GovernedVisualReusePlan:
    """Retain upstream governed evidence and expose only runtime coordination state."""

    outcome: str
    final_production_blocked: bool
    selected_asset_ids: tuple[str, ...]
    material_requirement_result: ValidationResult
    visual_needs_result: ValidationResult | None
    artifact_reuse_result: ValidationResult | None = None
    candidate_filter_result: ValidationResult | None = None
    cohesive_visual_plan_result: ValidationResult | None = None
    teacher_decision_outcomes: tuple[dict[str, Any], ...] = ()

    @property
    def image_gap_briefs(self) -> tuple[dict[str, Any], ...]:
        """Return unchanged image-gap briefs from the governed cohesive-plan record."""
        result = self.cohesive_visual_plan_result
        if result is None or result.record is None:
            return ()
        payload = result.record.to_dict()
        return tuple(payload["image_gap_briefs"])


def _eligible_asset_content_identities(
    scoped_candidates: list[object],
) -> dict[str, dict[str, Any] | None]:
    """Map each scoped asset ID to its canonical content identity (#3256).

    Assets without a recorded content fingerprint map to None (unverifiable
    at decision-use time, which fails closed per the decision contract).
    """
    identities: dict[str, dict[str, Any] | None] = {}
    for candidate in scoped_candidates:
        if not isinstance(candidate, dict):
            continue
        evidence = candidate.get("compatibility_evidence")
        if not isinstance(evidence, dict):
            continue
        asset_reference = evidence.get("asset_reference")
        if not isinstance(asset_reference, dict):
            continue
        asset_id = asset_reference.get("asset_id")
        if not isinstance(asset_id, str) or not asset_id:
            continue
        fingerprint = asset_reference.get("content_fingerprint")
        try:
            identities[asset_id] = (
                content_identity_from_fingerprint(fingerprint).copy()
                if isinstance(fingerprint, str) and fingerprint
                else None
            )
        except (ValueError, TypeError):
            identities[asset_id] = None
    return identities


def _apply_teacher_decisions(
    cohesive_payload: dict[str, Any],
    teacher_decisions: tuple[object, ...],
    *,
    candidate_set_fingerprint: str,
    eligible_asset_ids: set[str],
    content_identities: dict[str, dict[str, Any] | None],
    source_revision: object,
) -> tuple[tuple[str, ...], tuple[dict[str, Any], ...], str | None]:
    """Honor valid teacher decisions per role; block roles with invalid ones.

    Returns ``(selected_asset_ids, decision_outcomes, blocked_reason)``.
    ``blocked_reason`` is None when no role was blocked. A blocked role's
    asset is excluded from the selection and the planner's pick is never
    substituted — the role stays blocked with its explicit reason code.
    Decisions for roles absent from the plan are recorded as not honored
    (``role-retired``) without blocking unrelated work.
    """
    assignments: list[dict[str, Any]] = []
    for key in ("required_role_assignments", "optional_role_assignments"):
        items = cohesive_payload.get(key, ())
        if isinstance(items, (list, tuple)):
            assignments.extend(item for item in items if isinstance(item, dict))
    role_order: list[str] = []
    role_asset: dict[str, str] = {}
    for assignment in assignments:
        role_id = assignment.get("role_id")
        selected = assignment.get("selected_candidate")
        if not isinstance(role_id, str):
            continue
        asset_reference = selected.get("asset_reference") if isinstance(selected, dict) else None
        asset_id = (
            asset_reference.get("asset_id")
            if isinstance(asset_reference, dict)
            else None
        )
        if role_id not in role_asset:
            role_order.append(role_id)
        if isinstance(asset_id, str) and asset_id:
            role_asset[role_id] = asset_id
    active_roles = set(role_order)

    outcomes: list[dict[str, Any]] = []
    blocked: dict[str, str] = {}
    for raw in teacher_decisions:
        if not isinstance(raw, dict):
            continue
        decision_id = raw.get("decision_id")
        role = raw.get("role")
        validity: DecisionValidity = evaluate_decision_validity(
            raw,
            candidate_set_fingerprint=candidate_set_fingerprint,
            eligible_asset_ids=eligible_asset_ids,
            current_content_identities=content_identities,
            source_revision=(
                source_revision if isinstance(source_revision, str) else None
            ),
            active_roles=active_roles,
        )
        selected_asset = raw.get("selected_asset")
        decision_asset_id = (
            selected_asset.get("asset_id")
            if isinstance(selected_asset, dict)
            else None
        )
        if validity.valid and isinstance(decision_asset_id, str) and decision_asset_id:
            if isinstance(role, str) and role in role_asset:
                role_asset[role] = decision_asset_id
            outcomes.append(
                {
                    "decision_id": decision_id,
                    "role": role,
                    "honored": True,
                    "reason_code": None,
                    "detail": None,
                    "asset_id": decision_asset_id,
                }
            )
        else:
            outcomes.append(
                {
                    "decision_id": decision_id,
                    "role": role,
                    "honored": False,
                    "reason_code": validity.reason_code,
                    "detail": validity.detail,
                    "asset_id": decision_asset_id,
                }
            )
            # A decision for a retired (absent) role has no role to block;
            # record it without blocking unrelated work.
            if (
                isinstance(role, str)
                and role in active_roles
                and validity.reason_code != "role-retired"
            ):
                blocked[role] = validity.reason_code or "invalid"

    ordered_ids: list[str] = []
    for role_id in role_order:
        if role_id in blocked:
            continue
        asset_id = role_asset.get(role_id)
        if asset_id and asset_id not in ordered_ids:
            ordered_ids.append(asset_id)
    blocked_reason = next(iter(blocked.values()), None)
    return tuple(ordered_ids), tuple(outcomes), blocked_reason


def plan_governed_visual_reuse(
    requirement: object,
    *,
    artifact_manifests: object = None,
    visual_candidates: object = None,
    source_revision: object = None,
    changed_dependency_keys: object = None,
    impact_map: object = None,
    current_asset_evidence: object = None,
    teacher_decisions: tuple[object, ...] = (),
) -> GovernedVisualReusePlan:
    """Compose existing public contracts without adding selection or safety policy.

    ``teacher_decisions`` accepts governed teacher visual-decision records
    (see ``instructional_workflow_contracts.teacher_visual_decision``). A
    valid decision's asset replaces the planner's selection for its role; an
    invalid decision blocks its role with an explicit reason code — the
    planner never silently substitutes its own pick.
    """
    requirement_result = validate_material_requirement(requirement)
    if requirement_result.status is not ValidationStatus.VALID:
        return GovernedVisualReusePlan(
            outcome="invalid-material-requirement",
            final_production_blocked=True,
            selected_asset_ids=(),
            material_requirement_result=requirement_result,
            visual_needs_result=None,
        )

    visual_needs_result = plan_visual_needs(requirement_result)
    if visual_needs_result.status is not ValidationStatus.VALID:
        return GovernedVisualReusePlan(
            outcome="manual-review-required",
            final_production_blocked=True,
            selected_asset_ids=(),
            material_requirement_result=requirement_result,
            visual_needs_result=visual_needs_result,
        )

    assert visual_needs_result.record is not None
    visual_needs_payload = visual_needs_result.record.to_dict()
    if visual_needs_payload["outcome"] == "no-visual-needed":
        return GovernedVisualReusePlan(
            outcome="no-visual-needed",
            final_production_blocked=False,
            selected_asset_ids=(),
            material_requirement_result=requirement_result,
            visual_needs_result=visual_needs_result,
        )

    artifact_reuse_result = plan_instructional_artifact_reuse(
        requirement_result,
        [] if artifact_manifests is None else artifact_manifests,
        changed_dependency_keys=(
            [] if changed_dependency_keys is None else changed_dependency_keys
        ),
        impact_map={} if impact_map is None else impact_map,
    )
    if artifact_reuse_result.status is not ValidationStatus.VALID:
        return GovernedVisualReusePlan(
            outcome="manual-review-required",
            final_production_blocked=True,
            selected_asset_ids=(),
            material_requirement_result=requirement_result,
            visual_needs_result=visual_needs_result,
            artifact_reuse_result=artifact_reuse_result,
        )

    scope_state, scoped_candidates = _scope_candidates_to_current_assets(
        None if visual_candidates is None else visual_candidates,
        current_asset_evidence,
        source_revision,
    )
    # Canonical outcome-code registry (#3248): scoping failures are distinct
    # non-absence states and never become visual gaps.
    if scope_state == "no-evidence":
        return GovernedVisualReusePlan(
            outcome="empty-evidence",
            final_production_blocked=True,
            selected_asset_ids=(),
            material_requirement_result=requirement_result,
            visual_needs_result=visual_needs_result,
            artifact_reuse_result=artifact_reuse_result,
        )
    if scope_state == "malformed":
        return GovernedVisualReusePlan(
            outcome="incomplete-evidence",
            final_production_blocked=True,
            selected_asset_ids=(),
            material_requirement_result=requirement_result,
            visual_needs_result=visual_needs_result,
            artifact_reuse_result=artifact_reuse_result,
        )
    if scope_state == "identity-conflict":
        return GovernedVisualReusePlan(
            outcome="identity-conflict",
            final_production_blocked=True,
            selected_asset_ids=(),
            material_requirement_result=requirement_result,
            visual_needs_result=visual_needs_result,
            artifact_reuse_result=artifact_reuse_result,
        )
    if scope_state == "no-read-evidence":
        return GovernedVisualReusePlan(
            outcome="retrieval-failure",
            final_production_blocked=True,
            selected_asset_ids=(),
            material_requirement_result=requirement_result,
            visual_needs_result=visual_needs_result,
            artifact_reuse_result=artifact_reuse_result,
        )
    candidate_filter_result = filter_approved_visual_candidates(
        visual_needs_result,
        scoped_candidates,
        source_revision=source_revision,
        contract_version=VISUAL_CANDIDATES_V2_CONTRACT_ID,
    )
    if candidate_filter_result.status is not ValidationStatus.VALID:
        return GovernedVisualReusePlan(
            # #3255: a capacity failure is reported as capacity, never as
            # manual review. Every other filter failure keeps the existing
            # manual-review-required outcome.
            outcome=(
                "capacity-exceeded"
                if "capacity-exceeded" in candidate_filter_result.reason_codes
                else "manual-review-required"
            ),
            final_production_blocked=True,
            selected_asset_ids=(),
            material_requirement_result=requirement_result,
            visual_needs_result=visual_needs_result,
            artifact_reuse_result=artifact_reuse_result,
            candidate_filter_result=candidate_filter_result,
        )

    cohesive_result = plan_cohesive_visual_set(
        visual_needs_result,
        candidate_filter_result,
        candidate_projections=_candidate_projection_store(scoped_candidates),
    )
    if cohesive_result.status is not ValidationStatus.VALID or cohesive_result.record is None:
        return GovernedVisualReusePlan(
            outcome=(
                "capacity-exceeded"
                if "capacity-exceeded" in cohesive_result.reason_codes
                else "manual-review-required"
            ),
            final_production_blocked=True,
            selected_asset_ids=(),
            material_requirement_result=requirement_result,
            visual_needs_result=visual_needs_result,
            artifact_reuse_result=artifact_reuse_result,
            candidate_filter_result=candidate_filter_result,
            cohesive_visual_plan_result=cohesive_result,
        )

    cohesive_payload = cohesive_result.record.to_dict()
    selected_asset_ids = tuple(
        item["asset_reference"]["asset_id"]
        for item in cohesive_payload["selected_candidates"]
    )
    if cohesive_payload["image_gap_briefs"]:
        # Proven-absence briefs exist: the only state that may block on a gap.
        return GovernedVisualReusePlan(
            outcome="visual-gap-blocked",
            final_production_blocked=True,
            selected_asset_ids=selected_asset_ids,
            material_requirement_result=requirement_result,
            visual_needs_result=visual_needs_result,
            artifact_reuse_result=artifact_reuse_result,
            candidate_filter_result=candidate_filter_result,
            cohesive_visual_plan_result=cohesive_result,
        )
    if cohesive_payload["unfilled_required_roles"]:
        # Required roles went unfilled for non-absence reasons (the per-role
        # outcome codes live on the plan record): blocked, but not a gap.
        return GovernedVisualReusePlan(
            outcome="visual-assignment-blocked",
            final_production_blocked=True,
            selected_asset_ids=selected_asset_ids,
            material_requirement_result=requirement_result,
            visual_needs_result=visual_needs_result,
            artifact_reuse_result=artifact_reuse_result,
            candidate_filter_result=candidate_filter_result,
            cohesive_visual_plan_result=cohesive_result,
        )

    # #3252: honor valid teacher decisions per role; an invalid decision
    # blocks its role with an explicit reason code instead of silently
    # falling back to the planner's pick.
    decision_outcomes: tuple[dict[str, Any], ...] = ()
    if teacher_decisions:
        scoped_fingerprint = canonical_candidate_set_fingerprint(scoped_candidates)
        scoped_identities = _eligible_asset_content_identities(scoped_candidates)
        selected_asset_ids, decision_outcomes, blocked_reason = _apply_teacher_decisions(
            cohesive_payload,
            tuple(teacher_decisions),
            candidate_set_fingerprint=scoped_fingerprint,
            eligible_asset_ids=set(scoped_identities),
            content_identities=scoped_identities,
            source_revision=source_revision,
        )
        if blocked_reason is not None:
            return GovernedVisualReusePlan(
                outcome="teacher-decision-invalidated",
                final_production_blocked=True,
                selected_asset_ids=selected_asset_ids,
                material_requirement_result=requirement_result,
                visual_needs_result=visual_needs_result,
                artifact_reuse_result=artifact_reuse_result,
                candidate_filter_result=candidate_filter_result,
                cohesive_visual_plan_result=cohesive_result,
                teacher_decision_outcomes=decision_outcomes,
            )

    return GovernedVisualReusePlan(
        outcome="visuals-ready",
        final_production_blocked=False,
        selected_asset_ids=selected_asset_ids,
        material_requirement_result=requirement_result,
        visual_needs_result=visual_needs_result,
        artifact_reuse_result=artifact_reuse_result,
        candidate_filter_result=candidate_filter_result,
        cohesive_visual_plan_result=cohesive_result,
        teacher_decision_outcomes=decision_outcomes,
    )
