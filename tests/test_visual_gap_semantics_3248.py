"""Regression tests for #3248 — false visual-gap semantics.

Invariant: only proven absence of an eligible reusable asset may produce a
visual gap (image-gap brief) or authorize new image creation.

Every case enters through the real producers:
    validate_material_requirement -> plan_visual_needs ->
    filter_approved_visual_candidates -> plan_cohesive_visual_set ->
    bind_gap_to_image_intent
plus the Asset Picker (resolve_visual_asset_picker), the IMC orchestration
(plan_governed_visual_reuse), and the curriculum resolver
(resolve_current_curriculum_state).

Retained worksheet acceptance cases #3212 (Motion Spot text-only packet),
#3214 (Motion Spot zero icons) and #3204 (AI Superhero icons only on the
cover) are referenced here as the acceptance fixtures they are: their causal
path is unproven until #3259 establishes engine authority, so no
unit-specific code is added — these contract-level cases pin the taxonomy
those worksheets will be judged against.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from instructional_workflow_contracts import ValidationStatus
from instructional_workflow_contracts.artifact_manifest import (
    artifact_manifest_source_fingerprint,
    validate_artifact_manifest,
)
from instructional_workflow_contracts.common import freeze_json, sha256_hex
from instructional_workflow_contracts.cohesive_visual_plan import (
    plan_cohesive_visual_set,
)
from instructional_workflow_contracts.current_curriculum_state import (
    resolve_current_curriculum_state,
)
from instructional_workflow_contracts.image_intent import validate_image_intent
from instructional_workflow_contracts.material_requirement import (
    material_requirement_source_fingerprint,
    validate_material_requirement,
)
from instructional_workflow_contracts.visual_asset_candidates import (
    V2_CONTRACT_ID,
    filter_approved_visual_candidates,
)
from instructional_workflow_contracts.visual_asset_picker import (
    AssetCandidate,
    AssetPickerIntent,
    resolve_visual_asset_picker,
)
from instructional_workflow_contracts.visual_generation_provenance import (
    bind_gap_to_image_intent,
)
from instructional_workflow_contracts.visual_needs import plan_visual_needs

FIXTURES = Path(__file__).parent / "fixtures" / "instructional_workflow_contracts"
READ_REVISION = "visual-library-read-3248"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _requirement(*, two_required_roles: bool = False, maximum_visual_count: int | None = None):
    """Real validated MaterialRequirement; optionally two required roles."""
    mr = _load("valid_material_requirement_v2.json")
    if maximum_visual_count is not None:
        mr["visual_direction"]["maximum_visual_count"] = maximum_visual_count
    if two_required_roles:
        roles = mr["visual_direction"]["roles"]
        roles[1]["requirement_state"] = "required"
        # Keep the input in the validator's canonical role order so the real
        # producer round-trips (comparison < worked-example).
        mr["visual_direction"]["roles"] = [roles[1], roles[0]]
    mr["identity"]["source_fingerprint"] = material_requirement_source_fingerprint(mr)
    result = validate_material_requirement(mr)
    assert result.status is ValidationStatus.VALID, result.reason_codes
    assert result.record is not None
    return result.record


def _needs(requirement):
    """Real visual-needs plan through the governed producer."""
    result = plan_visual_needs(requirement)
    assert result.status is ValidationStatus.VALID, result.reason_codes
    assert result.record is not None
    return result.record


def _raw_envelope(
    *,
    asset_id: str,
    role_types: list[str],
    orientation: str,
    palette_family: str | None = None,
    cognitive_load_rating: int | None = None,
    access_state: str | None = None,
    duplicate_group_id: str | None = None,
) -> dict:
    """Real compatibility envelope, manifest re-signed through the producer."""
    raw = _load("valid_visual_asset_compatibility_v2.json")
    manifest = raw["artifact_manifest"]
    asset = manifest["assets"][0]
    asset["asset_id"] = asset_id
    asset["stable_ref"] = f"{asset_id}-ref"
    asset["content_fingerprint"] = sha256_hex({"asset": asset_id})
    if duplicate_group_id is not None:
        asset["duplicate_group_id"] = duplicate_group_id
    if access_state is not None:
        manifest["external_identity"]["access_state"] = access_state
        # A non-verified access state is only representable on a manifest that
        # is not classroom-ready (ready + unverified is structurally invalid).
        manifest["statuses"]["classroom_readiness"] = "blocked"
        asset["direct_use_status"] = "blocked"
    manifest["identity"]["source_fingerprint"] = artifact_manifest_source_fingerprint(
        manifest
    )
    manifest_result = validate_artifact_manifest(manifest)
    if access_state is None:
        assert manifest_result.status is ValidationStatus.VALID, manifest_result.reason_codes
    else:
        # Non-verified access: the manifest itself is manual-review; the
        # compatibility contract converts that into
        # asset-compatibility-invalid-manifest (the S4 inaccessible case).
        assert manifest_result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert manifest_result.record is not None
    manifest_fingerprint = manifest_result.record.fingerprint

    evidence = raw["compatibility_evidence"]
    evidence["asset_reference"] = {
        "asset_id": asset_id,
        "stable_ref": f"{asset_id}-ref",
        "content_fingerprint": sha256_hex({"asset": asset_id}),
    }
    evidence["manifest_reference"]["fingerprint"] = manifest_fingerprint
    evidence["freshness"]["manifest_fingerprint"] = manifest_fingerprint
    evidence["purpose"]["role_types"] = list(role_types)
    evidence["approved_use"]["role_types"] = list(role_types)
    evidence["orientation"]["orientation"] = orientation
    if palette_family is not None:
        evidence["cohesion_profile"]["palette_family"] = palette_family
    if cognitive_load_rating is not None:
        evidence["cohesion_profile"]["cognitive_load_rating"] = cognitive_load_rating
    return raw


def _filter(plan_record, raws, *, source_revision: str = READ_REVISION):
    result = filter_approved_visual_candidates(
        plan_record,
        raws,
        source_revision=source_revision,
        contract_version=V2_CONTRACT_ID,
    )
    return result


def _intent():
    result = validate_image_intent(
        {
            "identity": {
                "contract_version": "curriculum-image-intent-v1",
                "intent_id": "intent-3248-regression",
                "asset_id": None,
                "concept": "Regression concept",
                "purpose": "prove the #3248 binding boundary",
            },
            "scene": {
                "subject": "a classroom object",
                "action": None,
                "environment": "a classroom",
            },
            "visual_direction": {
                "composition": "centered",
                "viewpoint": "eye level",
                "look": "natural",
            },
            "control": {"must_show": ["object"], "avoid": [], "creative_freedom": []},
            "output": {"orientation": "landscape", "aspect_target": "16:9", "add_later": []},
            "library_handoff": {
                "unit_lesson": "U / L",
                "asset_role": "role",
                "intended_reuse": ["r"],
                "candidate_status": None,
                "review_notes": None,
            },
        }
    )
    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    return result.record


def _unfilled(plan_result):
    payload = plan_result.record.to_dict()
    unfilled = payload["unfilled_required_roles"]
    brief_roles = [u for u in unfilled if u["outcome_code"] == "proven-absence"]
    return brief_roles, unfilled, payload["image_gap_briefs"]


# --- Positive control: true proven absence still emits an evidence-backed brief.


def test_proven_absence_emits_evidence_backed_brief_and_binds() -> None:
    plan = _needs(_requirement())
    filtered = _filter(plan, [])
    assert filtered.status is ValidationStatus.VALID
    assert filtered.record is not None

    planned = plan_cohesive_visual_set(plan, filtered.record)
    assert planned.status is ValidationStatus.VALID
    unfilled_roles, unfilled, briefs = _unfilled(planned)
    assert len(unfilled_roles) == 1
    assert unfilled[0]["outcome_code"] == "proven-absence"
    assert len(briefs) == 1

    brief = briefs[0]
    evidence = brief["absence_evidence"]
    assert evidence["proven_absence"] is True
    assert evidence["remedy_class"] == "absent"
    assert evidence["snapshot"]["candidate_filter_id"] == filtered.record.record_id
    assert evidence["snapshot"]["candidate_filter_fingerprint"] == filtered.record.fingerprint
    assert evidence["snapshot"]["source_revision"] == READ_REVISION
    assert evidence["filter_evidence"] == {
        "candidate_count": 0,
        "eligible": 0,
        "rejected": 0,
        "manual_review": 0,
    }

    bound = bind_gap_to_image_intent(
        planned.record,
        brief_id=brief["brief_id"],
        missing_visual_role_id=brief["missing_visual_role_id"],
        image_intent=_intent(),
    )
    assert bound.status is ValidationStatus.VALID


# --- Non-absence states: distinct codes, never a brief, never a permission.


def test_cohesion_rejection_is_policy_unassigned_never_a_brief() -> None:
    # Ceiling 8 keeps the load gate out of this cohesion case (load semantics
    # belong to #3250; this test only pins the classification boundary).
    plan = _needs(_requirement(two_required_roles=True, maximum_visual_count=8))
    first = _raw_envelope(
        asset_id="asset-worked",
        role_types=["worked-example"],
        orientation="landscape",
        palette_family="limited-color",
        cognitive_load_rating=1,
    )
    second = _raw_envelope(
        asset_id="asset-comparison",
        role_types=["comparison"],
        orientation="square",
        palette_family="full-color",
        cognitive_load_rating=1,
    )
    filtered = _filter(plan, [first, second])
    assert filtered.status is ValidationStatus.VALID
    assert filtered.record is not None
    assert len(filtered.record.to_dict()["eligible"]) == 2

    planned = plan_cohesive_visual_set(plan, filtered.record)
    assert planned.status is ValidationStatus.VALID
    unfilled_roles, unfilled, briefs = _unfilled(planned)
    assert briefs == []
    assert unfilled_roles == []
    assert len(unfilled) == 1
    entry = unfilled[0]
    assert entry["role_type"] == "worked-example"
    assert entry["outcome_code"] == "policy-unassigned"
    assert "asset-cohesion-palette-conflict" in entry["reason_codes"]
    assert entry["rejected_candidate_ids"] != []
    assert entry["remedy_class"] == "policy-unassigned"


def test_shared_asset_permit_fills_both_roles_never_a_brief() -> None:
    # #3251 shared-asset policy: one governed asset approved for two roles
    # fills BOTH roles when it passes each binding's role-intrinsic
    # compatibility independently. The old unconditional
    # asset-duplicate-selected rejection is waived for the identical asset;
    # each binding is its own (role_id, slot_id) record sharing the asset.
    plan = _needs(_requirement(two_required_roles=True))
    only = _raw_envelope(
        asset_id="asset-shared",
        role_types=["worked-example", "comparison"],
        orientation="flexible",
    )
    filtered = _filter(plan, [only])
    assert filtered.status is ValidationStatus.VALID
    planned = plan_cohesive_visual_set(plan, filtered.record)
    assert planned.status is ValidationStatus.VALID
    payload = planned.record.to_dict()
    assert payload["outcome"] == "complete-set"
    brief_roles, unfilled, briefs = _unfilled(planned)
    assert briefs == []
    assert brief_roles == []
    assert unfilled == []
    bindings = [
        (assignment["role_id"], assignment["slot_id"])
        for assignment in payload["required_role_assignments"]
    ]
    assert len(bindings) == 2
    assert len(set(bindings)) == 2
    assert {
        assignment["selected_candidate"]["asset_reference"]["asset_id"]
        for assignment in payload["required_role_assignments"]
    } == {"asset-shared"}


def test_duplicate_group_collision_is_policy_unassigned_never_a_brief() -> None:
    # #3251: the shared-asset permit covers only the IDENTICAL governed
    # asset. A different asset that collides with an already-selected asset
    # (same duplicate group) is still an explicit policy rejection:
    # policy-unassigned, never a visual gap, never a brief.
    plan = _needs(_requirement(two_required_roles=True))
    # asset-first fills the comparison role. asset-second is a DIFFERENT
    # asset in the same duplicate group, role-compatible only with the
    # worked-example role (landscape): the identical-asset permit cannot
    # apply (asset-first is square and fails the worked-example
    # orientation check), so the duplicate-group collision stays an
    # explicit policy rejection.
    first = _raw_envelope(
        asset_id="asset-first",
        role_types=["comparison"],
        orientation="square",
        duplicate_group_id="duplicate-group-1",
    )
    second = _raw_envelope(
        asset_id="asset-second",
        role_types=["worked-example"],
        orientation="landscape",
        duplicate_group_id="duplicate-group-1",
    )
    filtered = _filter(plan, [first, second])
    assert filtered.status is ValidationStatus.VALID
    assert len(filtered.record.to_dict()["eligible"]) == 2
    planned = plan_cohesive_visual_set(plan, filtered.record)
    assert planned.status is ValidationStatus.VALID
    brief_roles, unfilled, briefs = _unfilled(planned)
    assert briefs == []
    assert brief_roles == []
    assert len(unfilled) == 1
    entry = unfilled[0]
    assert entry["role_type"] == "worked-example"
    assert entry["outcome_code"] == "policy-unassigned"
    assert "asset-duplicate-selected" in entry["reason_codes"]
    assert entry["rejected_candidate_ids"] != []
    assert entry["remedy_class"] == "policy-unassigned"


def test_cognitive_load_rating_is_advisory_never_a_brief() -> None:
    # #3250 option (b): load evidence remains observable, but no governed load
    # model exists, so rating 5 must not reject an otherwise eligible asset.
    plan = _needs(_requirement())
    heavy = _raw_envelope(
        asset_id="asset-heavy",
        role_types=["worked-example"],
        orientation="landscape",
        cognitive_load_rating=5,
    )
    filtered = _filter(plan, [heavy])
    assert filtered.status is ValidationStatus.VALID
    planned = plan_cohesive_visual_set(plan, filtered.record)
    assert planned.status is ValidationStatus.VALID
    unfilled_roles, unfilled, briefs = _unfilled(planned)
    assert briefs == []
    assert unfilled_roles == []
    assert unfilled == []
    assert planned.record is not None
    payload = planned.record.to_dict()
    assert payload["cognitive_load"]["total"] == 5
    assert all(
        "asset-cognitive-load-exceeded" not in item["reason_codes"]
        for item in payload["rejected_set_combinations"]
    )


def test_incompatible_candidate_never_becomes_a_brief() -> None:
    plan = _needs(_requirement())
    wrong_role = _raw_envelope(
        asset_id="asset-other",
        role_types=["comparison"],
        orientation="square",
    )
    filtered = _filter(plan, [wrong_role])
    assert filtered.status is ValidationStatus.VALID
    planned = plan_cohesive_visual_set(plan, filtered.record)
    assert planned.status is ValidationStatus.VALID
    unfilled_roles, unfilled, briefs = _unfilled(planned)
    assert briefs == []
    assert unfilled_roles == []
    assert len(unfilled) == 1
    assert unfilled[0]["outcome_code"] == "incompatible"
    assert unfilled[0]["remedy_class"] == "unapproved-for-use"


def test_inaccessible_candidate_never_becomes_a_brief() -> None:
    plan = _needs(_requirement())
    transient = _raw_envelope(
        asset_id="asset-transient",
        role_types=["worked-example"],
        orientation="landscape",
        access_state="transient-error",
    )
    filtered = _filter(plan, [transient])
    assert filtered.status is ValidationStatus.VALID
    assert filtered.record is not None
    rejected = filtered.record.to_dict()["rejected"]
    assert len(rejected) == 1
    assert "asset-compatibility-invalid-manifest" in rejected[0]["reason_codes"]

    planned = plan_cohesive_visual_set(plan, filtered.record)
    assert planned.status is ValidationStatus.VALID
    unfilled_roles, unfilled, briefs = _unfilled(planned)
    assert briefs == []
    assert unfilled_roles == []
    assert len(unfilled) == 1
    assert unfilled[0]["outcome_code"] == "inaccessible"


def test_manual_review_plan_emits_no_briefs() -> None:
    plan = _needs(_requirement())
    # Manual-review candidate: unspecified palette forces bounded human review.
    review_raw = _raw_envelope(
        asset_id="asset-review",
        role_types=["worked-example"],
        orientation="landscape",
    )
    review_raw["compatibility_evidence"]["cohesion_profile"]["palette_family"] = (
        "unspecified"
    )
    filtered = _filter(plan, [review_raw])
    assert filtered.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert filtered.record is not None

    planned = plan_cohesive_visual_set(plan, filtered.record)
    assert planned.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    _, unfilled, briefs = _unfilled(planned)
    assert briefs == []
    assert unfilled and unfilled[0]["outcome_code"] == "review-pending"


# --- Binding admission: non-absence, manual-review, and stale briefs rejected.


def test_binding_rejects_brief_without_proven_absence_evidence() -> None:
    plan = _needs(_requirement())
    filtered = _filter(plan, [])
    planned = plan_cohesive_visual_set(plan, filtered.record)
    assert planned.record is not None
    payload = copy.deepcopy(planned.record.to_dict())
    # Simulate a legacy / forged brief that asserts absence without evidence.
    payload["image_gap_briefs"][0].pop("absence_evidence")
    forged_id = "cohesive-visual-plan-forged-3248"
    payload["cohesive_visual_plan_id"] = forged_id
    forged = copy.deepcopy(planned.record)
    object.__setattr__(forged, "payload", freeze_json(payload))
    object.__setattr__(forged, "fingerprint", sha256_hex(payload))
    object.__setattr__(forged, "record_id", forged_id)

    brief = payload["image_gap_briefs"][0]
    bound = bind_gap_to_image_intent(
        forged,
        brief_id=brief["brief_id"],
        missing_visual_role_id=brief["missing_visual_role_id"],
        image_intent=_intent(),
    )
    assert bound.status is ValidationStatus.INVALID
    assert bound.reason_codes == ("asset-gap-not-proven-absence",)


def test_binding_rejects_stale_snapshot() -> None:
    plan = _needs(_requirement())
    filtered = _filter(plan, [])
    planned = plan_cohesive_visual_set(plan, filtered.record)
    assert planned.record is not None
    payload = copy.deepcopy(planned.record.to_dict())
    payload["image_gap_briefs"][0]["absence_evidence"]["snapshot"][
        "candidate_filter_fingerprint"
    ] = "0" * 64
    stale_id = "cohesive-visual-plan-stale-3248"
    payload["cohesive_visual_plan_id"] = stale_id
    stale = copy.deepcopy(planned.record)
    object.__setattr__(stale, "payload", freeze_json(payload))
    object.__setattr__(stale, "fingerprint", sha256_hex(payload))
    object.__setattr__(stale, "record_id", stale_id)

    brief = payload["image_gap_briefs"][0]
    bound = bind_gap_to_image_intent(
        stale,
        brief_id=brief["brief_id"],
        missing_visual_role_id=brief["missing_visual_role_id"],
        image_intent=_intent(),
    )
    assert bound.status is ValidationStatus.INVALID
    assert bound.reason_codes == ("asset-gap-stale-snapshot",)


def test_binding_rejects_manual_review_plan() -> None:
    plan = _needs(_requirement())
    filtered = _filter(plan, [])
    planned = plan_cohesive_visual_set(plan, filtered.record)
    assert planned.record is not None
    payload = copy.deepcopy(planned.record.to_dict())
    payload["manual_review_required"] = True
    payload["manual_review_reasons"] = ["manual-review-visual-candidates"]
    review_id = "cohesive-visual-plan-review-3248"
    payload["cohesive_visual_plan_id"] = review_id
    review_plan = copy.deepcopy(planned.record)
    object.__setattr__(review_plan, "payload", freeze_json(payload))
    object.__setattr__(review_plan, "fingerprint", sha256_hex(payload))
    object.__setattr__(review_plan, "record_id", review_id)

    brief = payload["image_gap_briefs"][0]
    bound = bind_gap_to_image_intent(
        review_plan,
        brief_id=brief["brief_id"],
        missing_visual_role_id=brief["missing_visual_role_id"],
        image_intent=_intent(),
    )
    assert bound.status is ValidationStatus.INVALID
    assert bound.reason_codes == ("asset-gap-manual-review-plan",)


# --- Asset Picker: the three non-absence cases never authorize creation.


def _picker_candidate(asset_id: str, **overrides) -> AssetCandidate:
    values = dict(
        asset_id=asset_id,
        source_reference=f"notion:{asset_id}",
        eligible=True,
        review_status="approved",
    )
    values.update(overrides)
    return AssetCandidate(**values)


def test_picker_requested_id_miss_is_invalid_without_handoff() -> None:
    intent = AssetPickerIntent(
        source_preference="explicit-existing",
        requested_asset_ids=("wanted",),
        generation_allowed=True,
    )
    result = resolve_visual_asset_picker(intent, [_picker_candidate("other")])
    assert result.outcome == "selection-invalidated"
    assert result.create_new_handoff_allowed is False


def test_picker_needs_review_only_requires_review_without_handoff() -> None:
    result = resolve_visual_asset_picker(
        AssetPickerIntent(generation_allowed=True),
        [_picker_candidate("review-a", review_status="needs-review")],
    )
    assert result.outcome == "review-required"
    assert result.needs_review_asset_ids == ("review-a",)
    assert result.selected_references == ()
    assert result.create_new_handoff_allowed is False


def test_picker_empty_pool_is_blocked_without_handoff() -> None:
    result = resolve_visual_asset_picker(AssetPickerIntent(generation_allowed=True), [])
    assert result.outcome == "blocked"
    assert result.create_new_handoff_allowed is False
