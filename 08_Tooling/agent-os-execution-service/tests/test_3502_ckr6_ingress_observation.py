"""#3502: a host never mistakes an unanswered CKR6 ingress request for an admission."""
from __future__ import annotations

import pytest

from agent_os_execution_service import ckr6_github_bridge as bridge

REQUEST = 6325177786


def result_comment(*, status: str, admissible: bool, request: int = REQUEST) -> dict[str, object]:
    result = {
        "operation": "issue-start",
        "repository": "Blummer92/agent-os",
        "issue_number": 3502,
        "status": status,
        "reason_codes": ["knowledge-not-needed"] if admissible else ["connector-surface-unavailable"],
        "selected_lesson_ids": [],
        "canonical_github_refs": [],
        "substantial_hypothesis_admissible": admissible,
        "mutation_admissible": False,
        "execution_authorized": False,
        "github_writes_authorized": False,
        "merge_authorized": False,
        "closure_authorized": False,
        "side_effects_performed": False,
    }
    return {"id": 1, "body": bridge.serialize_ckr6_result_comment(result, request_comment_id=request)}


def observe(**changes):
    value = {"request_comment_id": REQUEST, "issue_comments": []}
    value.update(changes)
    return bridge.classify_ckr6_ingress_observation(**value)


def test_run_39665727697_install_failure_is_ingress_failed_not_an_admission() -> None:
    # Exact observed facts: classify job failed at the install step, execute
    # job skipped, no result comment posted.
    observed = observe(
        run_status="completed",
        run_conclusion="failure",
        failed_step="Install existing Agent OS runtime",
        in_process_route_available=True,
    )
    assert observed["state"] == "ingress-failed"
    assert observed["reason_codes"] == ["ckr6-ingress-failed-before-result:install-existing-agent-os-runtime"]
    assert observed["substantial_hypothesis_admissible"] is False
    assert observed["outcome_synthesized"] is False
    assert observed["next_action"] == "reroute-in-process-ckr6"


def test_ingress_failure_without_capable_surface_is_an_explicit_capability_blocker() -> None:
    observed = observe(run_status="completed", run_conclusion="failure", failed_step="Set up Python")
    assert observed["next_action"] == "report-ckr6-capability-blocker"


@pytest.mark.parametrize(
    ("changes", "state", "action"),
    [
        ({"request_comment_id": None}, "not-attempted", "post-ckr6-request-or-report-ckr6-capability-blocker"),
        ({}, "run-not-observed", "reacquire-ckr6-run"),
        ({"run_status": "in_progress"}, "pending", "await-ckr6-result"),
        ({"run_status": "queued"}, "pending", "await-ckr6-result"),
        ({"run_status": "completed", "run_conclusion": "skipped"}, "request-not-admitted", "repost-bounded-ckr6-request"),
        ({"run_status": "completed", "run_conclusion": "success"}, "result-not-returned", "report-ckr6-capability-blocker"),
    ],
)
def test_unattempted_pending_and_unreturned_states_are_distinct(changes, state, action) -> None:
    observed = observe(**changes)
    assert observed["state"] == state
    assert observed["next_action"] == action
    assert observed["substantial_hypothesis_admissible"] is False


def test_correlated_result_comment_carries_the_canonical_admission() -> None:
    observed = observe(
        issue_comments=[{"id": 9, "body": "unrelated"}, result_comment(status="not-needed", admissible=True)],
        run_status="completed",
        run_conclusion="success",
    )
    assert observed["state"] == "result-returned"
    assert observed["result_status"] == "not-needed"
    assert observed["substantial_hypothesis_admissible"] is True
    assert observed["next_action"] == "consume-ckr6-result"


def test_returned_manual_review_result_is_not_admissible() -> None:
    observed = observe(issue_comments=[result_comment(status="manual-review", admissible=False)])
    assert observed["state"] == "result-returned"
    assert observed["reason_codes"] == ["ckr6-result-returned:manual-review"]
    assert observed["substantial_hypothesis_admissible"] is False


def test_result_for_another_request_or_malformed_comment_is_ignored() -> None:
    observed = observe(
        issue_comments=[
            result_comment(status="not-needed", admissible=True, request=REQUEST + 1),
            {"id": 3, "body": bridge.CKR6_RESULT_MARKER + "\n{not canonical json"},
            {"id": 4, "body": None},
        ],
        run_status="completed",
        run_conclusion="failure",
        failed_step="Install existing Agent OS runtime",
    )
    assert observed["state"] == "ingress-failed"
    assert observed["substantial_hypothesis_admissible"] is False


def test_observation_rejects_malformed_inputs() -> None:
    with pytest.raises(ValueError):
        observe(request_comment_id=0)
    with pytest.raises(TypeError):
        observe(issue_comments=())
    with pytest.raises(ValueError):
        observe(run_status="sideways")
    with pytest.raises(ValueError):
        observe(run_status="completed", failed_step="  ")
    with pytest.raises(TypeError):
        observe(in_process_route_available="yes")
