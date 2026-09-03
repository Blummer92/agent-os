import pytest

from scripts.agent_os_replay_json.rewriter import REWRITE_KINDS, RewriteOperation


def test_rewrite_vocabulary_is_finite():
    assert REWRITE_KINDS == {
        "keep",
        "remove-noise",
        "replace-sequence",
        "move-before",
        "move-after",
        "change-selector",
        "insert-assertion",
    }


def test_rewrite_operation_preserves_provenance():
    operation = RewriteOperation(
        kind="remove-noise",
        semantic_action_id="action-1",
        source_indexes=(3, 4, 5),
        evidence=("keyboard correction",),
        confidence="proven",
    )

    assert operation.source_indexes == (3, 4, 5)
    assert operation.to_dict()["source_indexes"] == [3, 4, 5]


def test_unknown_rewrite_kind_fails_closed():
    with pytest.raises(ValueError, match="unsupported rewrite kind"):
        RewriteOperation(
            kind="guess",
            semantic_action_id="action-1",
            source_indexes=(1,),
        )


def test_missing_source_indexes_fails_closed():
    with pytest.raises(ValueError, match="requires source indexes"):
        RewriteOperation(
            kind="keep",
            semantic_action_id="action-1",
            source_indexes=(),
        )


from scripts.agent_os_replay_json.rewriter import rewrite_replay


def test_clean_recording_round_trips():
    payload = {
        "steps": [
            {"type": "navigate", "url": "https://example.test"},
            {"type": "click", "selectors": [["aria/Folder"]]},
        ]
    }

    result = rewrite_replay(payload)

    assert result.rewritten_recording == payload
    assert result.semantic_equivalence == "proven"
    assert result.provenance == {0: (0,), 1: (1,)}


def test_keyboard_correction_sequence_collapses_to_final_change():
    payload = {
        "steps": [
            {
                "type": "change",
                "value": "My F",
                "selectors": [["[data-testid='editor-document-title']"]],
            },
            {"type": "keyDown", "key": "ArrowLeft"},
            {"type": "keyUp", "key": "ArrowLeft"},
            {
                "type": "change",
                "value": "My First Project",
                "selectors": [["[data-testid='editor-document-title']"]],
            },
        ]
    }

    result = rewrite_replay(payload)

    assert result.rewritten_recording["steps"] == [payload["steps"][3]]
    assert result.provenance == {0: (0, 1, 2, 3)}
    assert result.operations[0].kind == "replace-sequence"
    assert result.semantic_equivalence == "proven"

def test_click_and_double_click_are_preserved():
    payload = {
        "steps": [
            {"type": "click", "selectors": [["aria/Folder"]]},
            {"type": "doubleClick", "selectors": [["aria/Folder"]]},
        ]
    }

    result = rewrite_replay(payload)

    assert result.rewritten_recording["steps"][0]["type"] == "click"
    assert result.rewritten_recording["steps"][1]["type"] == "doubleClick"


def test_recovery_steps_are_preserved():
    payload = {
        "steps": [
            {"type": "click", "selectors": [["[data-testid='x-loading-view']"]]},
        ]
    }

    result = rewrite_replay(payload)

    assert result.rewritten_recording == payload
    assert result.operations[0].kind == "keep"


def test_unsupported_steps_are_preserved():
    payload = {
        "steps": [
            {"type": "mysteryStep", "value": "keep-me"},
        ]
    }

    result = rewrite_replay(payload)

    assert result.rewritten_recording == payload
    assert result.operations[0].kind == "keep"


def test_missing_steps_fails_closed():
    import pytest

    with pytest.raises(ValueError, match="steps"):
        rewrite_replay({})


from scripts.agent_os_replay_json.rewriter import RewriteRequest


def test_selector_change_requires_explicit_selector():
    with pytest.raises(ValueError, match="replacement selector"):
        RewriteRequest(
            kind="change-selector",
            semantic_action_id="action-1",
            source_indexes=(1,),
        )


def test_reorder_requires_explicit_target():
    with pytest.raises(ValueError, match="target action id"):
        RewriteRequest(
            kind="move-before",
            semantic_action_id="action-1",
            source_indexes=(1,),
        )


def test_valid_explicit_selector_request():
    request = RewriteRequest(
        kind="change-selector",
        semantic_action_id="action-1",
        source_indexes=(1,),
        evidence=("recorded selector alternative",),
        replacement_selector="[data-testid='folder-card']",
    )

    assert request.replacement_selector == "[data-testid='folder-card']"


def test_guessing_is_not_a_valid_request():
    with pytest.raises(ValueError, match="unsupported rewrite request"):
        RewriteRequest(
            kind="guess",
            semantic_action_id="action-1",
            source_indexes=(1,),
        )


from scripts.agent_os_replay_json.rewriter import RewriteRequest


def test_selector_change_requires_explicit_selector():
    with pytest.raises(ValueError, match="replacement selector"):
        RewriteRequest(
            kind="change-selector",
            semantic_action_id="action-1",
            source_indexes=(1,),
        )


def test_reorder_requires_explicit_target():
    with pytest.raises(ValueError, match="target action id"):
        RewriteRequest(
            kind="move-before",
            semantic_action_id="action-1",
            source_indexes=(1,),
        )


def test_valid_explicit_selector_request():
    request = RewriteRequest(
        kind="change-selector",
        semantic_action_id="action-1",
        source_indexes=(1,),
        evidence=("recorded selector alternative",),
        replacement_selector="[data-testid='folder-card']",
    )

    assert request.replacement_selector == "[data-testid='folder-card']"


def test_guessing_is_not_a_valid_request():
    with pytest.raises(ValueError, match="unsupported rewrite request"):
        RewriteRequest(
            kind="guess",
            semantic_action_id="action-1",
            source_indexes=(1,),
        )


from scripts.agent_os_replay_json.rewriter import apply_request


def test_selector_change_uses_only_recorded_selector_evidence():
    payload = {
        "steps": [
            {
                "type": "click",
                "selectors": [
                    ["[data-testid='folder-card']", "#generated-123"]
                ],
            }
        ]
    }

    request = RewriteRequest(
        kind="change-selector",
        semantic_action_id="action-0",
        source_indexes=(0,),
        replacement_selector="[data-testid='folder-card']",
    )

    result = apply_request(payload, request)

    assert result.semantic_equivalence == "proven"
    assert result.rewritten_recording["steps"][0]["selectors"] == [
        ["[data-testid='folder-card']"]
    ]
    assert result.operations[0].changes_selector is True


def test_selector_change_cannot_invent_selector():
    payload = {
        "steps": [
            {
                "type": "click",
                "selectors": [["#generated-123"]],
            }
        ]
    }

    request = RewriteRequest(
        kind="change-selector",
        semantic_action_id="action-0",
        source_indexes=(0,),
        replacement_selector="[data-testid='invented']",
    )

    result = apply_request(payload, request)

    assert result.semantic_equivalence == "rejected"
    assert result.rewritten_recording == payload


def test_request_source_indexes_must_match_analyzer_evidence():
    payload = {
        "steps": [
            {"type": "click", "selectors": [["aria/Folder"]]},
        ]
    }

    request = RewriteRequest(
        kind="change-selector",
        semantic_action_id="action-0",
        source_indexes=(99,),
        replacement_selector="aria/Folder",
    )

    result = apply_request(payload, request)

    assert result.semantic_equivalence == "rejected"


@pytest.mark.parametrize(
    "action_id",
    ["0", "action--1", "action-+0", "action- 0", " action-0", "action-0 ", "action-0junk", "action-01"],
)
def test_malformed_semantic_action_ids_are_rejected(action_id):
    payload = {
        "steps": [
            {"type": "click", "selectors": [["aria/Folder"]]},
        ]
    }
    request = RewriteRequest(
        kind="change-selector",
        semantic_action_id=action_id,
        source_indexes=(0,),
        replacement_selector="aria/Folder",
    )

    result = apply_request(payload, request)

    assert result.semantic_equivalence == "rejected"
    assert result.warnings == ("unknown semantic action id",)
    assert result.rewritten_recording == payload


def test_canonical_semantic_action_id_remains_valid():
    payload = {
        "steps": [
            {"type": "click", "selectors": [["aria/Folder"]]},
        ]
    }
    request = RewriteRequest(
        kind="change-selector",
        semantic_action_id="action-0",
        source_indexes=(0,),
        replacement_selector="aria/Folder",
    )

    result = apply_request(payload, request)

    assert result.semantic_equivalence == "proven"


def test_keyboard_noise_can_be_removed():
    payload = {
        "steps": [
            {"type": "keyUp", "key": "ArrowLeft"},
            {"type": "click", "selectors": [["aria/Folder"]]},
        ]
    }

    request = RewriteRequest(
        kind="remove-noise",
        semantic_action_id="action-0",
        source_indexes=(0,),
    )

    result = apply_request(payload, request)

    assert result.semantic_equivalence == "proven"
    assert result.rewritten_recording["steps"] == [payload["steps"][1]]
    assert result.operations[0].kind == "remove-noise"


def test_viewport_infrastructure_cannot_be_removed_as_noise():
    payload = {"steps": [{"type": "setViewport", "width": 1200, "height": 800}]}

    request = RewriteRequest(
        kind="remove-noise",
        semantic_action_id="action-0",
        source_indexes=(0,),
    )

    result = apply_request(payload, request)

    assert result.semantic_equivalence == "rejected"
    assert result.rewritten_recording == payload


def test_recovery_behavior_cannot_be_removed_as_noise():
    payload = {
        "steps": [
            {
                "type": "click",
                "selectors": [["[data-testid='x-loading-view']"]],
            }
        ]
    }

    request = RewriteRequest(
        kind="remove-noise",
        semantic_action_id="action-0",
        source_indexes=(0,),
    )

    result = apply_request(payload, request)

    assert result.semantic_equivalence == "rejected"
    assert result.rewritten_recording == payload


def test_instructional_action_cannot_be_removed_as_noise():
    payload = {
        "steps": [
            {"type": "click", "selectors": [["aria/Folder"]]},
        ]
    }

    request = RewriteRequest(
        kind="remove-noise",
        semantic_action_id="action-0",
        source_indexes=(0,),
    )

    result = apply_request(payload, request)

    assert result.semantic_equivalence == "rejected"
    assert result.rewritten_recording == payload

def test_move_before_is_unproven_without_dependency_evidence():
    payload = {
        "steps": [
            {"type": "click", "selectors": [["aria/A"]]},
            {"type": "click", "selectors": [["aria/B"]]},
        ]
    }

    request = RewriteRequest(
        kind="move-before",
        semantic_action_id="action-1",
        source_indexes=(1,),
        target_action_id="action-0",
    )

    result = apply_request(payload, request)

    assert result.semantic_equivalence == "unproven"
    assert result.rewritten_recording == payload


def test_move_after_is_unproven_without_dependency_evidence():
    payload = {
        "steps": [
            {"type": "click", "selectors": [["aria/A"]]},
            {"type": "click", "selectors": [["aria/B"]]},
        ]
    }

    request = RewriteRequest(
        kind="move-after",
        semantic_action_id="action-0",
        source_indexes=(0,),
        target_action_id="action-1",
    )

    result = apply_request(payload, request)

    assert result.semantic_equivalence == "unproven"
    assert result.rewritten_recording == payload
