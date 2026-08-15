import importlib.util
import sys
from pathlib import Path

MODULE = Path(__file__).parents[1] / "scripts" / "agent-os-release-run.py"
spec = importlib.util.spec_from_file_location("release_run", MODULE)
release_run = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = release_run
spec.loader.exec_module(release_run)


def evidence(**overrides):
    base = {
        "repository": "Blummer92/agent-os",
        "pull_request_number": 123,
        "issue_number": 903,
        "expected_head_sha": "a" * 40,
        "observed_head_sha": "a" * 40,
        "pr_state": "open",
        "issue_state": "open",
        "changed_files": ["scripts/agent-os-release-run.py"],
        "allowed_changed_files": ["scripts/agent-os-release-run.py"],
        "required_checks": {"validation": "success"},
        "review_thread_summary": {"blocking_unresolved": 0, "resolved": 1},
        "ready_for_review_authorized": True,
        "merge_authorized": False,
        "issue_closure_authorized": False,
    }
    base.update(overrides)
    return base


def test_exact_head_success_reaches_merge_authorization_pause():
    state = release_run.evaluate_release_run(evidence())
    assert state.phase == "merge-authorization-pause"
    assert state.classification == "READY_FOR_MERGE_AUTHORIZATION"


def test_head_drift_fails_closed():
    state = release_run.evaluate_release_run(evidence(observed_head_sha="b" * 40))
    assert "exact-head drift" in state.blockers
    assert state.classification == "BLOCKED"


def test_every_non_success_required_check_blocks():
    for status in ("missing", "pending", "skipped", "cancelled", "timed_out", "failed"):
        state = release_run.evaluate_release_run(evidence(required_checks={"required": status}))
        assert state.classification == "BLOCKED"


def test_prior_head_green_does_not_satisfy_current_head():
    state = release_run.evaluate_release_run(evidence(prior_head_only_green=True))
    assert "prior-head checks cannot satisfy current head" in state.blockers


def test_requested_changes_and_blocking_thread_block():
    requested = release_run.evaluate_release_run(evidence(requested_changes=True))
    threaded = release_run.evaluate_release_run(evidence(review_thread_summary={"blocking_unresolved": 1}))
    assert requested.classification == "BLOCKED"
    assert threaded.classification == "BLOCKED"


def test_ready_for_review_requires_authorization():
    state = release_run.evaluate_release_run(evidence(ready_for_review_authorized=False))
    assert state.phase == "ready-for-review"
    assert state.next_action == "request-ready-for-review-authorization"


def test_merge_requires_separate_authorization():
    state = release_run.evaluate_release_run(evidence(merge_authorized=False))
    assert state.phase == "merge-authorization-pause"
    assert state.next_action == "request-merge-authorization"


def test_merge_action_is_exact_head_and_method_bounded():
    state = release_run.evaluate_release_run(evidence(merge_authorized=True))
    assert state.phase == "merge"
    assert "expected-head" in state.next_action


def test_post_merge_verification_fails_closed():
    state = release_run.evaluate_release_run(evidence(pr_state="merged", merge_commit_verified=False, main_verified=True))
    assert state.phase == "post-merge-verification"
    assert state.classification == "BLOCKED"


def test_issue_closure_requires_separate_authorization():
    state = release_run.evaluate_release_run(evidence(pr_state="merged", merge_commit_verified=True, main_verified=True))
    assert state.phase == "issue-closure-authorization-pause"


def test_completion_comment_precedes_closure():
    state = release_run.evaluate_release_run(evidence(pr_state="merged", merge_commit_verified=True, main_verified=True, issue_closure_authorized=True))
    assert state.next_action == "post-completion-comment-before-closure"


def test_side_effects_are_explicit_and_deterministic():
    item = evidence(side_effects_performed=["ready-for-review"])
    first = release_run.evaluate_release_run(item)
    second = release_run.evaluate_release_run(item)
    assert first == second
    assert first.side_effects_performed == ["ready-for-review"]


def test_scope_drift_blocks():
    state = release_run.evaluate_release_run(evidence(changed_files=[".github/workflows/nope.yml"]))
    assert "changed-file scope drift" in state.blockers


def test_no_implicit_dangerous_actions_exist():
    state = release_run.evaluate_release_run(evidence())
    text = repr(state)
    for action in ("branch-delete", "workflow-rerun", "review-dismissal", "auto-merge", "bypass"):
        assert action not in state.side_effects_performed
        assert action not in state.next_action
