"""#3672 Phase 2/5: governed visual-reuse provenance reconciliation.

The candidate envelope's library title is a *claim*. The authoritative
title is the one the governed Notion projection carried into
current-asset evidence for the exact (Asset ID, Notion page ID, Drive
file ID) identity. Contradiction fails closed as ``title-conflict``; a
claim with no authoritative counterpart fails closed as
``title-unverifiable``. Neither is a visual gap, and a caller-provided
``verified`` flag is never read as provenance.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import instructional_materials_coach.visual_reuse as visual_reuse
from instructional_workflow_contracts import ValidationStatus
from instructional_workflow_contracts.artifact_manifest import (
    artifact_manifest_idempotency_key,
    artifact_manifest_source_fingerprint,
    validate_artifact_manifest,
)
from instructional_workflow_contracts.asset_content_identity import (
    content_identity_from_fingerprint,
)
from instructional_workflow_contracts.material_requirement import (
    material_requirement_source_fingerprint,
)
from instructional_workflow_contracts.teacher_visual_decision import (
    canonical_candidate_set_fingerprint,
)
from instructional_workflow_contracts.visual_asset_compatibility import (
    validate_visual_asset_compatibility_evidence,
)
from instructional_workflow_contracts.visual_needs import plan_visual_needs

ROOT = Path(__file__).parents[3]
FIXTURES = ROOT / "tests" / "fixtures" / "instructional_workflow_contracts"
REVISION = "3672-snapshot"
EXACT_TITLE = "Rule of Thirds - Off Center Subject"
RELATED_TITLE = "The Rule and the Thirds of Composition"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _hex(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def content_fp(index: int) -> str:
    return _hex(f"asset-content-{index:03d}")


def build_candidate(index: int, title, *, stale: bool = False,
                    approved_state: str = "approved") -> dict:
    envelope = copy.deepcopy(_fixture("valid_visual_asset_compatibility_v2.json"))
    asset_id = f"asset-{index:03d}"
    stable_ref = f"asset-ref-{index:03d}"
    page_id = f"page-{index:03d}"
    drive_file_id = f"drive-file-{index:03d}"

    manifest = envelope["artifact_manifest"]
    manifest["identity"]["manifest_id"] = f"manifest-{index:03d}"
    manifest["external_identity"]["file_id"] = drive_file_id
    manifest["external_identity"]["exact_reference"] = f"drive:{drive_file_id}"
    manifest["external_identity"]["web_view_link"] = f"https://example.invalid/{drive_file_id}"
    asset = manifest["assets"][0]
    asset["asset_id"] = asset_id
    asset["stable_ref"] = stable_ref
    asset["content_fingerprint"] = content_fp(index)
    manifest["operation"]["idempotency_key"] = artifact_manifest_idempotency_key(manifest)
    manifest["custom_properties"]["manifest_id"] = f"manifest-{index:03d}"
    manifest["custom_properties"]["idempotency_key"] = manifest["operation"]["idempotency_key"]
    manifest["identity"]["source_fingerprint"] = artifact_manifest_source_fingerprint(manifest)
    manifest_result = validate_artifact_manifest(manifest)
    assert manifest_result.status is ValidationStatus.VALID
    manifest_record = manifest_result.record

    library = envelope["library_record"]
    library["page_id"] = page_id
    library["drive_file_id"] = drive_file_id
    library["page_url"] = f"https://example.invalid/{page_id}"
    library["drive_url"] = f"https://example.invalid/{drive_file_id}"
    library["asset_title"] = title

    evidence = envelope["compatibility_evidence"]
    evidence["manifest_reference"] = {
        "manifest_id": manifest_record.record_id,
        "record_revision": manifest_record.record_revision,
        "fingerprint": manifest_record.fingerprint,
        "verified_at": manifest["identity"]["verified_at"],
        "external_file_id": drive_file_id,
    }
    evidence["freshness"]["manifest_record_revision"] = manifest_record.record_revision
    evidence["freshness"]["manifest_fingerprint"] = manifest_record.fingerprint
    evidence["freshness"]["manifest_verified_at"] = manifest["identity"]["verified_at"]
    evidence["freshness"]["stale"] = stale
    evidence["asset_reference"] = {
        "asset_id": asset_id,
        "stable_ref": stable_ref,
        "content_fingerprint": content_fp(index),
    }
    evidence["library_reference"] = {"page_id": page_id, "drive_file_id": drive_file_id}
    evidence["approved_use"]["state"] = approved_state

    result = validate_visual_asset_compatibility_evidence(envelope)
    assert result.record is not None, result.reason_codes
    return envelope


def evidence_for(index: int, title, **extra) -> dict:
    item = {
        "asset_id": f"asset-{index:03d}",
        "library_reference": {
            "page_id": f"page-{index:03d}",
            "drive_file_id": f"drive-file-{index:03d}",
        },
    }
    if title is not None:
        item["asset_title"] = title
    item.update(extra)
    return item


def concept_requirement() -> dict:
    requirement = _fixture("valid_material_requirement_v2.json")
    requirement["visual_direction"]["roles"][0]["concept"] = "Rule of Thirds"
    requirement["identity"]["source_fingerprint"] = (
        material_requirement_source_fingerprint(requirement)
    )
    return requirement


def run_plan(candidates, evidence, *, requirement=None, teacher_decisions=()):
    return visual_reuse.plan_governed_visual_reuse(
        requirement if requirement is not None else concept_requirement(),
        artifact_manifests=[_fixture("valid_artifact_manifest.json")],
        visual_candidates=candidates,
        source_revision=REVISION,
        changed_dependency_keys=[],
        impact_map={},
        current_asset_evidence=evidence,
        teacher_decisions=teacher_decisions,
    )


# --- Provenance reconciliation -------------------------------------------


def test_matching_authoritative_title_admits_and_selects() -> None:
    plan = run_plan([build_candidate(1, EXACT_TITLE)], [evidence_for(1, EXACT_TITLE)])
    assert plan.outcome == "visuals-ready"
    assert plan.final_production_blocked is False
    assert plan.selected_asset_ids == ("asset-001",)
    assert plan.image_gap_briefs == ()


def test_forged_candidate_title_claiming_the_concept_is_rejected() -> None:
    # The governed record's real title is unrelated; the candidate envelope
    # forges the exact concept title. Fingerprint self-consistency of the
    # forged envelope does not save it: provenance is the Notion record.
    plan = run_plan(
        [build_candidate(1, EXACT_TITLE)],
        [evidence_for(1, "Leading Lines - The Governed Title")],
    )
    assert plan.outcome == "title-conflict"
    assert plan.final_production_blocked is True
    assert plan.selected_asset_ids == ()
    assert plan.image_gap_briefs == ()


def test_candidate_title_contradicting_notion_evidence_is_rejected() -> None:
    plan = run_plan(
        [build_candidate(1, "Leading Lines - Forged Title")],
        [evidence_for(1, EXACT_TITLE)],
    )
    assert plan.outcome == "title-conflict"
    assert plan.final_production_blocked is True
    assert plan.selected_asset_ids == ()
    assert plan.image_gap_briefs == ()


def test_title_claim_without_authoritative_title_is_unverifiable() -> None:
    plan = run_plan([build_candidate(1, EXACT_TITLE)], [evidence_for(1, None)])
    assert plan.outcome == "title-unverifiable"
    assert plan.final_production_blocked is True
    assert plan.selected_asset_ids == ()
    # Missing provenance is never proven absence.
    assert plan.image_gap_briefs == ()


def test_caller_verified_flag_is_never_provenance() -> None:
    # A verified=True flag on the evidence item does not substitute for the
    # governed title field.
    plan = run_plan(
        [build_candidate(1, EXACT_TITLE)],
        [evidence_for(1, None, verified=True)],
    )
    assert plan.outcome == "title-unverifiable"
    assert plan.selected_asset_ids == ()
    # And with the real governed title present, the flag changes nothing.
    plan = run_plan(
        [build_candidate(1, EXACT_TITLE)],
        [evidence_for(1, EXACT_TITLE, verified=True)],
    )
    assert plan.outcome == "visuals-ready"
    assert plan.selected_asset_ids == ("asset-001",)


def test_contradictory_authoritative_titles_fail_closed() -> None:
    evidence = [evidence_for(1, EXACT_TITLE), evidence_for(1, RELATED_TITLE)]
    plan = run_plan([build_candidate(1, EXACT_TITLE)], evidence)
    assert plan.outcome == "title-conflict"
    assert plan.selected_asset_ids == ()


# --- Identity mismatches fail closed (scope level + plan level) -----------


def _assert_identity_mismatch_excludes(evidence_item) -> None:
    candidate = build_candidate(1, EXACT_TITLE)
    state, scoped = visual_reuse._scope_candidates_to_current_assets(
        [candidate], [evidence_item], REVISION
    )
    assert scoped == []
    plan = run_plan([candidate], [evidence_item])
    assert plan.selected_asset_ids == ()
    assert plan.final_production_blocked is True


def test_asset_id_mismatch_fails_closed() -> None:
    item = evidence_for(1, EXACT_TITLE)
    item["asset_id"] = "asset-999"
    _assert_identity_mismatch_excludes(item)


def test_notion_page_id_mismatch_fails_closed() -> None:
    item = evidence_for(1, EXACT_TITLE)
    item["library_reference"]["page_id"] = "page-999"
    _assert_identity_mismatch_excludes(item)


def test_drive_file_id_mismatch_fails_closed() -> None:
    item = evidence_for(1, EXACT_TITLE)
    item["library_reference"]["drive_file_id"] = "drive-file-999"
    _assert_identity_mismatch_excludes(item)


# --- Stale / restricted / unlicensed evidence ------------------------------


def test_stale_source_evidence_is_escalated_not_selected() -> None:
    plan = run_plan(
        [build_candidate(1, EXACT_TITLE, stale=True)],
        [evidence_for(1, EXACT_TITLE)],
    )
    assert plan.outcome == "manual-review-required"
    assert plan.final_production_blocked is True
    assert plan.selected_asset_ids == ()


def test_restricted_image_with_perfect_title_match_remains_ineligible() -> None:
    plan = run_plan(
        [build_candidate(1, EXACT_TITLE, approved_state="denied")],
        [evidence_for(1, EXACT_TITLE)],
    )
    assert plan.outcome != "visuals-ready"
    assert plan.final_production_blocked is True
    assert plan.selected_asset_ids == ()


def test_missing_licensing_evidence_remains_blocking() -> None:
    plan = run_plan(
        [build_candidate(1, EXACT_TITLE, approved_state="pending")],
        [evidence_for(1, EXACT_TITLE)],
    )
    assert plan.outcome == "manual-review-required"
    assert plan.final_production_blocked is True
    assert plan.selected_asset_ids == ()


# --- Teacher overrides ------------------------------------------------------


def _role_id(requirement) -> str:
    needs = plan_visual_needs(requirement)
    assert needs.status is ValidationStatus.VALID
    return needs.record.to_dict()["required_roles"][0]["role_id"]


def _decision(requirement, candidates, *, role_id: str, revision: str = REVISION) -> dict:
    return {
        "contract_id": "teacher-visual-decision-v1",
        "decision_id": "decision-3672",
        "actor": "teacher",
        "decided_at": "2026-10-03T12:00:00Z",
        "requirement_id": requirement["identity"]["requirement_id"],
        "source_revision": revision,
        "role": role_id,
        "slot": 0,
        "selected_asset": {
            "asset_id": "asset-002",
            "provider_file_id": "drive-file-002",
            "content_identity": dict(content_identity_from_fingerprint(content_fp(2))),
            "revision_identity": "rev-1",
            "provenance": {"source": "teacher-choice-3672"},
        },
        "overridden_recommendation": "asset-001",
        "candidate_set_fingerprint": canonical_candidate_set_fingerprint(candidates),
        "scope": "unit",
        "invalidation_rule": "candidate-set-or-content-change",
        "status": "active",
    }


def _two_candidate_setup():
    requirement = concept_requirement()
    candidates = [build_candidate(1, EXACT_TITLE), build_candidate(2, RELATED_TITLE)]
    evidence = [evidence_for(1, EXACT_TITLE), evidence_for(2, RELATED_TITLE)]
    return requirement, candidates, evidence


def test_valid_teacher_override_remains_honored() -> None:
    requirement, candidates, evidence = _two_candidate_setup()
    decision = _decision(requirement, candidates, role_id=_role_id(requirement))
    plan = run_plan(candidates, evidence, requirement=requirement,
                    teacher_decisions=(decision,))
    assert plan.outcome == "visuals-ready"
    # The planner alone would pick the exact match (asset-001); the valid
    # teacher decision for the supported-related asset is honored instead.
    assert plan.selected_asset_ids == ("asset-002",)
    honored = [o for o in plan.teacher_decision_outcomes if o["decision_id"] == "decision-3672"]
    assert honored and honored[0]["honored"] is True


def test_invalidated_teacher_override_remains_blocking() -> None:
    requirement, candidates, evidence = _two_candidate_setup()
    # The decision was recorded against a different (stale) candidate set:
    # the governed candidate-set fingerprint no longer matches, so the
    # decision is invalidated, its role stays blocked, and the planner's
    # pick is never silently substituted. (Under the #3252 contract a
    # revision move alone does not invalidate when the fingerprint still
    # re-verifies the exact set; a changed set always does.)
    decision = _decision(requirement, candidates, role_id=_role_id(requirement),
                         revision="stale-snapshot")
    decision["candidate_set_fingerprint"] = canonical_candidate_set_fingerprint(
        candidates[:1]
    )
    plan = run_plan(candidates, evidence, requirement=requirement,
                    teacher_decisions=(decision,))
    assert plan.outcome == "teacher-decision-invalidated"
    assert plan.final_production_blocked is True
    assert "asset-002" not in plan.selected_asset_ids
    assert "asset-001" not in plan.selected_asset_ids
    outcomes = [o for o in plan.teacher_decision_outcomes if o["decision_id"] == "decision-3672"]
    assert outcomes and outcomes[0]["honored"] is False
    assert outcomes[0]["reason_code"]


# --- Preserved behavior -----------------------------------------------------


def test_no_concept_request_preserves_existing_selection() -> None:
    requirement = _fixture("valid_material_requirement_v2.json")
    plan = run_plan([build_candidate(1, EXACT_TITLE)], [evidence_for(1, EXACT_TITLE)],
                    requirement=requirement)
    assert plan.outcome == "visuals-ready"
    assert plan.selected_asset_ids == ("asset-001",)


def test_no_external_writes_in_governed_reuse() -> None:
    plan = run_plan([build_candidate(1, EXACT_TITLE)], [evidence_for(1, EXACT_TITLE)])
    assert plan.outcome == "visuals-ready"
    for result in (
        plan.material_requirement_result,
        plan.visual_needs_result,
        plan.artifact_reuse_result,
        plan.candidate_filter_result,
        plan.cohesive_visual_plan_result,
    ):
        assert result is not None and result.record is not None
        assert set(result.record.to_dict()["authority"].values()) == {False}


def test_image_gap_semantics_unchanged_for_proven_absence() -> None:
    # An identified read that admits zero candidates remains the only
    # proven-absence path, exactly as before #3672.
    plan = visual_reuse.plan_governed_visual_reuse(
        concept_requirement(),
        artifact_manifests=[_fixture("valid_artifact_manifest.json")],
        visual_candidates=[],
        source_revision=REVISION,
        changed_dependency_keys=[],
        impact_map={},
        current_asset_evidence=[],
    )
    assert plan.outcome == "visual-gap-blocked"
    assert len(plan.image_gap_briefs) == 1
    assert plan.image_gap_briefs[0]["absence_evidence"]["proven_absence"] is True


# --- Independent-QA repair round (P1/P2) ------------------------------------


def test_teacher_override_cannot_resurrect_denied_asset() -> None:
    # Independent QA P1: the candidate-set fingerprint binds identity
    # triples only, so revoking asset-002's approved use does not change
    # it. Decision eligibility must come from the candidate filter's
    # eligible classifications — a denied asset is not eligible, and a
    # teacher decision can never honor it back into an unblocked plan.
    requirement, candidates, evidence = _two_candidate_setup()
    decision = _decision(requirement, candidates, role_id=_role_id(requirement))
    denied_candidates = [
        candidates[0],
        build_candidate(2, RELATED_TITLE, approved_state="denied"),
    ]
    plan = run_plan(denied_candidates, evidence, requirement=requirement,
                    teacher_decisions=(decision,))
    assert plan.outcome == "teacher-decision-invalidated"
    assert plan.final_production_blocked is True
    assert plan.selected_asset_ids == ()
    outcomes = [o for o in plan.teacher_decision_outcomes
                if o["decision_id"] == "decision-3672"]
    assert outcomes and outcomes[0]["honored"] is False


def test_teacher_override_cannot_select_denied_asset_recorded_directly() -> None:
    requirement, _, evidence = _two_candidate_setup()
    denied_candidates = [
        build_candidate(1, EXACT_TITLE),
        build_candidate(2, RELATED_TITLE, approved_state="denied"),
    ]
    decision = _decision(requirement, denied_candidates,
                         role_id=_role_id(requirement))
    plan = run_plan(denied_candidates, evidence, requirement=requirement,
                    teacher_decisions=(decision,))
    assert plan.outcome == "teacher-decision-invalidated"
    assert plan.selected_asset_ids == ()


def test_object_form_library_record_title_is_reconciled() -> None:
    # Independent QA P2: the compatibility contract also accepts an
    # ExistingAssetRecord object as library_record. The scoping boundary
    # must reconcile its claimed title too — never skip it fail-open.
    from visual_asset_sync.models import ExistingAssetRecord

    def object_form(envelope):
        envelope = copy.deepcopy(envelope)
        record = envelope["library_record"]
        envelope["library_record"] = ExistingAssetRecord(
            page_id=record["page_id"],
            page_url=record["page_url"],
            drive_file_id=record["drive_file_id"],
            drive_url=record["drive_url"],
            asset_title=record["asset_title"],
            approved_use=record["approved_use"],
            asset_type=record["asset_type"],
            human_review_status=record["human_review_status"],
            review_date=record["review_date"],
            extra_fields=dict(record["extra_fields"]),
        )
        return envelope

    forged = object_form(build_candidate(1, EXACT_TITLE))
    plan = run_plan([forged], [evidence_for(1, "Leading Lines - Governed Title")])
    assert plan.outcome == "title-conflict"
    assert plan.selected_asset_ids == ()

    matching = object_form(build_candidate(1, EXACT_TITLE))
    plan = run_plan([matching], [evidence_for(1, EXACT_TITLE)])
    assert plan.outcome == "visuals-ready"
    assert plan.selected_asset_ids == ("asset-001",)


def test_dict_subclass_library_record_title_is_reconciled() -> None:
    # Independent QA round-2 P3 hardening: a dict subclass carrying the
    # claim as a key must be reconciled too — the stored key is read
    # directly, never routed through a possibly-overridden .get.
    class SubDict(dict):
        pass

    envelope = build_candidate(1, EXACT_TITLE)
    envelope["library_record"] = SubDict(envelope["library_record"])
    state, scoped = visual_reuse._scope_candidates_to_current_assets(
        [envelope], [evidence_for(1, "Leading Lines - Governed Title")], REVISION
    )
    assert state == "title-conflict"
    assert scoped == []
