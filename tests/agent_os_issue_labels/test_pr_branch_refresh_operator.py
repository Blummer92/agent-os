from __future__ import annotations

import inspect
import subprocess
import sys

import pytest

from scripts.agent_os_issue_labels.pr_branch_refresh_operator import (
    SubprocessBranchUpdateRunner,
)


def test_subprocess_runner_maps_success(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = SubprocessBranchUpdateRunner(timeout_seconds=17).run(
        ("git", "rev-parse", "HEAD"), cwd="/repo", env={"A": "B"}
    )
    assert result.started is True
    assert result.return_code == 0
    assert result.timed_out is False
    assert result.termination_confirmed is True
    assert result.stdout == "ok\n"
    argv, kwargs = calls[0]
    assert argv == ["git", "rev-parse", "HEAD"]
    assert kwargs["shell"] is False
    assert kwargs["timeout"] == 17
    assert kwargs["check"] is False


def test_subprocess_runner_projects_timeout_as_uncertain(monkeypatch):
    calls = 0

    def fake_run(argv, **kwargs):
        nonlocal calls
        calls += 1
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"], output="partial")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = SubprocessBranchUpdateRunner().run(
        ("git", "push", "origin", "x:y"), cwd="/repo", env={}
    )
    assert calls == 1
    assert result.started is True
    assert result.return_code is None
    assert result.timed_out is True
    assert result.termination_confirmed is False
    assert result.stdout == "partial"


def test_subprocess_runner_projects_spawn_failure_before_side_effect(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda argv, **kwargs: (_ for _ in ()).throw(FileNotFoundError("git"))
    )
    result = SubprocessBranchUpdateRunner().run(("git", "status"), cwd="/repo", env={})
    assert result.started is False
    assert result.return_code is None
    assert result.timed_out is False
    assert result.termination_confirmed is True


def test_subprocess_runner_rejects_malformed_argv():
    runner = SubprocessBranchUpdateRunner()
    for argv in ((), ("git", ""), ("git", "bad\x00arg")):
        with pytest.raises(ValueError):
            runner.run(argv, cwd="/repo", env={})


class _SequenceRunner:
    def __init__(self, observations):
        self.observations = list(observations)
        self.calls = []

    def run(self, argv, *, cwd, env):
        self.calls.append((argv, cwd, env))
        return self.observations.pop(0)


def _observation(*, stdout="", return_code=0):
    from scripts.agent_os_github_git_objects.branch_update import BranchUpdateObservation
    return BranchUpdateObservation(
        started=True, return_code=return_code, timed_out=False,
        termination_confirmed=True, stdout=stdout, stderr=""
    )


def test_closed_validation_executor_runs_only_known_fixed_profile():
    from scripts.agent_os_issue_labels.pr_branch_refresh_operator import ClosedBranchRefreshValidationExecutor
    sha = "a" * 40
    runner = _SequenceRunner([_observation(stdout=sha + "\n"), _observation(), _observation(stdout=sha + "\n")])
    result = ClosedBranchRefreshValidationExecutor(runner, "/repo").run_required_validation(
        "Blummer92/agent-os", 1363, head_sha=sha,
        command_ids=("pytest:pr-branch-refresh",),
    )
    assert result.status == "green"
    assert runner.calls[1][0] == (
        sys.executable, "-m", "pytest",
        "tests/agent_os_issue_labels/test_pr_branch_refresh.py", "-q",
    )


def test_closed_validation_executor_uses_exact_current_python_and_bounded_environment():
    from scripts.agent_os_issue_labels.pr_branch_refresh_operator import ClosedBranchRefreshValidationExecutor
    sha = "a" * 40
    runner = _SequenceRunner([_observation(stdout=sha + "\n"), _observation(), _observation(stdout=sha + "\n")])
    environment = {
        "PATH": "/runner/bin:/usr/bin",
        "HOME": "/runner/home",
        "GITHUB_TOKEN": "must-not-leak",
        "NOTION_TOKEN": "must-not-leak",
    }
    result = ClosedBranchRefreshValidationExecutor(
        runner, "/repo", environment=environment
    ).run_required_validation(
        "Blummer92/agent-os", 2962, head_sha=sha,
        command_ids=("pytest:pr-branch-refresh",),
    )
    assert result.status == "green"
    assert runner.calls[1][0][0] == sys.executable
    assert runner.calls[1][2] == {"HOME": "/runner/home", "PATH": "/runner/bin:/usr/bin"}


def test_closed_validation_executor_rejects_unknown_id_without_execution():
    from scripts.agent_os_issue_labels.pr_branch_refresh_operator import ClosedBranchRefreshValidationExecutor
    runner = _SequenceRunner([])
    result = ClosedBranchRefreshValidationExecutor(runner, "/repo").run_required_validation(
        "Blummer92/agent-os", 1363, head_sha="a" * 40,
        command_ids=("operator-supplied-shell-command",),
    )
    assert result.status == "failing"
    assert result.failed_command_id == "operator-supplied-shell-command"
    assert result.failure_reason == "unknown-command"
    assert runner.calls == []


def test_closed_validation_executor_fails_on_stale_checkout_before_test():
    from scripts.agent_os_issue_labels.pr_branch_refresh_operator import ClosedBranchRefreshValidationExecutor
    runner = _SequenceRunner([_observation(stdout=("b" * 40) + "\n")])
    result = ClosedBranchRefreshValidationExecutor(runner, "/repo").run_required_validation(
        "Blummer92/agent-os", 1363, head_sha="a" * 40,
        command_ids=("pytest:pr-branch-refresh",),
    )
    assert result.status == "failing"
    assert result.failed_command_id == "head:before"
    assert result.failure_reason == "head-mismatch"
    assert len(runner.calls) == 1


def test_closed_validation_executor_stops_after_first_failure():
    from scripts.agent_os_issue_labels.pr_branch_refresh_operator import ClosedBranchRefreshValidationExecutor
    sha = "a" * 40
    runner = _SequenceRunner([_observation(stdout=sha + "\n"), _observation(return_code=1)])
    result = ClosedBranchRefreshValidationExecutor(runner, "/repo").run_required_validation(
        "Blummer92/agent-os", 1363, head_sha=sha,
        command_ids=("pytest:pr-branch-refresh", "pytest:pr-branch-refresh-provider"),
    )
    assert result.status == "failing"
    assert result.failed_command_id == "pytest:pr-branch-refresh"
    assert result.failure_reason == "command-nonzero-exit"
    assert len(runner.calls) == 2


@pytest.mark.parametrize(
    ("observation", "expected_reason"),
    [
        (
            lambda: __import__("scripts.agent_os_github_git_objects.branch_update", fromlist=["BranchUpdateObservation"]).BranchUpdateObservation(
                started=False, return_code=None, timed_out=False, termination_confirmed=True
            ),
            "command-not-started",
        ),
        (
            lambda: __import__("scripts.agent_os_github_git_objects.branch_update", fromlist=["BranchUpdateObservation"]).BranchUpdateObservation(
                started=True, return_code=None, timed_out=True, termination_confirmed=False
            ),
            "command-timeout",
        ),
        (
            lambda: __import__("scripts.agent_os_github_git_objects.branch_update", fromlist=["BranchUpdateObservation"]).BranchUpdateObservation(
                started=True, return_code=None, timed_out=False, termination_confirmed=False
            ),
            "command-termination-unconfirmed",
        ),
    ],
)
def test_closed_validation_executor_projects_safe_command_failure_reason(observation, expected_reason):
    from scripts.agent_os_issue_labels.pr_branch_refresh_operator import ClosedBranchRefreshValidationExecutor
    sha = "a" * 40
    runner = _SequenceRunner([_observation(stdout=sha + "\n"), observation()])
    result = ClosedBranchRefreshValidationExecutor(runner, "/repo").run_required_validation(
        "Blummer92/agent-os", 2962, head_sha=sha,
        command_ids=("pytest:pr-branch-refresh",),
    )
    assert result.status == "failing"
    assert result.failed_command_id == "pytest:pr-branch-refresh"
    assert result.failure_reason == expected_reason


def test_closed_validation_executor_projects_post_validation_head_movement():
    from scripts.agent_os_issue_labels.pr_branch_refresh_operator import ClosedBranchRefreshValidationExecutor
    sha = "a" * 40
    runner = _SequenceRunner([
        _observation(stdout=sha + "\n"),
        _observation(),
        _observation(stdout=("b" * 40) + "\n"),
    ])
    result = ClosedBranchRefreshValidationExecutor(runner, "/repo").run_required_validation(
        "Blummer92/agent-os", 2962, head_sha=sha,
        command_ids=("pytest:pr-branch-refresh",),
    )
    assert result.status == "failing"
    assert result.failed_command_id == "head:after"
    assert result.failure_reason == "head-moved"


def test_missing_github_credentials_fail_before_composition():
    from scripts.agent_os_issue_labels.pr_branch_refresh_operator import build_branch_refresh_github_client
    for env in ({}, {"GITHUB_TOKEN": "  "}, {"GH_TOKEN": ""}):
        with pytest.raises(RuntimeError):
            build_branch_refresh_github_client(env)


def _request(*, authorization_current=True):
    from scripts.agent_os_issue_labels.pr_branch_refresh import PullRequestBranchRefreshRequest
    return PullRequestBranchRefreshRequest(
        repository="Blummer92/agent-os", pr_number=1363, base_branch="main",
        expected_base_sha="b" * 40, expected_head_sha="a" * 40,
        current_main_sha="b" * 40, authorization_id="auth:1363",
        authorization_current=authorization_current,
        allowed_changed_paths=("x.py",), forbidden_paths=(".github/workflows/x.yml",),
        required_validation_command_ids=("pytest:pr-branch-refresh",),
        branch_refresh_authorized=True,
    )


def test_operator_rejects_stale_authorization_before_github():
    from scripts.agent_os_issue_labels.pr_branch_refresh_operator import run_branch_refresh_operator
    with pytest.raises(RuntimeError, match="authorization"):
        run_branch_refresh_operator(
            request=_request(authorization_current=False), repository_root="/repo",
            invocation_id="invocation:1363", environment={},
        )


def test_operator_delegates_exactly_once_to_production_caller(monkeypatch):
    import scripts.agent_os_issue_labels.pr_branch_refresh_operator as operator
    import scripts.agent_os_issue_labels.pr_branch_refresh_provider as provider
    request = _request()

    class FakeGitHubClient:
        requester = object()

    fake_client = FakeGitHubClient()
    monkeypatch.setattr(operator, "build_branch_refresh_github_client", lambda environment: fake_client)
    monkeypatch.setattr(
        operator, "preflight_production_branch_refresh",
        lambda **kwargs: operator.BranchRefreshOperatorPreflight(
            repository=request.repository, pr_number=request.pr_number,
            expected_head_sha=request.expected_head_sha,
            current_main_sha=request.current_main_sha,
            authorization_id=request.authorization_id, ready=True, reason_codes=(),
        ),
    )
    calls = []
    monkeypatch.setattr(provider, "run_production_pull_request_branch_refresh", lambda **kwargs: calls.append(kwargs) or "result")
    result = operator.run_branch_refresh_operator(
        request=request, repository_root="/repo", invocation_id="invocation:1363",
        environment={"GITHUB_TOKEN": "redacted-test-token"},
    )
    assert result == "result"
    assert len(calls) == 1
    assert calls[0]["request"] is request
    assert calls[0]["github_client"] is fake_client
    assert calls[0]["invocation_id"] == "invocation:1363"


def test_preflight_is_non_mutating_and_reports_moved_head(monkeypatch):
    from scripts.agent_os_issue_labels.pr_branch_refresh import PullRequestBranchSnapshot
    import scripts.agent_os_issue_labels.pr_branch_refresh_operator as operator
    import scripts.agent_os_issue_labels.pr_branch_refresh_provider as provider
    request = _request()

    class FakeBacking:
        def __init__(self, **kwargs):
            pass

        def read_branch(self, repository, pr_number):
            return PullRequestBranchSnapshot(
                repository=repository, pr_number=pr_number, base_branch="main",
                base_sha="b" * 40, head_branch="agent/x", head_sha="c" * 40,
                current_main_sha="b" * 40, branch_state="behind",
                mergeability="mergeable", changed_paths=("x.py",),
            )

    monkeypatch.setattr(provider, "GitHubPullRequestBranchRefreshBackingProvider", FakeBacking)
    result = operator.preflight_production_branch_refresh(
        github_client=object(), request=request, repository_root="/repo"
    )
    assert result.ready is False
    assert result.reason_codes == ("head.moved",)


# #1402 canonical facade regressions.

def _facade_kwargs(**overrides):
    values = {
        "repository": "Blummer92/agent-os", "pr_number": 1363,
        "expected_head_sha": "a" * 40, "current_main_sha": "b" * 40,
        "authorization_id": "auth:1363", "authorization_current": True,
        "branch_refresh_authorized": True, "allowed_changed_paths": ("x.py",),
        "forbidden_paths": (".github/workflows/x.yml",),
        "repository_root": "/repo",
        "invocation_id": "invocation:1363",
        "environment": {"GITHUB_TOKEN": "redacted-test-token"},
    }
    values.update(overrides)
    return values


def _result(*, status="converged", side_effects=True, reasons=None, validation_status="green"):
    from scripts.agent_os_issue_labels.pr_branch_refresh import BranchRefreshValidationResult, PullRequestBranchRefreshResult
    if reasons is None:
        reasons = ("branch.current-proven", "head-evidence.invalidated", "refresh.rebased")
    validation = None if validation_status is None else BranchRefreshValidationResult(
        head_sha="c" * 40, status=validation_status,
        command_ids=("pytest:pr-branch-refresh",),
    )
    return PullRequestBranchRefreshResult(
        repository="Blummer92/agent-os", pr_number=1363, status=status,
        old_head_sha="a" * 40, new_head_sha="c" * 40 if side_effects else None,
        invalidated_head_evidence=("tested-sha",) if side_effects else (),
        validation=validation,
        reason_codes=tuple(reasons), branch_refresh_authorized=True,
        side_effects_performed=side_effects,
    )


def test_refresh_pr_is_single_package_root_operator_entrypoint():
    import scripts.agent_os_issue_labels as package
    assert "refresh_pr" in package.__all__
    assert "refresh_pull_request_branch" not in package.__all__
    assert "run_production_pull_request_branch_refresh" not in package.__all__
    assert callable(package.refresh_pr)


def test_refresh_pr_signature_hides_internal_composition_and_validation_profile():
    from scripts.agent_os_issue_labels.pr_branch_refresh_operator import refresh_pr
    parameters = set(inspect.signature(refresh_pr).parameters)
    for hidden in (
        "request", "provider", "runner",
        "validation_executor", "required_validation_command_ids",
    ):
        assert hidden not in parameters


def test_refresh_pr_constructs_canonical_request_and_delegates_once(monkeypatch):
    import scripts.agent_os_issue_labels.pr_branch_refresh_operator as operator
    calls = []
    monkeypatch.setattr(operator, "run_branch_refresh_operator", lambda **kwargs: calls.append(kwargs) or _result())
    receipt = operator.refresh_pr(**_facade_kwargs())
    assert len(calls) == 1
    request = calls[0]["request"]
    assert request.repository == "Blummer92/agent-os"
    assert request.pr_number == 1363
    assert request.base_branch == "main"
    assert request.expected_base_sha == "b" * 40
    assert request.current_main_sha == "b" * 40
    assert request.expected_head_sha == "a" * 40
    assert request.authorization_id == "auth:1363"
    assert request.authorization_current is True
    assert request.required_validation_command_ids == operator._CANONICAL_REFRESH_VALIDATION_COMMAND_IDS
    assert receipt.status == "converged"


@pytest.mark.parametrize("field", ["authorization_current", "branch_refresh_authorized"])
def test_refresh_pr_rejects_missing_or_stale_authority_before_operator(monkeypatch, field):
    import scripts.agent_os_issue_labels.pr_branch_refresh_operator as operator
    calls = 0

    def fake_run(**kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("operator must not run")

    monkeypatch.setattr(operator, "run_branch_refresh_operator", fake_run)
    receipt = operator.refresh_pr(**_facade_kwargs(**{field: False}))
    assert calls == 0
    assert receipt.status == "blocked"
    assert receipt.reason_codes == ("authorization.refresh-required",)
    assert receipt.mutation_count == 0


@pytest.mark.parametrize(
    "reason",
    ["head.moved", "base.moved", "branch.mergeability-blocked", "scope.forbidden-path", "scope.expanded"],
)
def test_refresh_pr_projects_existing_preflight_blockers_without_retry(monkeypatch, reason):
    import scripts.agent_os_issue_labels.pr_branch_refresh_operator as operator
    calls = 0

    def fake_run(**kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("branch refresh preflight blocked: " + reason)

    monkeypatch.setattr(operator, "run_branch_refresh_operator", fake_run)
    receipt = operator.refresh_pr(**_facade_kwargs())
    assert calls == 1
    assert receipt.status == "blocked"
    assert receipt.blockers == (reason,)
    assert receipt.mutation_count == 0
    assert receipt.side_effects_performed is False


def test_refresh_pr_does_not_retry_unclassified_runtime_failure(monkeypatch):
    import scripts.agent_os_issue_labels.pr_branch_refresh_operator as operator
    calls = 0

    def fake_run(**kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("credentials unavailable")

    monkeypatch.setattr(operator, "run_branch_refresh_operator", fake_run)
    with pytest.raises(RuntimeError, match="credentials unavailable"):
        operator.refresh_pr(**_facade_kwargs())
    assert calls == 1


def test_refresh_pr_success_receipt_is_bounded_and_non_authorizing(monkeypatch):
    import scripts.agent_os_issue_labels.pr_branch_refresh_operator as operator
    monkeypatch.setattr(operator, "run_branch_refresh_operator", lambda **kwargs: _result())
    receipt = operator.refresh_pr(**_facade_kwargs())
    assert receipt.authorization_id == "auth:1363"
    assert receipt.authorization_consumed is True
    assert receipt.admitted_main_sha == "b" * 40
    assert receipt.old_head_sha == "a" * 40
    assert receipt.new_head_sha == "c" * 40
    assert receipt.mutation_count == 1
    assert receipt.validation_status == "green"
    assert receipt.validation_head_sha == "c" * 40
    assert receipt.validation_failed_command_id is None
    assert receipt.validation_failure_reason is None
    assert receipt.final_current_proven is True
    assert receipt.blockers == ()
    assert receipt.rollback_posture == "restore-old-head-with-separate-authorization"
    for name in (
        "ready_for_review_authorized", "merge_authorized", "issue_closure_authorized",
        "workflow_authorized", "repository_setting_authorized", "production_authorized",
        "credential_authorized", "external_system_write_authorized",
    ):
        assert getattr(receipt, name) is False


@pytest.mark.parametrize(
    ("status", "side_effects", "validation_status", "reason"),
    [
        ("blocked", False, None, "scope.forbidden-path"),
        ("stale", True, "green", "main.moved-before-final-proof"),
        ("validation-failing", True, "failing", "branch.current-proven"),
    ],
)
def test_refresh_pr_receipt_projects_terminal_result_states(monkeypatch, status, side_effects, validation_status, reason):
    import scripts.agent_os_issue_labels.pr_branch_refresh_operator as operator
    monkeypatch.setattr(
        operator, "run_branch_refresh_operator",
        lambda **kwargs: _result(
            status=status, side_effects=side_effects,
            validation_status=validation_status, reasons=(reason,),
        ),
    )
    receipt = operator.refresh_pr(**_facade_kwargs())
    assert receipt.status == status
    assert receipt.mutation_count == (1 if side_effects else 0)
    assert receipt.blockers == (reason,)
    assert receipt.validation_status == validation_status


def test_receipt_rejects_mutation_count_outside_closed_vocabulary():
    from scripts.agent_os_issue_labels.pr_branch_refresh_operator import PullRequestBranchRefreshReceipt
    with pytest.raises(ValueError, match="mutation_count"):
        PullRequestBranchRefreshReceipt(
            repository="Blummer92/agent-os", pr_number=1363, status="blocked",
            authorization_id="auth:1363", authorization_consumed=False,
            admitted_main_sha="b" * 40, old_head_sha="a" * 40, new_head_sha=None,
            mutation_count=2, validation_status=None, validation_head_sha=None,
            validation_failed_command_id=None, validation_failure_reason=None,
            final_current_proven=False,
            blockers=("blocked",), reason_codes=("blocked",),
            rollback_posture="no-branch-mutation", side_effects_performed=False,
        )
