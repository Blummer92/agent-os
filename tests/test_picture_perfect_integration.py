import hashlib
import json
from pathlib import Path

import pytest

from instructional_workflow_contracts.image_intent import IMAGE_INTENT_CONTRACT_ID
from instructional_workflow_contracts.picture_perfect_integration import (
    apply_modeling_decision,
    build_image_intent,
    build_modeling_candidates,
    build_visual_requirement,
    visual_provenance,
)
from scripts.agent_os_replay_json.analyzer import analyze_replay
from scripts.agent_os_replay_json.rewriter import rewrite_replay


FIXTURE = Path("tests/fixtures/agent_os_replay_json/tutorial_0_organization_core.json")


def _fixture():
    return json.loads(FIXTURE.read_text())


def _evidence():
    payload = _fixture()
    actions = [action.to_dict() for action in analyze_replay(payload)]
    rewrite = rewrite_replay(payload).to_dict()
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    candidates = build_modeling_candidates(
        recording_id="tutorial-0-organization-core",
        recording_sha256=digest,
        semantic_actions=actions,
        rewrite_operations=rewrite["operations"],
    )
    return payload, actions, rewrite, candidates


def _decision(candidate, *, step_id, sequence, title, student_action, notice, check):
    return apply_modeling_decision(
        candidate,
        disposition="keep",
        step_id=step_id,
        sequence=sequence,
        title=title,
        student_action=student_action,
        notice=notice,
        check=check,
    )


def test_tutorial_0_rj_evidence_builds_candidates_without_instructional_authority():
    payload, actions, rewrite, candidates = _evidence()

    assert len(payload["steps"]) == 14
    assert len(candidates) == len(actions)
    assert any(item["action_kind"] == "open_your_stuff" for item in candidates)
    assert any(item["action_kind"] == "open_folder" and item["fragile"] for item in candidates)
    assert any(item["action_kind"] == "keyboard_noise" for item in candidates)
    assert all(item["instructional_disposition"] == "undecided" for item in candidates)
    assert all(item["rj3_state"] == "pending" for item in candidates)
    assert all(item["rj4_state"] == "pending" for item in candidates)
    assert rewrite["semantic_equivalence"] == "proven"


def test_six_step_tutorial_0_modeling_sequence_is_teacher_modeling_owned():
    _, _, _, candidates = _evidence()
    by_kind = {}
    for candidate in candidates:
        by_kind.setdefault(candidate["action_kind"], []).append(candidate)

    steps = [
        _decision(
            by_kind["open_your_stuff"][0],
            step_id="tutorial0-step-01-open-your-stuff",
            sequence=1,
            title="Open Your Stuff",
            student_action="Open Your Stuff in Adobe Express.",
            notice="Your Stuff is where class files and folders are organized.",
            check="The Your Stuff workspace is visible.",
        ),
        _decision(
            by_kind["choose_create_folder"][0],
            step_id="tutorial0-step-02-create-digital-media",
            sequence=2,
            title="Create the Digital Media folder",
            student_action="Choose Create folder.",
            notice="A new folder is being created in Your Stuff.",
            check="The folder naming field is visible.",
        ),
        _decision(
            by_kind["rename"][0],
            step_id="tutorial0-step-03-name-digital-media",
            sequence=3,
            title="Name the folder Digital Media",
            student_action="Name the folder Digital Media and confirm.",
            notice="The folder name matches the class organization structure.",
            check="A Digital Media folder is visible.",
        ),
        _decision(
            by_kind["open_folder"][0],
            step_id="tutorial0-step-04-enter-digital-media",
            sequence=4,
            title="Open Digital Media",
            student_action="Open the Digital Media folder.",
            notice="The breadcrumb or folder view shows that Digital Media is open.",
            check="The Digital Media folder contents are visible.",
        ),
        _decision(
            by_kind["choose_create_folder"][1],
            step_id="tutorial0-step-05-create-tutorial-folder",
            sequence=5,
            title="Create the Tutorial 0 folder",
            student_action="Create another folder inside Digital Media.",
            notice="The new folder is nested inside Digital Media.",
            check="The folder naming field is visible inside Digital Media.",
        ),
        _decision(
            by_kind["rename"][1],
            step_id="tutorial0-step-06-name-tutorial-folder",
            sequence=6,
            title="Name the Tutorial 0 folder",
            student_action="Name the folder Tutorial 0 - Organize My Files and confirm.",
            notice="The Tutorial 0 folder has the exact organization name.",
            check="Tutorial 0 - Organize My Files is visible inside Digital Media.",
        ),
    ]

    assert [step["sequence"] for step in steps] == [1, 2, 3, 4, 5, 6]
    assert all(step["execution_authorized"] is False for step in steps)
    assert all(step["source"]["recording_sha256"] for step in steps)


def test_rj2_noise_disposition_never_becomes_instructional_disposition_automatically():
    _, actions, _, _ = _evidence()
    noise_index = next(i for i, action in enumerate(actions) if action["kind"] == "keyboard_noise")
    noise = actions[noise_index]
    candidates = build_modeling_candidates(
        recording_id="tutorial-0-noise-case",
        recording_sha256="a" * 64,
        semantic_actions=[noise],
        rewrite_operations=[
            {
                "kind": "remove-noise",
                "semantic_action_id": "action-0",
                "source_indexes": noise["source_indexes"],
                "confidence": "proven",
            }
        ],
    )

    assert candidates[0]["rewrite"]["kind"] == "remove-noise"
    assert candidates[0]["instructional_disposition"] == "undecided"


def test_picture_perfect_adds_visual_state_without_mutating_student_action():
    _, _, _, candidates = _evidence()
    candidate = next(item for item in candidates if item["action_kind"] == "open_your_stuff")
    step = _decision(
        candidate,
        step_id="tutorial0-step-01-open-your-stuff",
        sequence=1,
        title="Open Your Stuff",
        student_action="Open Your Stuff in Adobe Express.",
        notice="Your Stuff is where class files are organized.",
        check="The Your Stuff workspace is visible.",
    )

    visual = build_visual_requirement(
        step,
        visual_state="action",
        must_show=["Adobe Express workspace", "Your Stuff navigation control"],
        must_not_show=["student names", "email addresses", "support chat"],
    )

    assert visual["student_action"] == step["student_action"]
    assert visual["sequence"] == step["sequence"]
    assert visual["semantic_action_ids"] == step["semantic_action_ids"]
    assert visual["source"] == step["source"]


def test_visual_requirement_rejects_raw_recorder_selector_leakage():
    _, _, _, candidates = _evidence()
    candidate = next(item for item in candidates if item["action_kind"] == "open_your_stuff")
    step = _decision(
        candidate,
        step_id="tutorial0-step-01-open-your-stuff",
        sequence=1,
        title="Open Your Stuff",
        student_action="Open Your Stuff in Adobe Express.",
        notice="Your Stuff is where class files are organized.",
        check="The Your Stuff workspace is visible.",
    )

    with pytest.raises(ValueError, match="raw Recorder selector evidence"):
        build_visual_requirement(
            step,
            visual_state="action",
            must_show=["[data-testid='sidebar-button-your-stuff']"],
            must_not_show=[],
        )


def test_image_intent_is_canonical_provider_neutral_and_not_source_evidence():
    _, _, _, candidates = _evidence()
    candidate = next(item for item in candidates if item["action_kind"] == "open_your_stuff")
    step = _decision(
        candidate,
        step_id="tutorial0-step-01-open-your-stuff",
        sequence=1,
        title="Open Your Stuff",
        student_action="Open Your Stuff in Adobe Express.",
        notice="Your Stuff is where class files are organized.",
        check="The Your Stuff workspace is visible.",
    )
    visual = build_visual_requirement(
        step,
        visual_state="action+result",
        must_show=["Adobe Express workspace", "Your Stuff navigation control"],
        must_not_show=["student names", "email addresses", "support chat"],
    )

    intent = build_image_intent(visual)
    payload = intent.to_dict()

    assert intent.contract_version == IMAGE_INTENT_CONTRACT_ID
    assert intent.authority.execution_authorized is False
    assert intent.authority.external_write_authorized is False
    assert payload["identity"]["contract_version"] == IMAGE_INTENT_CONTRACT_ID
    assert "recording_id" not in json.dumps(payload)
    assert "source_indexes" not in json.dumps(payload)
    assert "provider_prompt" not in payload


def test_visual_provenance_traces_frame_to_modeling_to_semantic_to_recording():
    _, _, _, candidates = _evidence()
    candidate = next(item for item in candidates if item["action_kind"] == "open_your_stuff")
    step = _decision(
        candidate,
        step_id="tutorial0-step-01-open-your-stuff",
        sequence=1,
        title="Open Your Stuff",
        student_action="Open Your Stuff in Adobe Express.",
        notice="Your Stuff is where class files are organized.",
        check="The Your Stuff workspace is visible.",
    )
    visual = build_visual_requirement(
        step,
        visual_state="action",
        must_show=["Adobe Express workspace", "Your Stuff navigation control"],
        must_not_show=["student names"],
    )

    provenance = visual_provenance(visual)

    assert provenance["visual_id"] == "visual:tutorial0-step-01-open-your-stuff"
    assert provenance["modeling_step_id"] == step["step_id"]
    assert provenance["semantic_action_ids"] == step["semantic_action_ids"]
    assert provenance["source_indexes"] == step["source"]["source_indexes"]
    assert len(provenance["recording_sha256"]) == 64


def test_rewrite_provenance_mismatch_fails_closed():
    _, actions, _, _ = _evidence()
    with pytest.raises(ValueError, match="rewrite provenance"):
        build_modeling_candidates(
            recording_id="tutorial-0-bad-rewrite",
            recording_sha256="b" * 64,
            semantic_actions=[actions[0]],
            rewrite_operations=[
                {
                    "kind": "keep",
                    "semantic_action_id": "action-0",
                    "source_indexes": [999],
                    "confidence": "proven",
                }
            ],
        )


def test_missing_provenance_blocks_downstream_visual_readiness():
    with pytest.raises(ValueError, match="required provenance"):
        apply_modeling_decision(
            {"candidate_id": "incomplete"},
            disposition="keep",
            step_id="tutorial0-step-incomplete",
            sequence=1,
            title="Incomplete",
            student_action="Do the thing.",
            notice="Notice the thing.",
            check="The thing is visible.",
        )


def test_raw_recorder_candidate_cannot_be_used_as_picture_perfect_modeling_step():
    _, _, _, candidates = _evidence()
    with pytest.raises(ValueError, match="modeling step"):
        build_visual_requirement(
            candidates[0],
            visual_state="action",
            must_show=["Adobe Express workspace"],
            must_not_show=[],
        )


def test_unsupported_recorder_action_remains_visible_as_uncertainty():
    candidates = build_modeling_candidates(
        recording_id="tutorial-0-unsupported",
        recording_sha256="c" * 64,
        semantic_actions=[
            {
                "kind": "unsupported",
                "source_indexes": [7],
                "target": None,
                "interaction": None,
                "evidence": ["synthetic future Recorder action"],
                "fragile": False,
                "recovery": False,
            }
        ],
    )

    assert candidates[0]["action_kind"] == "unsupported"
    assert candidates[0]["instructional_disposition"] == "undecided"
    assert candidates[0]["rj3_state"] == "pending"
    assert candidates[0]["rj4_state"] == "pending"


def test_noninstructional_modeling_decision_cannot_generate_picture_perfect_visual():
    _, _, _, candidates = _evidence()
    candidate = next(item for item in candidates if item["action_kind"] == "keyboard_noise")
    step = apply_modeling_decision(
        candidate,
        disposition="not-instructional",
        step_id="tutorial0-noise-01",
        sequence=7,
    )

    with pytest.raises(ValueError, match="non-instructional"):
        build_visual_requirement(
            step,
            visual_state="action",
            must_show=["Adobe Express workspace"],
            must_not_show=[],
        )
