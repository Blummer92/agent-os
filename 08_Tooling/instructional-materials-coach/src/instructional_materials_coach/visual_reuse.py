"""Pure orchestration for governed visual reuse before classroom artifact writes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from instructional_workflow_contracts import ValidationResult, ValidationStatus
from instructional_workflow_contracts.asset_content_identity import (
    content_identity_from_fingerprint,
)
from instructional_workflow_contracts.cohesive_visual_plan import (
    plan_cohesive_visual_set,
    _assignment as _governed_assignment,
    _asset_key as _governed_asset_key,
    _role_rejection_reasons as _governed_role_rejections,
    _set_rejection_reasons as _governed_set_rejections,
    _resolve_eligible_candidates as _governed_eligible_candidates,
)
from instructional_workflow_contracts.material_requirement import validate_material_requirement
from instructional_workflow_contracts.reuse_planner import plan_instructional_artifact_reuse
from instructional_workflow_contracts.teacher_visual_decision import (
    DecisionValidity,
    canonical_candidate_set_fingerprint,
    canonical_decision_slot_id,
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
    # Binding-preserving representation of teacher-resolved choices; unlike
    # transport asset IDs, shared asset IDs occur once per role/slot binding.
    teacher_selected_role_slot_bindings: tuple[dict[str, str], ...] = ()
    # Derived from the same governed candidate/role policy; source #944 stays immutable.
    effective_role_assignments: tuple[dict[str, Any], ...] = ()
    teacher_decision_block_reason: str | None = None

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
) -> tuple[tuple[str, ...], tuple[dict[str, Any], ...], str | None,
           tuple[dict[str, str], ...]]:
    """Resolve each choice against an exact (role_id, slot_id) binding.

    The selected asset-ID tuple is a deduplicated transport list; the fourth
    return value preserves per-slot multiplicity for downstream consumers.
    Invalid choices block only their exact binding, never a sibling slot.
    Historical superseded/invalidated records cannot overwrite active ones.
    """
    assignments: list[dict[str, Any]] = []
    for field in ("required_role_assignments", "optional_role_assignments"):
        values = cohesive_payload.get(field, ())
        if isinstance(values, (list, tuple)):
            assignments.extend(x for x in values if isinstance(x, dict))

    binding_order: list[tuple[str, str]] = []
    binding_assets: dict[tuple[str, str], str | None] = {}
    ambiguous = False
    for item in assignments:
        role_id = item.get("role_id")
        slot_id = item.get("slot_id", "0")  # governed implicit-slot legacy
        if (not isinstance(role_id, str) or not role_id
                or type(slot_id) is not str
                or canonical_decision_slot_id(slot_id) != slot_id):
            ambiguous = True
            continue
        key = (role_id, slot_id)
        if key in binding_assets:
            ambiguous = True
            continue
        selected = item.get("selected_candidate")
        asset_ref = selected.get("asset_reference") if isinstance(selected, dict) else None
        asset_id = asset_ref.get("asset_id") if isinstance(asset_ref, dict) else None
        binding_order.append(key)
        binding_assets[key] = asset_id if isinstance(asset_id, str) and asset_id else None

    active_roles = {role for role, _ in binding_order}
    # Append-only history: the newest timestamp wins, as in active_decision_for.
    # Distinct records at the same latest timestamp are ambiguous and fail closed.
    active_by_binding: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for raw in teacher_decisions:
        if not isinstance(raw, dict) or raw.get("status") != "active":
            continue
        role = raw.get("role")
        slot = canonical_decision_slot_id(raw.get("slot"))
        if isinstance(role, str) and slot is not None:
            active_by_binding.setdefault((role, slot), []).append(raw)
    latest_by_binding: dict[tuple[str, str], dict[str, Any]] = {}
    conflicting: set[tuple[str, str]] = set()
    for key, records in active_by_binding.items():
        latest_time = max(str(record.get("decided_at", "")) for record in records)
        latest = [record for record in records
                  if str(record.get("decided_at", "")) == latest_time]
        if any(record != latest[0] for record in latest[1:]):
            conflicting.add(key)
        else:
            latest_by_binding[key] = latest[0]

    outcomes: list[dict[str, Any]] = []
    blocked: dict[tuple[str, str], str] = {}
    for raw in teacher_decisions:
        if not isinstance(raw, dict):
            continue
        role = raw.get("role")
        slot_id = canonical_decision_slot_id(raw.get("slot"))
        key = (role, slot_id)
        selected = raw.get("selected_asset")
        asset_id = selected.get("asset_id") if isinstance(selected, dict) else None
        status = raw.get("status")
        reason: str | None = None
        detail: str | None = None
        if status != "active":
            reason = "superseded" if status == "superseded" else "decision-inactive"
            detail = "historical/inactive decisions never authorize a slot"
        elif role not in active_roles:
            reason = "role-retired"
            detail = "role is absent from the current visual plan"
        elif slot_id is None:
            reason = "slot-binding-invalid"
            detail = "decision has no valid governed slot identifier"
        elif key not in binding_assets:
            reason = "slot-binding-missing"
            detail = "decision's exact role/slot binding is absent from the current plan"
        elif ambiguous:
            reason = "ambiguous-plan-binding"
            detail = "current visual plan contains ambiguous role/slot assignments"
        elif key in conflicting:
            reason = "conflicting-active-decisions"
            detail = "distinct active decisions share the latest timestamp"
        elif raw != latest_by_binding.get(key):
            reason = "superseded-by-later"
            detail = "a newer active decision owns this role/slot"
        else:
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
            if not validity.valid:
                reason, detail = validity.reason_code, validity.detail
            elif not isinstance(asset_id, str) or not asset_id:
                reason, detail = "decision-asset-invalid", "selected asset ID missing"

        honored = reason is None
        if honored:
            binding_assets[key] = asset_id
        elif status == "active" and role in active_roles and reason != "superseded-by-later":
            blocked[key] = reason or "decision-invalid"
        outcomes.append({
            "decision_id": raw.get("decision_id"), "role": role,
            "slot_id": slot_id, "honored": honored,
            "reason_code": reason, "detail": detail, "asset_id": asset_id,
        })

    if ambiguous:
        # No ambiguous plan can authorize completion, even without decisions.
        return (), tuple(outcomes), "ambiguous-plan-binding", ()

    exact_bindings: list[dict[str, str]] = []
    ordered_ids: list[str] = []
    for key in binding_order:
        if key in blocked:
            continue
        asset_id = binding_assets[key]
        if asset_id:
            exact_bindings.append({
                "role_id": key[0], "slot_id": key[1], "asset_id": asset_id,
            })
            if asset_id not in ordered_ids:
                ordered_ids.append(asset_id)
    blocked_reason = next(iter(blocked.values()), None)
    return tuple(ordered_ids), tuple(outcomes), blocked_reason, tuple(exact_bindings)


def _materialize_effective_assignments(
    cohesive_payload: dict[str, Any],
    resolved_bindings: tuple[dict[str, str], ...],
    *,
    scoped_candidates: list[object],
    candidate_filter_result: ValidationResult,
    visual_needs_result: ValidationResult,
) -> tuple[dict[str, Any], ...]:
    """Recheck each teacher-resolved binding against governed role/set policy."""
    filter_record = candidate_filter_result.record
    needs_record = visual_needs_result.record
    if filter_record is None or needs_record is None:
        raise ValueError("teacher-resolved-source-evidence-missing")
    filtered = filter_record.to_dict()
    needs = needs_record.to_dict()
    eligible = _governed_eligible_candidates(
        list(filtered["eligible"]),
        transport=filtered.get("projection_transport"),
        candidate_projections=_candidate_projection_store(scoped_candidates),
        candidate_contract_version=filter_record.contract_version,
    )
    candidates: dict[str, dict[str, Any]] = {}
    for candidate in eligible:
        asset_id = candidate["asset_reference"]["asset_id"]
        if asset_id in candidates and candidates[asset_id] != candidate:
            raise ValueError("teacher-selected-asset-ambiguous")
        candidates[asset_id] = candidate
    roles = {role["role_id"]: role
             for role in [*needs["required_roles"], *needs["optional_roles"]]}
    binding_assets = {(b["role_id"], b["slot_id"]): b["asset_id"]
                      for b in resolved_bindings}
    if len(binding_assets) != len(resolved_bindings):
        raise ValueError("teacher-resolved-binding-ambiguous")

    effective: list[dict[str, Any]] = []
    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    used_assets: set[tuple[str, str, str]] = set()
    for field in ("required_role_assignments", "optional_role_assignments"):
        for original in cohesive_payload[field]:
            role_id = original["role_id"]
            slot_id = original.get("slot_id", "0")
            key = (role_id, slot_id)
            if key in seen or key not in binding_assets or role_id not in roles:
                raise ValueError("teacher-resolved-binding-missing-or-duplicate")
            seen.add(key)
            asset_id = binding_assets[key]
            candidate = candidates.get(asset_id)
            if candidate is None:
                raise ValueError(
                    "teacher-selected-candidate-not-filter-eligible:"
                    f" asset={asset_id} eligible={','.join(sorted(candidates))}"
                )
            role = roles[role_id]
            reasons = _governed_role_rejections(
                role, candidate, material_type=needs["material_type"],
            )
            if reasons:
                raise ValueError("teacher-selected-role-incompatible")
            if _governed_set_rejections(
                candidate, selected=selected, used_asset_keys=used_assets,
                role_reasons=reasons,
            ):
                raise ValueError("teacher-selected-set-incompatible")
            chosen_by_planner = original["selected_candidate"]
            if chosen_by_planner["asset_reference"]["asset_id"] == asset_id:
                if chosen_by_planner.get("compatibility_fingerprint") != candidate["fingerprint"]:
                    raise ValueError("teacher-selected-candidate-identity-conflict")
                effective.append(original)
            else:
                effective.append(_governed_assignment(
                    role, candidate,
                    requirement_state=original["requirement_state"],
                    slot_id=slot_id,
                ))
            selected.append(candidate)
            used_assets.add(_governed_asset_key(candidate))
    if seen != set(binding_assets):
        raise ValueError("teacher-resolved-binding-count-mismatch")
    if len(used_assets) > needs["maximum_visual_count"]:
        raise ValueError("teacher-resolved-asset-cap-exceeded")
    return tuple(effective)


def effective_visual_payload(visual_plan: object) -> dict[str, Any]:
    """One consumer view; original validated cohesive-plan evidence is unchanged."""
    result = getattr(visual_plan, "cohesive_visual_plan_result", None)
    if result is None or getattr(result, "record", None) is None:
        raise ValueError("governed-visual-plan-missing")
    payload = result.record.to_dict()
    outcomes = getattr(visual_plan, "teacher_decision_outcomes", ())
    if not outcomes:
        return payload
    if getattr(visual_plan, "final_production_blocked", True):
        raise ValueError("teacher-visual-plan-blocked")
    effective = getattr(visual_plan, "effective_role_assignments", ())
    if not effective:
        raise ValueError("teacher-resolved-assignments-missing")
    required = [x for x in effective if x["requirement_state"] == "required"]
    optional = [x for x in effective if x["requirement_state"] == "optional"]
    original_keys = {(x["role_id"], x.get("slot_id", "0"))
                     for kind in ("required_role_assignments", "optional_role_assignments")
                     for x in payload[kind]}
    effective_keys = [(x["role_id"], x.get("slot_id", "0")) for x in effective]
    if (len(effective_keys) != len(set(effective_keys))
            or set(effective_keys) != original_keys
            or len(required) != len(payload["required_role_assignments"])
            or len(optional) != len(payload["optional_role_assignments"])):
        raise ValueError("teacher-resolved-assignments-mismatched")
    payload["required_role_assignments"] = required
    payload["optional_role_assignments"] = optional
    payload["selected_candidates"] = [x["selected_candidate"] for x in effective]
    actual_ids = {x["selected_candidate"]["asset_reference"]["asset_id"] for x in effective}
    if actual_ids != set(getattr(visual_plan, "selected_asset_ids", ())):
        raise ValueError("teacher-resolved-asset-selection-mismatch")
    return payload


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
    teacher_selected_role_slot_bindings: tuple[dict[str, str], ...] = ()
    effective_role_assignments: tuple[dict[str, Any], ...] = ()
    if teacher_decisions:
        scoped_fingerprint = canonical_candidate_set_fingerprint(scoped_candidates)
        scoped_identities = _eligible_asset_content_identities(scoped_candidates)
        (selected_asset_ids, decision_outcomes, blocked_reason,
         teacher_selected_role_slot_bindings) = _apply_teacher_decisions(
            cohesive_payload,
            tuple(teacher_decisions),
            candidate_set_fingerprint=scoped_fingerprint,
            eligible_asset_ids=set(scoped_identities),
            content_identities=scoped_identities,
            source_revision=source_revision,
        )
        if blocked_reason is None:
            try:
                effective_role_assignments = _materialize_effective_assignments(
                    cohesive_payload, teacher_selected_role_slot_bindings,
                    scoped_candidates=scoped_candidates,
                    candidate_filter_result=candidate_filter_result,
                    visual_needs_result=visual_needs_result,
                )
            except (KeyError, TypeError, ValueError) as exc:
                blocked_reason = str(exc)
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
                teacher_selected_role_slot_bindings=teacher_selected_role_slot_bindings,
                effective_role_assignments=effective_role_assignments,
                teacher_decision_block_reason=blocked_reason,
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
        teacher_selected_role_slot_bindings=teacher_selected_role_slot_bindings,
        effective_role_assignments=effective_role_assignments,
    )
