from __future__ import annotations

import copy
import json
from pathlib import Path

from instructional_workflow_contracts import AuthorityEvidence, canonical_json_bytes
from instructional_workflow_contracts.handoff import validate_curriculum_handoff
from instructional_workflow_contracts.material_requirement import validate_material_requirement
from instructional_workflow_contracts.ppux_projection_input import (
    PPUX_INPUT_VERSION,
    assemble_ppux_projection_input,
)
from instructional_workflow_contracts.visual_needs import plan_visual_needs


FIXTURES = Path(__file__).parent / "fixtures" / "instructional_workflow_contracts"


def fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def upstream():
    handoff = fixture("valid_handoff.json")
    material = fixture("valid_material_requirement_v2.json")
    visual = plan_visual_needs(material)
    assert validate_curriculum_handoff(handoff).record is not None
    assert validate_material_requirement(material).record is not None
    assert visual.record is not None
    return handoff, material, visual


def tutorial(recording_id: str = "photography-foundations-typography") -> dict[str, object]:
    digest = "c" * 64
    return {
        "recording_id": recording_id,
        "recording_sha256": digest,
        "retained_steps": [
            {
                "review_step_id": "typography-step-1",
                "sequence": 1,
                "source_step_ids": ["teacher-modeling-step-1"],
                "source_steps": [],
                "semantic_action_ids": ["action-1"],
                "source_indexes": [0],
                "recording_id": recording_id,
                "recording_sha256": digest,
                "modeled_application": "Canva",
                "action_identity": [
                    {"sourceIndex": 0, "sourceFingerprint": "d" * 64}
                ],
                "execution_authorized": False,
            }
        ],
        "excluded_step_ids": [],
        "review_decisions": [{"step_id": "teacher-modeling-step-1", "choice": "keep"}],
        "recording_evidence": {
            "recordingSha256": digest,
            "actionIdentity": [{"sourceIndex": 0, "sourceFingerprint": "d" * 64}],
            "claims": [],
        },
        "execution_authorized": False,
    }


def routed_steps(visual) -> list[dict[str, object]]:
    payload = visual.record.to_dict()
    role_id = payload["required_roles"][0]["role_id"]
    return [
        {
            "reviewStepId": "typography-step-1",
            "visualRoleRef": role_id,
            "disposition": "new-visual",
            "authoring": {
                "imagePurpose": "Model purposeful typography hierarchy.",
                "imageState": "result",
                "applicationContext": "",
                "targetState": "clear hierarchy between headline and supporting text",
                "mustShow": ["headline", "supporting text"],
                "mustNotShow": ["student data"],
                "annotationSpace": "right side",
                "requestedUiDetails": [],
            },
        }
    ]


def test_assembles_exact_ppux_envelope_with_stable_identity() -> None:
    handoff, material, visual = upstream()

    first = assemble_ppux_projection_input(
        handoff=handoff,
        material_requirement=material,
        visual_needs_plan=visual,
        reviewed_tutorial=tutorial(),
        routed_steps=routed_steps(visual),
    )
    second = assemble_ppux_projection_input(
        handoff=copy.deepcopy(handoff),
        material_requirement=copy.deepcopy(material),
        visual_needs_plan=visual,
        reviewed_tutorial=copy.deepcopy(tutorial()),
        routed_steps=copy.deepcopy(routed_steps(visual)),
    )

    assert first.status == "valid"
    assert first.envelope is not None
    assert first.envelope["formatVersion"] == PPUX_INPUT_VERSION
    assert set(first.envelope) == {"formatVersion", "tutorial", "route"}
    assert first.envelope["route"]["sourceHandoffRef"] == "handoff-1"
    assert first.envelope["route"]["sourceFingerprint"] == (
        validate_curriculum_handoff(handoff).record.fingerprint
    )
    assert first.envelope["route"]["objectiveRef"] == "objective-1"
    assert first.envelope["route"]["successCriteriaRef"] == "criteria-1"
    assert first.envelope["route"]["evidenceTargetRef"] == "evidence-1"
    assert first.canonical_bytes == canonical_json_bytes(first.envelope)
    assert first.sha256 == second.sha256
    assert first.canonical_bytes == second.canonical_bytes
    assert first.byte_length == len(first.canonical_bytes)
    assert first.authority == AuthorityEvidence()


def test_material_handoff_mismatch_fails_closed() -> None:
    handoff, material, visual = upstream()
    other = copy.deepcopy(handoff)
    other["identity"]["handoff_id"] = "handoff-other"

    result = assemble_ppux_projection_input(
        handoff=other,
        material_requirement=material,
        visual_needs_plan=visual,
        reviewed_tutorial=tutorial(),
        routed_steps=routed_steps(visual),
    )

    assert result.status == "blocked"
    assert result.envelope is None
    assert result.reason_codes == ("ppux-handoff-mismatch",)


def test_visual_plan_must_reconstruct_from_exact_material_requirement() -> None:
    handoff, material, visual = upstream()
    other_material = copy.deepcopy(material)
    other_material["visual_direction"]["roles"][0]["instructional_purpose"] = (
        "A materially different visual purpose."
    )
    from instructional_workflow_contracts.material_requirement import (
        material_requirement_source_fingerprint,
    )
    other_material["identity"]["source_fingerprint"] = material_requirement_source_fingerprint(
        other_material
    )

    result = assemble_ppux_projection_input(
        handoff=handoff,
        material_requirement=other_material,
        visual_needs_plan=visual,
        reviewed_tutorial=tutorial(),
        routed_steps=routed_steps(visual),
    )

    assert result.status == "blocked"
    assert result.reason_codes == ("ppux-visual-needs-mismatch",)


def test_unmatched_or_duplicate_reviewed_steps_fail_closed() -> None:
    handoff, material, visual = upstream()
    steps = routed_steps(visual)
    steps[0]["reviewStepId"] = "another-step"

    result = assemble_ppux_projection_input(
        handoff=handoff,
        material_requirement=material,
        visual_needs_plan=visual,
        reviewed_tutorial=tutorial(),
        routed_steps=steps,
    )
    assert result.status == "blocked"
    assert result.reason_codes == ("ppux-step-unmatched",)


def test_visual_role_must_come_from_canonical_visual_needs_plan() -> None:
    handoff, material, visual = upstream()
    steps = routed_steps(visual)
    steps[0]["visualRoleRef"] = "visual-role:invented"

    result = assemble_ppux_projection_input(
        handoff=handoff,
        material_requirement=material,
        visual_needs_plan=visual,
        reviewed_tutorial=tutorial(),
        routed_steps=steps,
    )
    assert result.status == "blocked"
    assert result.reason_codes == ("ppux-visual-role-mismatch",)


def test_tutorial_recording_identity_is_bound_across_retained_steps() -> None:
    handoff, material, visual = upstream()
    reviewed = tutorial()
    reviewed["retained_steps"][0]["recording_id"] = "tutorial-0-fixture"

    result = assemble_ppux_projection_input(
        handoff=handoff,
        material_requirement=material,
        visual_needs_plan=visual,
        reviewed_tutorial=reviewed,
        routed_steps=routed_steps(visual),
    )
    assert result.status == "blocked"
    assert result.reason_codes == ("ppux-tutorial-identity-mismatch",)


def test_new_visual_requires_existing_authoring_evidence() -> None:
    handoff, material, visual = upstream()
    steps = routed_steps(visual)
    del steps[0]["authoring"]

    result = assemble_ppux_projection_input(
        handoff=handoff,
        material_requirement=material,
        visual_needs_plan=visual,
        reviewed_tutorial=tutorial(),
        routed_steps=steps,
    )
    assert result.status == "blocked"
    assert result.reason_codes == ("ppux-authoring-missing",)


def test_no_authority_or_external_effect_is_created() -> None:
    handoff, material, visual = upstream()
    result = assemble_ppux_projection_input(
        handoff=handoff,
        material_requirement=material,
        visual_needs_plan=visual,
        reviewed_tutorial=tutorial(),
        routed_steps=routed_steps(visual),
    )

    assert result.status == "valid"
    assert result.authority.execution_authorized is False
    assert result.authority.external_write_authorized is False
    assert result.authority.production_authorized is False
    assert result.authority.publication_authorized is False
