"""#3153 contract tests: bounded redacted failed-command diagnostic evidence.

A governed PR refresh that fails validation after a successful branch mutation
must preserve bounded, redacted child-command diagnostics so an operator can
distinguish a test failure from an unavailable test runtime. These tests pin the
projection at every seam: executor result, receipt, and artifact payload.
"""
from __future__ import annotations

from dataclasses import asdict, replace

from scripts.agent_os_github_git_objects.branch_update import BranchUpdateObservation


SHA = "a" * 40
COMMAND_ID = "pytest:pr-branch-refresh"


class _SequenceRunner:
    def __init__(self, observations):
        self.observations = list(observations)
        self.calls = []

    def run(self, argv, *, cwd, env):
        self.calls.append((argv, cwd, env))
        return self.observations.pop(0)


def _executor(runner):
    from scripts.agent_os_issue_labels.pr_branch_refresh_operator import (
        ClosedBranchRefreshValidationExecutor,
    )

    return ClosedBranchRefreshValidationExecutor(runner, "/repo")


def _head_ok():
    return BranchUpdateObservation(
        started=True, return_code=0, timed_out=False,
        termination_confirmed=True, stdout=SHA + "\n", stderr="",
    )


def test_failed_command_projects_exit_code_and_tails():
    runner = _SequenceRunner([
        _head_ok(),
        BranchUpdateObservation(
            started=True, return_code=3, timed_out=False,
            termination_confirmed=True,
            stdout="tests/agent_os_issue_labels/test_x.py F\n3 failed\n",
            stderr="E   AssertionError: expected 1, got 2\n",
        ),
    ])
    result = _executor(runner).run_required_validation(
        "Blummer92/agent-os", 3153, head_sha=SHA, command_ids=(COMMAND_ID,),
    )
    assert result.status == "failing"
    assert result.failed_command_id == COMMAND_ID
    assert result.failure_reason == "command-nonzero-exit"
    assert result.failed_command_exit_code == 3
    assert result.failed_command_stdout_tail == "tests/agent_os_issue_labels/test_x.py F\n3 failed"
    assert result.failed_command_stderr_tail == "E   AssertionError: expected 1, got 2"
    assert result.evidence_unavailable_reason is None


def test_missing_runtime_records_evidence_unavailable_not_silence():
    runner = _SequenceRunner([
        _head_ok(),
        BranchUpdateObservation(
            started=False, return_code=None, timed_out=False,
            termination_confirmed=True, stderr="FileNotFoundError:python3",
        ),
    ])
    result = _executor(runner).run_required_validation(
        "Blummer92/agent-os", 3153, head_sha=SHA, command_ids=(COMMAND_ID,),
    )
    assert result.status == "failing"
    assert result.failure_reason == "command-not-started"
    assert result.failed_command_exit_code is None
    assert result.failed_command_stdout_tail is None
    assert result.failed_command_stderr_tail is None
    # Explicit reason: the runtime was missing, not "the tests failed silently".
    assert result.evidence_unavailable_reason == "command-not-started"


def test_unconfirmed_termination_is_first_class_distinct_from_nonzero_exit():
    runner = _SequenceRunner([
        _head_ok(),
        BranchUpdateObservation(
            started=True, return_code=None, timed_out=False,
            termination_confirmed=False, stdout="partial-output",
        ),
    ])
    result = _executor(runner).run_required_validation(
        "Blummer92/agent-os", 3153, head_sha=SHA, command_ids=(COMMAND_ID,),
    )
    assert result.failure_reason == "command-termination-unconfirmed"
    assert result.failed_command_exit_code is None
    assert result.failed_command_stdout_tail is None
    assert result.evidence_unavailable_reason == "command-termination-unconfirmed"


def test_timeout_projects_partial_output_with_timeout_reason():
    runner = _SequenceRunner([
        _head_ok(),
        BranchUpdateObservation(
            started=True, return_code=None, timed_out=True,
            termination_confirmed=False,
            stdout="collected 10 items\nrunning test_1\n", stderr="",
        ),
    ])
    result = _executor(runner).run_required_validation(
        "Blummer92/agent-os", 3153, head_sha=SHA, command_ids=(COMMAND_ID,),
    )
    assert result.status == "failing"
    assert result.failure_reason == "command-timeout"
    assert result.failed_command_exit_code is None
    assert result.failed_command_stdout_tail == "collected 10 items\nrunning test_1"
    assert result.evidence_unavailable_reason == "command-timeout"


def test_oversized_output_cap_is_enforced_byte_exactly():
    runner = _SequenceRunner([
        _head_ok(),
        BranchUpdateObservation(
            started=True, return_code=1, timed_out=False,
            termination_confirmed=True, stdout="", stderr="x" * 10000,
        ),
    ])
    result = _executor(runner).run_required_validation(
        "Blummer92/agent-os", 3153, head_sha=SHA, command_ids=(COMMAND_ID,),
    )
    tail = result.failed_command_stderr_tail
    assert tail is not None
    assert len(tail) == 4096
    assert tail == "x" * 4096


def test_output_line_cap_keeps_most_recent_lines():
    lines = [f"line-{index}" for index in range(500)]
    runner = _SequenceRunner([
        _head_ok(),
        BranchUpdateObservation(
            started=True, return_code=1, timed_out=False,
            termination_confirmed=True, stdout="\n".join(lines), stderr="",
        ),
    ])
    result = _executor(runner).run_required_validation(
        "Blummer92/agent-os", 3153, head_sha=SHA, command_ids=(COMMAND_ID,),
    )
    kept = result.failed_command_stdout_tail.splitlines()
    assert len(kept) == 200
    assert kept[0] == "line-300"
    assert kept[-1] == "line-499"


def test_secret_canary_is_redacted_in_projected_evidence():
    canary = "ghp_canarytestsecret0123456789abcdef"
    runner = _SequenceRunner([
        _head_ok(),
        BranchUpdateObservation(
            started=True, return_code=1, timed_out=False,
            termination_confirmed=True, stdout="",
            stderr=f"error: bad token={canary} rejected\n",
        ),
    ])
    result = _executor(runner).run_required_validation(
        "Blummer92/agent-os", 3153, head_sha=SHA, command_ids=(COMMAND_ID,),
    )
    tail = result.failed_command_stderr_tail
    assert canary not in tail
    assert "[redacted]" in tail
    # The raw secret must not survive anywhere in the serialized result either.
    from scripts.agent_os_issue_labels.pr_branch_refresh_actions_runner import (
        _receipt_dict,
    )
    from scripts.agent_os_issue_labels.pr_branch_refresh_operator import (
        _receipt_from_result,
    )
    from scripts.agent_os_issue_labels.pr_branch_refresh import (
        PullRequestBranchRefreshResult,
    )

    receipt = _receipt_from_result(
        result=PullRequestBranchRefreshResult(
            repository="Blummer92/agent-os", pr_number=3153, status="validation-failing",
            old_head_sha=SHA, new_head_sha=SHA,
            invalidated_head_evidence=("tested-sha",), validation=result,
            reason_codes=("branch.current-proven", "head-evidence.invalidated", "refresh.rebased"),
            branch_refresh_authorized=True, side_effects_performed=True,
            mutation_attempted=True,
        ),
        authorization_id="auth:3153",
        admitted_main_sha="b" * 40,
    )
    assert canary not in str(_receipt_dict(receipt))


def test_golden_fixture_fixed_observation_yields_fixed_result():
    runner = _SequenceRunner([
        _head_ok(),
        BranchUpdateObservation(
            started=True, return_code=2, timed_out=False,
            termination_confirmed=True,
            stdout="2 failed, 10 passed in 1.23s\n",
            stderr="short test summary info\n",
        ),
    ])
    result = _executor(runner).run_required_validation(
        "Blummer92/agent-os", 3153, head_sha=SHA, command_ids=(COMMAND_ID,),
    )
    assert asdict(result) == {
        "head_sha": SHA,
        "status": "failing",
        "command_ids": (COMMAND_ID,),
        "failed_command_id": COMMAND_ID,
        "failure_reason": "command-nonzero-exit",
        "failed_command_exit_code": 2,
        "failed_command_stdout_tail": "2 failed, 10 passed in 1.23s",
        "failed_command_stderr_tail": "short test summary info",
        "evidence_unavailable_reason": None,
    }


def test_receipt_projects_evidence_through_unchanged_chain():
    from scripts.agent_os_issue_labels.pr_branch_refresh import (
        BranchRefreshValidationResult,
        PullRequestBranchRefreshResult,
    )
    from scripts.agent_os_issue_labels.pr_branch_refresh_actions_runner import (
        _receipt_dict,
    )
    from scripts.agent_os_issue_labels.pr_branch_refresh_operator import (
        _receipt_from_result,
    )

    validation = BranchRefreshValidationResult(
        head_sha="c" * 40, status="failing", command_ids=(COMMAND_ID,),
        failed_command_id=COMMAND_ID, failure_reason="command-nonzero-exit",
        failed_command_exit_code=1,
        failed_command_stdout_tail="1 failed",
        failed_command_stderr_tail="E boom",
        evidence_unavailable_reason=None,
    )
    receipt = _receipt_from_result(
        result=PullRequestBranchRefreshResult(
            repository="Blummer92/agent-os", pr_number=3153, status="validation-failing",
            old_head_sha="a" * 40, new_head_sha="c" * 40,
            invalidated_head_evidence=("tested-sha",), validation=validation,
            reason_codes=("branch.current-proven", "head-evidence.invalidated", "refresh.rebased"),
            branch_refresh_authorized=True, side_effects_performed=True,
            mutation_attempted=True,
        ),
        authorization_id="auth:3153",
        admitted_main_sha="b" * 40,
    )
    payload = _receipt_dict(receipt)
    assert payload["validation_status"] == "failing"
    assert payload["validation_failed_command_id"] == COMMAND_ID
    assert payload["validation_failure_reason"] == "command-nonzero-exit"
    assert payload["validation_failed_command_exit_code"] == 1
    assert payload["validation_failed_command_stdout_tail"] == "1 failed"
    assert payload["validation_failed_command_stderr_tail"] == "E boom"
    assert payload["validation_evidence_unavailable_reason"] is None
    # Existing chain keys are unchanged.
    assert payload["status"] == "validation-failing"
    assert payload["mutation_count"] == 1
    assert payload["authorization_consumed"] is True


def test_green_result_carries_no_evidence():
    runner = _SequenceRunner([_head_ok(), _head_ok(), _head_ok()])
    result = _executor(runner).run_required_validation(
        "Blummer92/agent-os", 3153, head_sha=SHA, command_ids=(COMMAND_ID,),
    )
    assert result.status == "green"
    assert result.failed_command_exit_code is None
    assert result.failed_command_stdout_tail is None
    assert result.failed_command_stderr_tail is None
    assert result.evidence_unavailable_reason is None


def test_failed_validation_never_serializes_as_successful():
    # Full lifecycle: validation fails with diagnostics, yet the branch
    # mutation succeeded. Terminal status must be "validation-failing", never
    # "converged", and the mutation must have been attempted exactly once.
    from scripts.agent_os_issue_labels.pr_branch_refresh import (
        BranchRefreshMutationResult,
        BranchRefreshValidationResult,
        PullRequestBranchRefreshRequest,
        PullRequestBranchSnapshot,
        refresh_pull_request_branch,
    )
    from scripts.agent_os_issue_labels.pr_branch_refresh_operator import (
        ClosedBranchRefreshValidationExecutor,
    )

    class FakeProvider:
        def __init__(self):
            self.branch = PullRequestBranchSnapshot(
                "Blummer92/agent-os", 3153, "main", "b" * 40,
                "agent/3153-refresh-diagnostic-evidence", "a" * 40, "b" * 40,
                "behind", "mergeable", ("x.py",),
            )
            self.rebases = 0

        def read_branch(self, repository, pr_number):
            return self.branch

        def rebase_onto_main(self, repository, pr_number, **kwargs):
            self.rebases += 1
            self.branch = replace(self.branch, head_sha="c" * 40, branch_state="current")
            return BranchRefreshMutationResult("updated", "a" * 40, "c" * 40)

        def run_required_validation(self, repository, pr_number, *, head_sha, command_ids):
            runner = _SequenceRunner([
                BranchUpdateObservation(
                    started=True, return_code=0, timed_out=False,
                    termination_confirmed=True, stdout="c" * 40 + "\n", stderr="",
                ),
                BranchUpdateObservation(
                    started=True, return_code=1, timed_out=False,
                    termination_confirmed=True, stdout="1 failed", stderr="E boom",
                ),
            ])
            return ClosedBranchRefreshValidationExecutor(runner, "/repo").run_required_validation(
                repository, pr_number, head_sha=head_sha, command_ids=command_ids,
            )

    request = PullRequestBranchRefreshRequest(
        repository="Blummer92/agent-os", pr_number=3153, base_branch="main",
        expected_base_sha="b" * 40, expected_head_sha="a" * 40,
        current_main_sha="b" * 40, authorization_id="auth:3153",
        authorization_current=True, allowed_changed_paths=("x.py",),
        forbidden_paths=(".github/workflows/x.yml",),
        required_validation_command_ids=(COMMAND_ID,),
        branch_refresh_authorized=True,
    )
    result = refresh_pull_request_branch(FakeProvider(), request)
    assert result.status == "validation-failing"
    assert result.status != "converged"
    assert result.mutation_attempted is True
    assert result.validation is not None
    assert result.validation.status == "failing"
    assert result.validation.failed_command_exit_code == 1
    assert result.validation.failed_command_stderr_tail == "E boom"


def test_failing_command_is_never_rerun_to_recover_diagnostics():
    # The executor must return from the observation already in hand. A second
    # run of the failing command merely to recover diagnostics is forbidden.
    runner = _SequenceRunner([
        _head_ok(),
        BranchUpdateObservation(
            started=True, return_code=1, timed_out=False,
            termination_confirmed=True, stdout="x", stderr="y",
        ),
    ])
    result = _executor(runner).run_required_validation(
        "Blummer92/agent-os", 3153, head_sha=SHA,
        command_ids=(COMMAND_ID, "pytest:pr-branch-refresh-provider"),
    )
    assert result.status == "failing"
    failing_argvs = [
        call[0] for call in runner.calls
        if "test_pr_branch_refresh.py" in " ".join(call[0])
    ]
    assert len(failing_argvs) == 1
    # Stops after the first failure: the second command never executes.
    assert len(runner.calls) == 2
