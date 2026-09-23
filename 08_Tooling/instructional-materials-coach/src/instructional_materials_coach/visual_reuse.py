"""Pure orchestration for governed visual reuse before classroom artifact writes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from instructional_workflow_contracts import ValidationResult, ValidationStatus
from instructional_workflow_contracts.cohesive_visual_plan import plan_cohesive_visual_set
from instructional_workflow_contracts.material_requirement import validate_material_requirement
from instructional_workflow_contracts.reuse_planner import plan_instructional_artifact_reuse
from instructional_workflow_contracts.visual_asset_candidates import (
    V2_CONTRACT_ID as VISUAL_CANDIDATES_V2_CONTRACT_ID,
    filter_approved_visual_candidates,
)
from instructional_workflow_contracts.visual_needs import plan_visual_needs


def _scope_candidates_to_current_assets(
    visual_candidates: object,
    current_asset_evidence: object,
) -> object:
    """Constrain supplied governed candidates to exact current-unit asset identity.

    The caller may omit current asset evidence for existing offline/planner-only
    uses. When current evidence is supplied, only candidates whose existing
    Asset ID + Visual Asset Library page ID + Drive file ID tuple is present in
    that relation-first evidence can reach the existing candidate filter.
    """
    if current_asset_evidence is None:
        return visual_candidates
    if type(visual_candidates) is not list or type(current_asset_evidence) is not list:
        return []

    admitted: set[tuple[str, str, str]] = set()
    for item in current_asset_evidence:
        if type(item) is not dict:
            continue
        reference = item.get("library_reference")
        if type(reference) is not dict:
            continue
        asset_id = item.get("asset_id")
        page_id = reference.get("page_id")
        drive_file_id = reference.get("drive_file_id")
        if all(isinstance(value, str) and value for value in (asset_id, page_id, drive_file_id)):
            admitted.add((asset_id, page_id, drive_file_id))

    scoped: list[object] = []
    for candidate in visual_candidates:
        if type(candidate) is not dict:
            continue
        evidence = candidate.get("compatibility_evidence")
        if type(evidence) is not dict:
            continue
        asset_reference = evidence.get("asset_reference")
        library_reference = evidence.get("library_reference")
        if type(asset_reference) is not dict or type(library_reference) is not dict:
            continue
        identity = (
            asset_reference.get("asset_id"),
            library_reference.get("page_id"),
            library_reference.get("drive_file_id"),
        )
        if identity in admitted:
            scoped.append(candidate)
    return scoped


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

    @property
    def image_gap_briefs(self) -> tuple[dict[str, Any], ...]:
        """Return unchanged image-gap briefs from the governed cohesive-plan record."""
        result = self.cohesive_visual_plan_result
        if result is None or result.record is None:
            return ()
        payload = result.record.to_dict()
        return tuple(payload["image_gap_briefs"])


def plan_governed_visual_reuse(
    requirement: object,
    *,
    artifact_manifests: object = None,
    visual_candidates: object = None,
    source_revision: object = None,
    changed_dependency_keys: object = None,
    impact_map: object = None,
    current_asset_evidence: object = None,
) -> GovernedVisualReusePlan:
    """Compose existing public contracts without adding selection or safety policy."""
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

    scoped_candidates = _scope_candidates_to_current_assets(
        [] if visual_candidates is None else visual_candidates,
        current_asset_evidence,
    )
    candidate_filter_result = filter_approved_visual_candidates(
        visual_needs_result,
        scoped_candidates,
        source_revision=source_revision,
        contract_version=VISUAL_CANDIDATES_V2_CONTRACT_ID,
    )
    if candidate_filter_result.status is not ValidationStatus.VALID:
        return GovernedVisualReusePlan(
            outcome="manual-review-required",
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
    )
    if cohesive_result.status is not ValidationStatus.VALID or cohesive_result.record is None:
        return GovernedVisualReusePlan(
            outcome="manual-review-required",
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
    if cohesive_payload["unfilled_required_roles"]:
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

    return GovernedVisualReusePlan(
        outcome="visuals-ready",
        final_production_blocked=False,
        selected_asset_ids=selected_asset_ids,
        material_requirement_result=requirement_result,
        visual_needs_result=visual_needs_result,
        artifact_reuse_result=artifact_reuse_result,
        candidate_filter_result=candidate_filter_result,
        cohesive_visual_plan_result=cohesive_result,
    )
