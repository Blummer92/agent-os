from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from workflow_scheduler.planning import (  # noqa: E402
    reconstruct_draft_task_proposal_result,
    serialize_draft_task_proposal_result,
)
from workflow_scheduler.planning.draft_ingestion import (  # noqa: E402
    _draft_task_proposal_result_payload,
)

from test_draft_ingestion import (  # noqa: E402
    _build,
    _handoff,
    _issueplan,
    _repository_state,
)


def test_round_trip_eligible_result():
    result = _build()
    assert result.status == "eligible"
    payload = serialize_draft_task_proposal_result(result)
    assert reconstruct_draft_task_proposal_result(payload) == result


def test_round_trip_blocked_result_with_no_nested_evidence():
    # Missing external evidence is blocked, with no issueplan/repository nested results.
    from workflow_scheduler.planning.draft_ingestion import build_draft_task_proposals

    handoff = _handoff()
    result = build_draft_task_proposals(
        handoff, None, None, created_at="2026-07-20T12:00:00Z"
    )
    assert result.status == "blocked"
    assert result.issueplan_comparison is None
    assert result.repository_state_validation is None
    payload = serialize_draft_task_proposal_result(result)
    assert reconstruct_draft_task_proposal_result(payload) == result


def test_round_trip_stale_result_with_both_nested_results_present():
    handoff, issueplan, binding = _two_phase_stale()
    result = _build(handoff=handoff, issueplan=issueplan)
    assert result.status == "stale"
    assert result.issueplan_comparison is not None
    assert result.repository_state_validation is not None
    payload = serialize_draft_task_proposal_result(result)
    assert reconstruct_draft_task_proposal_result(payload) == result


def _two_phase_stale():
    handoff = _handoff()
    issueplan = _issueplan(
        handoff,
        graph_reference=None,
        planning_result_reference=None,
        handoff_reference=None,
        supplied_node_ids=(),
    )
    return handoff, issueplan, None


def test_serialization_is_deterministic():
    result = _build()
    first = serialize_draft_task_proposal_result(result)
    second = serialize_draft_task_proposal_result(result)
    assert first == second
    assert json.loads(first) == json.loads(second)


def test_reconstruct_from_bytes_str_and_mapping():
    result = _build()
    payload_bytes = serialize_draft_task_proposal_result(result)
    payload_text = payload_bytes.decode("utf-8")
    payload_mapping = _draft_task_proposal_result_payload(result)
    assert reconstruct_draft_task_proposal_result(payload_bytes) == result
    assert reconstruct_draft_task_proposal_result(payload_text) == result
    assert reconstruct_draft_task_proposal_result(payload_mapping) == result


def test_proposal_identity_is_preserved_through_round_trip():
    result = _build()
    payload = serialize_draft_task_proposal_result(result)
    reconstructed = reconstruct_draft_task_proposal_result(payload)
    assert reconstructed.proposals[0].proposal_id == result.proposals[0].proposal_id


def test_reject_unknown_field():
    payload = _draft_task_proposal_result_payload(_build())
    payload["extra"] = "unexpected"
    with pytest.raises(ValueError):
        reconstruct_draft_task_proposal_result(payload)


def test_reject_missing_field():
    payload = _draft_task_proposal_result_payload(_build())
    del payload["status"]
    with pytest.raises(ValueError):
        reconstruct_draft_task_proposal_result(payload)


def test_reject_malformed_status():
    payload = _draft_task_proposal_result_payload(_build())
    payload["status"] = "not-a-real-status"
    with pytest.raises(ValueError):
        reconstruct_draft_task_proposal_result(payload)


def test_reject_proposals_list_drift_for_non_eligible_status():
    payload = _draft_task_proposal_result_payload(_build())
    payload["status"] = "blocked"
    with pytest.raises(ValueError):
        reconstruct_draft_task_proposal_result(payload)


def test_reject_tuple_transport_for_proposals():
    payload = _draft_task_proposal_result_payload(_build())
    payload["proposals"] = tuple(payload["proposals"])
    with pytest.raises(ValueError):
        reconstruct_draft_task_proposal_result(payload)


def test_reject_tuple_transport_for_reason_codes():
    payload = _draft_task_proposal_result_payload(_build())
    payload["reason_codes"] = tuple(payload["reason_codes"])
    with pytest.raises(ValueError):
        reconstruct_draft_task_proposal_result(payload)


def test_reject_authorization_status_drift():
    payload = _draft_task_proposal_result_payload(_build())
    payload["authorization_status"] = "evaluated"
    with pytest.raises(ValueError):
        reconstruct_draft_task_proposal_result(payload)


def test_reject_execution_authorized_drift():
    payload = _draft_task_proposal_result_payload(_build())
    payload["execution_authorized"] = True
    with pytest.raises(ValueError):
        reconstruct_draft_task_proposal_result(payload)


def test_reject_side_effects_performed_drift():
    payload = _draft_task_proposal_result_payload(_build())
    payload["side_effects_performed"] = True
    with pytest.raises(ValueError):
        reconstruct_draft_task_proposal_result(payload)


def test_reject_malformed_nested_handoff_validation():
    payload = _draft_task_proposal_result_payload(_build())
    del payload["handoff_validation"]["outcome"]
    with pytest.raises(ValueError):
        reconstruct_draft_task_proposal_result(payload)


def test_reject_malformed_nested_issueplan_comparison():
    handoff, issueplan, _binding = _two_phase_stale()
    result = _build(handoff=handoff, issueplan=issueplan)
    payload = _draft_task_proposal_result_payload(result)
    assert payload["issueplan_comparison"] is not None
    del payload["issueplan_comparison"]["outcome"]
    with pytest.raises(ValueError):
        reconstruct_draft_task_proposal_result(payload)


def test_reject_malformed_nested_repository_state_validation():
    handoff, issueplan, _binding = _two_phase_stale()
    result = _build(handoff=handoff, issueplan=issueplan)
    payload = _draft_task_proposal_result_payload(result)
    assert payload["repository_state_validation"] is not None
    payload["repository_state_validation"]["outcome"] = "not-a-real-outcome"
    with pytest.raises(ValueError):
        reconstruct_draft_task_proposal_result(payload)


def test_reject_bool_for_repository_id_in_nested_repository_identity():
    handoff, issueplan, _binding = _two_phase_stale()
    result = _build(handoff=handoff, issueplan=issueplan)
    payload = _draft_task_proposal_result_payload(result)
    identity = payload["repository_state_validation"]["repository_identity"]
    if identity is not None:
        identity["repository_id"] = True
        with pytest.raises(ValueError):
            reconstruct_draft_task_proposal_result(payload)


def test_reject_noncanonical_bytes_with_reordered_keys():
    result = _build()
    canonical = serialize_draft_task_proposal_result(result)
    payload = _draft_task_proposal_result_payload(result)
    reordered = dict(reversed(payload.items()))
    reordered_text = json.dumps(reordered, ensure_ascii=False, separators=(",", ":"))
    assert reordered_text.encode("utf-8") != canonical
    with pytest.raises(ValueError):
        reconstruct_draft_task_proposal_result(reordered_text.encode("utf-8"))


def test_reject_noncanonical_text_with_extra_whitespace():
    canonical = serialize_draft_task_proposal_result(_build()).decode("utf-8")
    padded_text = canonical.replace(",", ", ")
    assert padded_text != canonical
    with pytest.raises(ValueError):
        reconstruct_draft_task_proposal_result(padded_text)


def test_serialize_rejects_wrong_type():
    with pytest.raises(TypeError):
        serialize_draft_task_proposal_result(object())


def test_reconstruct_rejects_wrong_type():
    with pytest.raises(TypeError):
        reconstruct_draft_task_proposal_result(123)


def test_wsc3_construction_and_eligibility_behavior_is_unchanged():
    # Reuse of the transport must not alter build_draft_task_proposals behavior.
    from workflow_scheduler.planning.draft_ingestion import build_draft_task_proposals

    handoff = _handoff()
    issueplan = _issueplan(handoff)
    repository = _repository_state()
    result = build_draft_task_proposals(
        handoff, issueplan, repository, created_at="2026-07-20T12:00:00Z"
    )
    assert result.status == "eligible"
    assert len(result.proposals) == 1
    assert result.execution_authorized is False
    assert result.side_effects_performed is False
