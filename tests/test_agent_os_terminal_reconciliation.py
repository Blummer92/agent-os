import importlib.util
import sys
from pathlib import Path

MODULE = Path(__file__).parents[1] / "scripts" / "agent-os-release-run.py"
spec = importlib.util.spec_from_file_location("release_run_terminal", MODULE)
release_run = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = release_run
spec.loader.exec_module(release_run)

AGGREGATE = "Agent OS Validation Gate / Run aggregate validation"
ACCEPTANCE = "Agent OS Issue Acceptance Report"
HEAD = "a" * 40
MAIN = "b" * 40
LEASE_ID = "pilot-lease:owned"
HOLDER_ID = "pilot-holder:owned"
GENERATION = 7


def lifecycle(reason="validation-terminal"):
    return {
        "reconciliation_status": "converged",
        "invocation_reason": reason,
        "planned_head_sha": HEAD,
        "verified_head_sha": HEAD,
        "unmanaged_labels_preserved": ["agent-os"],
    }


def lease_receipt(**overrides):
    value = {
        "released": True,
        "lease_identity": LEASE_ID,
        "holder_identity": HOLDER_ID,
        "generation": GENERATION,
        "ambiguous": False,
        "forced": False,
    }
    value.update(overrides)
    return value


def evidence(**overrides):
    value = {
        "repository": "Blummer92/agent-os",
        "pull_request_number": 1311,
        "issue_number": 1309,
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
        "issue_closure_authorized": True,
        "merge_commit_verified": True,
        "main_verified": True,
        "lifecycle_reconciliation": lifecycle(),
        "side_effects_performed": ["merge"],
    }
    value.update(overrides)
    return value


def test_terminal_reconciliation_starts_with_completion_pointer():
    state = release_run.evaluate_release_run(evidence())
    assert state.phase == "terminal-reconciliation"
    assert state.next_action == "post-completion-comment-before-closure"


def test_completion_pointer_then_terminalizes_existing_lineage():
    state = release_run.evaluate_release_run(
        evidence(side_effects_performed=["merge", "completion-comment"])
    )
    assert state.next_action == "terminalize-current-lineage-via-checkpoint-owner"


def test_terminal_reconciliation_requires_explicit_lease_disposition():
    state = release_run.evaluate_release_run(
        evidence(
            side_effects_performed=[
                "merge",
                "completion-comment",
                "lineage-terminalized",
            ]
        )
    )
    assert "terminal lease disposition evidence is missing" in state.blockers
    assert state.next_action == "reacquire-terminal-lease-disposition"


def test_owned_lease_must_release_through_exact_identity_receipt():
    state = release_run.evaluate_release_run(
        evidence(
            side_effects_performed=[
                "merge",
                "completion-comment",
                "lineage-terminalized",
            ],
            lease_release_required=True,
            lease_identity=LEASE_ID,
            lease_holder_identity=HOLDER_ID,
            lease_generation=GENERATION,
        )
    )
    assert state.next_action == "release-exactly-owned-lease"


def test_mismatched_forced_or_ambiguous_lease_release_fails_closed():
    cases = (
        lease_receipt(generation=GENERATION + 1),
        lease_receipt(forced=True),
        lease_receipt(ambiguous=True),
        lease_receipt(released=False),
    )
    for receipt in cases:
        state = release_run.evaluate_release_run(
            evidence(
                side_effects_performed=[
                    "merge",
                    "completion-comment",
                    "lineage-terminalized",
                ],
                lease_release_required=True,
                lease_identity=LEASE_ID,
                lease_holder_identity=HOLDER_ID,
                lease_generation=GENERATION,
                lease_release_receipt=receipt,
            )
        )
        assert state.classification == "BLOCKED"
        assert state.next_action == "reacquire-terminal-lease-evidence"


def test_proven_no_lease_or_exact_release_allows_issue_closure():
    no_lease = release_run.evaluate_release_run(
        evidence(
            side_effects_performed=[
                "merge",
                "completion-comment",
                "lineage-terminalized",
            ],
            lease_release_required=False,
        )
    )
    assert no_lease.next_action == "close-issue"

    released = release_run.evaluate_release_run(
        evidence(
            side_effects_performed=[
                "merge",
                "completion-comment",
                "lineage-terminalized",
            ],
            lease_release_required=True,
            lease_identity=LEASE_ID,
            lease_holder_identity=HOLDER_ID,
            lease_generation=GENERATION,
            lease_release_receipt=lease_receipt(),
        )
    )
    assert released.next_action == "close-issue"


def test_closed_issue_requires_final_existing_lifecycle_reconciliation():
    state = release_run.evaluate_release_run(
        evidence(
            issue_state="closed",
            side_effects_performed=[
                "merge",
                "completion-comment",
                "lineage-terminalized",
                "close-issue",
            ],
            lease_release_required=False,
        )
    )
    assert "terminal projection reconciliation receipt is missing" in state.blockers
    assert state.next_action == "reconcile-terminal-projections-via-existing-lifecycle"


def test_terminal_reconciliation_finishes_with_one_final_report():
    before_report = evidence(
        issue_state="closed",
        side_effects_performed=[
            "merge",
            "completion-comment",
            "lineage-terminalized",
            "close-issue",
        ],
        lease_release_required=False,
        terminal_lifecycle_reconciliation=lifecycle("final-state-readback"),
    )
    pending = release_run.evaluate_release_run(before_report)
    assert pending.next_action == "emit-final-report"

    complete_evidence = dict(before_report)
    complete_evidence["side_effects_performed"] = [
        *before_report["side_effects_performed"],
        "final-report",
    ]
    first = release_run.evaluate_release_run(complete_evidence)
    second = release_run.evaluate_release_run(complete_evidence)
    assert first == second
    assert first.phase == "terminal-complete"
    assert first.classification == "COMPLETED"
    assert first.terminal_reconciliation_status == "converged"
    assert first.next_action == "none"
