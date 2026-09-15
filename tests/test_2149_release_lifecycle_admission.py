import importlib.util
import sys
from pathlib import Path

from scripts.agent_os_issue_acceptance.lifecycle_mutation_authorization import (
    LifecycleOwnerDecision,
    produce_lifecycle_mutation_authorization,
)
from scripts.agent_os_issue_acceptance.lifecycle_mutation_guard import LifecycleStateSnapshot

MODULE = Path(__file__).parents[1] / "scripts" / "agent-os-release-run.py"
spec = importlib.util.spec_from_file_location("release_run_2149", MODULE)
release_run = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = release_run
spec.loader.exec_module(release_run)

AGGREGATE = "Agent OS Validation Gate / Run aggregate validation"
ACCEPTANCE = "Agent OS Issue Acceptance Report"
HEAD = "a" * 40
MAIN = "b" * 40


def lifecycle():
    return {
        "reconciliation_status": "converged",
        "invocation_reason": "validation-terminal",
        "planned_head_sha": HEAD,
        "verified_head_sha": HEAD,
        "unmanaged_labels_preserved": ["agent-os"],
    }


def evidence(**changes):
    value = {
        "repository": "Blummer92/agent-os",
        "pull_request_number": 2200,
        "issue_number": 2149,
        "expected_head_sha": HEAD,
        "observed_head_sha": HEAD,
        "current_main_sha": MAIN,
        "validation_head_sha": HEAD,
        "branch_state": "current",
        "pr_state": "merged",
        "pr_lifecycle_state": "merged",
        "issue_state": "open",
        "checkpoint_pr_lifecycle_state": "merged",
        "changed_files": ["scripts/agent-os-release-run.py"],
        "allowed_changed_files": ["scripts/agent-os-release-run.py"],
        "required_checks": {AGGREGATE: "success", ACCEPTANCE: "success"},
        "canonical_required_checks": [AGGREGATE, ACCEPTANCE],
        "authoritative_aggregate_check": AGGREGATE,
        "authorized_merge_method": "squash",
        "review_thread_summary": {"blocking_unresolved": 0},
        "ready_for_review_authorized": True,
        "merge_authorized": True,
        "merge_commit_verified": True,
        "main_verified": True,
        "lifecycle_reconciliation": lifecycle(),
        "side_effects_performed": ["merge"],
    }
    value.update(changes)
    return value


def closure_packet(**snapshot_changes):
    data = dict(
        repository="Blummer92/agent-os",
        issue_number=2149,
        pull_request_number=2200,
        source_head=HEAD,
        base_head=MAIN,
        pr_state="ready",
        merged=True,
        issue_state="open",
        review_state="clear",
        unresolved_threads=0,
        lifecycle_labels=("status:ready",),
        observed_revision="terminal-readback-2149",
    )
    data.update(snapshot_changes)
    snapshot = LifecycleStateSnapshot(**data)
    decision = LifecycleOwnerDecision(
        repository=snapshot.repository,
        issue_number=snapshot.issue_number,
        pull_request_number=snapshot.pull_request_number,
        requested_mutations=("close-issue",),
        authorizer_id="repository-owner",
        decision_id="request-interpretation:2149-release",
        decision_recorded=True,
    )
    authorization = produce_lifecycle_mutation_authorization(decision, snapshot)
    return {"authorization": authorization.to_dict(), "snapshot": snapshot.to_dict()}


def test_legacy_raw_boolean_cannot_authorize_issue_closure():
    state = release_run.evaluate_release_run(evidence(issue_closure_authorized=True))
    assert state.issue_closure_authorized is False
    assert state.phase == "issue-closure-authorization-pause"
    assert state.next_action == "request-issue-closure-authorization"


def test_canonical_lifecycle_admission_authorizes_terminal_progression():
    state = release_run.evaluate_release_run(
        evidence(issue_closure_lifecycle=closure_packet())
    )
    assert state.issue_closure_authorized is True
    assert state.next_action == "post-completion-comment-before-closure"


def test_stale_head_bound_closure_packet_fails_closed():
    state = release_run.evaluate_release_run(
        evidence(issue_closure_lifecycle=closure_packet(source_head="c" * 40))
    )
    assert state.issue_closure_authorized is False
    assert state.next_action == "request-issue-closure-authorization"


def test_wrong_issue_closure_packet_fails_closed():
    state = release_run.evaluate_release_run(
        evidence(issue_closure_lifecycle=closure_packet(issue_number=2150))
    )
    assert state.issue_closure_authorized is False
    assert state.next_action == "request-issue-closure-authorization"


def test_non_authorized_lifecycle_record_cannot_be_smuggled_as_boolean():
    packet = closure_packet()
    packet["authorization"]["state"] = "consumed"
    packet["authorization"]["authorization_id"] = ""
    packet["authorization"]["authorization_revision"] = ""
    state = release_run.evaluate_release_run(
        evidence(issue_closure_lifecycle=packet, issue_closure_authorized=True)
    )
    assert state.issue_closure_authorized is False
    assert state.next_action == "request-issue-closure-authorization"
