import pytest

from scripts.agent_os_replay_json.rewriter import REWRITE_KINDS, RewriteOperation, RewriteRequest, apply_request, rewrite_replay


def test_rewrite_vocabulary_is_finite():
    assert REWRITE_KINDS == {"keep", "remove-noise", "replace-sequence", "move-before", "move-after", "change-selector", "insert-assertion"}


def test_rewrite_operation_preserves_provenance():
    operation = RewriteOperation(kind="remove-noise", semantic_action_id="action-1", source_indexes=(3, 4, 5), evidence=("keyboard correction",), confidence="proven")
    assert operation.source_indexes == (3, 4, 5)
    assert operation.to_dict()["source_indexes"] == [3, 4, 5]


def test_unknown_rewrite_kind_fails_closed():
    with pytest.raises(ValueError, match="unsupported rewrite kind"):
        RewriteOperation(kind="guess", semantic_action_id="action-1", source_indexes=(1,))


def test_missing_source_indexes_fails_closed():
    with pytest.raises(ValueError, match="requires source indexes"):
        RewriteOperation(kind="keep", semantic_action_id="action-1", source_indexes=())


def test_clean_recording_round_trips():
    payload={"steps":[{"type":"navigate","url":"https://example.test"},{"type":"click","selectors":[["aria/Folder"]]}]}
    result=rewrite_replay(payload)
    assert result.rewritten_recording==payload and result.semantic_equivalence=="proven" and result.provenance=={0:(0,),1:(1,)}


def test_keyboard_correction_sequence_collapses_to_final_change():
    payload={"steps":[{"type":"change","value":"My F","selectors":[["[data-testid='editor-document-title']"]]},{"type":"keyDown","key":"ArrowLeft"},{"type":"keyUp","key":"ArrowLeft"},{"type":"change","value":"My First Project","selectors":[["[data-testid='editor-document-title']"]]}]}
    result=rewrite_replay(payload)
    assert result.rewritten_recording["steps"]==[payload["steps"][3]]
    assert result.provenance=={0:(0,1,2,3)} and result.operations[0].kind=="replace-sequence" and result.semantic_equivalence=="proven"


def test_request_validation_basics():
    with pytest.raises(ValueError, match="replacement selector"):
        RewriteRequest(kind="change-selector",semantic_action_id="action-1",source_indexes=(1,))
    with pytest.raises(ValueError, match="target action id"):
        RewriteRequest(kind="move-before",semantic_action_id="action-1",source_indexes=(1,))
    with pytest.raises(ValueError, match="unsupported rewrite request"):
        RewriteRequest(kind="guess",semantic_action_id="action-1",source_indexes=(1,))


def _selector_request(action_id: str):
    return RewriteRequest(kind="change-selector", semantic_action_id=action_id, source_indexes=(0,), replacement_selector="aria/Folder")


@pytest.mark.parametrize("action_id", ["0", "action--1", "action-+0", "action- 0", " action-0", "action-0 ", "action-0junk", "action-01"])
def test_malformed_semantic_action_ids_are_rejected(action_id):
    payload={"steps":[{"type":"click","selectors":[["aria/Folder"]]}]}
    result=apply_request(payload,_selector_request(action_id))
    assert result.semantic_equivalence=="rejected"
    assert result.warnings==("unknown semantic action id",)
    assert result.rewritten_recording==payload


def test_canonical_semantic_action_id_remains_valid():
    payload={"steps":[{"type":"click","selectors":[["aria/Folder"]]}]}
    result=apply_request(payload,_selector_request("action-0"))
    assert result.semantic_equivalence=="proven"


def test_selector_change_cannot_invent_selector():
    payload={"steps":[{"type":"click","selectors":[["#generated-123"]]}]}
    request=RewriteRequest(kind="change-selector",semantic_action_id="action-0",source_indexes=(0,),replacement_selector="[data-testid='invented']")
    assert apply_request(payload,request).semantic_equivalence=="rejected"


def test_request_source_indexes_must_match_analyzer_evidence():
    payload={"steps":[{"type":"click","selectors":[["aria/Folder"]]}]}
    request=RewriteRequest(kind="change-selector",semantic_action_id="action-0",source_indexes=(99,),replacement_selector="aria/Folder")
    assert apply_request(payload,request).semantic_equivalence=="rejected"


def test_keyboard_noise_can_be_removed():
    payload={"steps":[{"type":"keyUp","key":"ArrowLeft"},{"type":"click","selectors":[["aria/Folder"]]}]}
    request=RewriteRequest(kind="remove-noise",semantic_action_id="action-0",source_indexes=(0,))
    result=apply_request(payload,request)
    assert result.semantic_equivalence=="proven" and result.rewritten_recording["steps"]==[payload["steps"][1]]


def test_viewport_and_instructional_actions_cannot_be_removed_as_noise():
    for step in ({"type":"setViewport","width":1200,"height":800},{"type":"click","selectors":[["aria/Folder"]]}):
        payload={"steps":[step]}; request=RewriteRequest(kind="remove-noise",semantic_action_id="action-0",source_indexes=(0,))
        assert apply_request(payload,request).semantic_equivalence=="rejected"


def test_recovery_behavior_cannot_be_removed_as_noise():
    payload={"steps":[{"type":"click","selectors":[["[data-testid='x-loading-view']"]]}]}
    request=RewriteRequest(kind="remove-noise",semantic_action_id="action-0",source_indexes=(0,))
    assert apply_request(payload,request).semantic_equivalence=="rejected"


def test_moves_are_unproven_without_dependency_evidence():
    payload={"steps":[{"type":"click","selectors":[["aria/A"]]},{"type":"click","selectors":[["aria/B"]]}]}
    before=RewriteRequest(kind="move-before",semantic_action_id="action-1",source_indexes=(1,),target_action_id="action-0")
    after=RewriteRequest(kind="move-after",semantic_action_id="action-0",source_indexes=(0,),target_action_id="action-1")
    assert apply_request(payload,before).semantic_equivalence=="unproven"
    assert apply_request(payload,after).semantic_equivalence=="unproven"
