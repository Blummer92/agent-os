from instructional_workflow_contracts import apply_combined_modeling_decision


def _candidate(action_id, source_indexes, *, fragile=False):
    return {
        "candidate_id": f"candidate:{action_id}",
        "recording_id": "tutorial-0-combine",
        "recording_sha256": "d" * 64,
        "semantic_action_id": action_id,
        "source_indexes": source_indexes,
        "rewrite": {"kind": "keep", "confidence": "proven", "source_indexes": tuple(source_indexes)},
        "rj3_state": "pending",
        "rj4_state": "pending",
        "fragile": fragile,
        "recovery": False,
    }


def test_combine_preserves_every_semantic_action_and_source_index():
    step = apply_combined_modeling_decision(
        [_candidate("action-2", [2]), _candidate("action-3", [3, 4], fragile=True)],
        step_id="tutorial0-step-combined-create-folder",
        sequence=2,
        title="Create the Digital Media folder",
        student_action="Create the folder and give it the class organization name.",
        notice="Creating and naming the folder form one meaningful organization moment.",
        check="The Digital Media folder is visible.",
    )

    assert step["disposition"] == "combine"
    assert step["semantic_action_ids"] == ["action-2", "action-3"]
    assert step["source"]["source_indexes"] == [2, 3, 4]
    assert step["source"]["fragile"] is True
    assert step["execution_authorized"] is False


def test_combine_rejects_cross_recording_candidates():
    first = _candidate("action-2", [2])
    second = _candidate("action-3", [3])
    second["recording_sha256"] = "e" * 64

    try:
        apply_combined_modeling_decision(
            [first, second],
            step_id="tutorial0-invalid-combine",
            sequence=2,
            title="Invalid combine",
            student_action="Do not use this.",
            notice="This should fail.",
            check="No step should be produced.",
        )
    except ValueError as exc:
        assert "share recording identity" in str(exc)
    else:
        raise AssertionError("cross-recording combine must fail closed")
