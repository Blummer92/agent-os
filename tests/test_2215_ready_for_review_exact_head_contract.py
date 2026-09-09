import importlib.util
import sys
from pathlib import Path

MODULE = Path(__file__).parents[1] / "scripts" / "agent-os-release-run.py"
spec = importlib.util.spec_from_file_location("release_run_2215", MODULE)
release_run = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = release_run
spec.loader.exec_module(release_run)

AGGREGATE = "Agent OS Validation Gate / Run aggregate validation"
ACCEPTANCE = "Agent OS Issue Acceptance Report"
HEAD = "a" * 40
MAIN = "b" * 40


def _lifecycle():
    return {"reconciliation_status": "converged", "invocation_reason": "validation-terminal", "verified_head_sha": HEAD}


def _evidence(**overrides):
    base = {
        "repository": "Blummer92/agent-os", "pull_request_number": 2217, "issue_number": 2215,
        "expected_head_sha": HEAD, "observed_head_sha": HEAD, "current_main_sha": MAIN,
        "validation_head_sha": HEAD, "branch_state": "current", "pr_state": "open",
        "pr_lifecycle_state": "draft", "issue_state": "open",
        "changed_files": ["tests/test_2215_ready_for_review_exact_head_contract.py"],
        "allowed_changed_files": ["tests/test_2215_ready_for_review_exact_head_contract.py"],
        "required_checks": {AGGREGATE: "success", ACCEPTANCE: "success"},
        "canonical_required_checks": [AGGREGATE, ACCEPTANCE], "authoritative_aggregate_check": AGGREGATE,
        "authorized_merge_method": "squash", "review_thread_summary": {"blocking_unresolved": 0},
        "ready_for_review_authorized": True, "merge_authorized": False, "issue_closure_authorized": False,
        "lifecycle_reconciliation": _lifecycle(),
    }
    base.update(overrides)
    return base


def test_draft_ready_reuses_current_exact_head_green_aggregate():
    state = release_run.evaluate_release_run(_evidence())
    assert state.phase == "ready-for-review"
    assert state.next_action == "perform-ready-for-review-at-exact-head"
    assert state.blockers == []


def test_draft_ready_missing_aggregate_fails_closed_instead_of_admitting_ready():
    state = release_run.evaluate_release_run(_evidence(required_checks={ACCEPTANCE: "success"}))
    assert f"required check {AGGREGATE} is missing" in state.blockers
    assert state.next_action == "resolve-or-reacquire-blocking-evidence"


def test_draft_ready_stale_aggregate_head_fails_closed():
    state = release_run.evaluate_release_run(_evidence(validation_head_sha="c" * 40))
    assert "authoritative validation is bound to a stale head" in state.blockers
    assert state.next_action == "resolve-or-reacquire-blocking-evidence"
