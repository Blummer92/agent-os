from __future__ import annotations

import subprocess

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
        ("git", "rev-parse", "HEAD"),
        cwd="/repo",
        env={"A": "B"},
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
        ("git", "push", "origin", "x:y"),
        cwd="/repo",
        env={},
    )

    assert calls == 1
    assert result.started is True
    assert result.return_code is None
    assert result.timed_out is True
    assert result.termination_confirmed is False
    assert result.stdout == "partial"


def test_subprocess_runner_projects_spawn_failure_before_side_effect(monkeypatch):
    def fake_run(argv, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = SubprocessBranchUpdateRunner().run(
        ("git", "status"),
        cwd="/repo",
        env={},
    )

    assert result.started is False
    assert result.return_code is None
    assert result.timed_out is False
    assert result.termination_confirmed is True


def test_subprocess_runner_rejects_malformed_argv():
    runner = SubprocessBranchUpdateRunner()

    for argv in ((), ("git", ""), ("git", "bad\x00arg")):
        try:
            runner.run(argv, cwd="/repo", env={})
        except ValueError:
            pass
        else:
            raise AssertionError("malformed argv was accepted")


class _Requester:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def requestJsonAndCheck(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return {}, self.payload


class _Client:
    def __init__(self, payload):
        self.requester = _Requester(payload)


def _review_payload(*, resolved=False, has_next=False):
    return {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "pageInfo": {"hasNextPage": has_next},
                        "nodes": [
                            {
                                "id": "PRRT_1",
                                "isResolved": resolved,
                                "isOutdated": False,
                                "path": "x.py",
                                "line": 7,
                                "originalLine": 7,
                                "diffSide": "RIGHT",
                                "startLine": None,
                                "startDiffSide": None,
                                "comments": {
                                    "pageInfo": {"hasNextPage": False},
                                    "nodes": [
                                        {
                                            "databaseId": 123,
                                            "id": "PRRC_1",
                                            "body": "blocking review",
                                            "createdAt": "2026-08-25T00:00:00Z",
                                            "updatedAt": "2026-08-25T00:00:00Z",
                                            "author": {"login": "reviewer"},
                                        }
                                    ],
                                },
                            }
                        ],
                    }
                }
            }
        }
    }


def test_review_reader_counts_current_unresolved_threads():
    from scripts.agent_os_issue_labels.pr_branch_refresh_operator import (
        PyGithubBlockingReviewThreadsReader,
    )

    client = _Client(_review_payload())
    reader = PyGithubBlockingReviewThreadsReader(client)

    assert reader.blocking_review_threads("Blummer92/agent-os", 1363) == 1
    assert len(client.requester.calls) == 1


def test_review_reader_does_not_count_resolved_thread():
    from scripts.agent_os_issue_labels.pr_branch_refresh_operator import (
        PyGithubBlockingReviewThreadsReader,
    )

    reader = PyGithubBlockingReviewThreadsReader(
        _Client(_review_payload(resolved=True))
    )

    assert reader.blocking_review_threads("Blummer92/agent-os", 1363) == 0


def test_review_reader_fails_closed_on_incomplete_pagination():
    from scripts.agent_os_issue_labels.pr_branch_refresh_operator import (
        PyGithubBlockingReviewThreadsReader,
    )

    reader = PyGithubBlockingReviewThreadsReader(
        _Client(_review_payload(has_next=True))
    )

    try:
        reader.blocking_review_threads("Blummer92/agent-os", 1363)
    except RuntimeError as error:
        assert "incomplete" in str(error)
    else:
        raise AssertionError("incomplete review evidence was accepted")


class _SequenceRunner:
    def __init__(self, observations):
        self.observations = list(observations)
        self.calls = []

    def run(self, argv, *, cwd, env):
        self.calls.append((argv, cwd, env))
        return self.observations.pop(0)


def _observation(*, stdout="", return_code=0):
    from scripts.agent_os_github_git_objects.branch_update import (
        BranchUpdateObservation,
    )

    return BranchUpdateObservation(
        started=True,
        return_code=return_code,
        timed_out=False,
        termination_confirmed=True,
        stdout=stdout,
        stderr="",
    )


def test_closed_validation_executor_runs_only_known_fixed_profile():
    from scripts.agent_os_issue_labels.pr_branch_refresh_operator import (
        ClosedBranchRefreshValidationExecutor,
    )

    sha = "a" * 40
    runner = _SequenceRunner(
        [
            _observation(stdout=sha + "\n"),
            _observation(),
            _observation(stdout=sha + "\n"),
        ]
    )
    executor = ClosedBranchRefreshValidationExecutor(runner, "/repo")

    result = executor.run_required_validation(
        "Blummer92/agent-os",
        1363,
        head_sha=sha,
        command_ids=("pytest:pr-branch-refresh",),
    )

    assert result.status == "green"
    assert runner.calls[1][0] == (
        ".venv/bin/python",
        "-m",
        "pytest",
        "tests/agent_os_issue_labels/test_pr_branch_refresh.py",
        "-q",
    )


def test_closed_validation_executor_rejects_unknown_id_without_execution():
    from scripts.agent_os_issue_labels.pr_branch_refresh_operator import (
        ClosedBranchRefreshValidationExecutor,
    )

    runner = _SequenceRunner([])
    executor = ClosedBranchRefreshValidationExecutor(runner, "/repo")

    result = executor.run_required_validation(
        "Blummer92/agent-os",
        1363,
        head_sha="a" * 40,
        command_ids=("operator-supplied-shell-command",),
    )

    assert result.status == "failing"
    assert runner.calls == []


def test_closed_validation_executor_fails_on_stale_checkout_before_test():
    from scripts.agent_os_issue_labels.pr_branch_refresh_operator import (
        ClosedBranchRefreshValidationExecutor,
    )

    runner = _SequenceRunner([_observation(stdout=("b" * 40) + "\n")])
    executor = ClosedBranchRefreshValidationExecutor(runner, "/repo")

    result = executor.run_required_validation(
        "Blummer92/agent-os",
        1363,
        head_sha="a" * 40,
        command_ids=("pytest:pr-branch-refresh",),
    )

    assert result.status == "failing"
    assert len(runner.calls) == 1


def test_closed_validation_executor_stops_after_first_failure():
    from scripts.agent_os_issue_labels.pr_branch_refresh_operator import (
        ClosedBranchRefreshValidationExecutor,
    )

    sha = "a" * 40
    runner = _SequenceRunner(
        [
            _observation(stdout=sha + "\n"),
            _observation(return_code=1),
        ]
    )
    executor = ClosedBranchRefreshValidationExecutor(runner, "/repo")

    result = executor.run_required_validation(
        "Blummer92/agent-os",
        1363,
        head_sha=sha,
        command_ids=(
            "pytest:pr-branch-refresh",
            "pytest:pr-branch-refresh-provider",
        ),
    )

    assert result.status == "failing"
    assert len(runner.calls) == 2


def test_missing_github_credentials_fail_before_composition():
    from scripts.agent_os_issue_labels.pr_branch_refresh_operator import (
        build_branch_refresh_github_client,
    )

    for env in ({}, {"GITHUB_TOKEN": "  "}, {"GH_TOKEN": ""}):
        try:
            build_branch_refresh_github_client(env)
        except RuntimeError:
            pass
        else:
            raise AssertionError("missing credentials were accepted")


def test_operator_rejects_stale_authorization_before_github(monkeypatch):
    from scripts.agent_os_issue_labels.pr_branch_refresh import (
        PullRequestBranchRefreshRequest,
    )
    from scripts.agent_os_issue_labels.pr_branch_refresh_operator import (
        run_branch_refresh_operator,
    )

    request = PullRequestBranchRefreshRequest(
        repository="Blummer92/agent-os",
        pr_number=1363,
        base_branch="main",
        expected_base_sha="b" * 40,
        expected_head_sha="a" * 40,
        current_main_sha="b" * 40,
        authorization_id="auth:1363",
        authorization_current=False,
        allowed_changed_paths=("x.py",),
        forbidden_paths=(".github/workflows/x.yml",),
        required_validation_command_ids=("pytest:pr-branch-refresh",),
        branch_refresh_authorized=True,
        label_write_authorized=True,
    )

    try:
        run_branch_refresh_operator(
            request=request,
            repository_root="/repo",
            invocation_id="invocation:1363",
            environment={},
        )
    except RuntimeError as error:
        assert "authorization" in str(error)
    else:
        raise AssertionError("stale authorization reached composition")


def test_operator_delegates_exactly_once_to_production_caller(monkeypatch):
    from scripts.agent_os_issue_labels.pr_branch_refresh import (
        PullRequestBranchRefreshRequest,
    )
    import scripts.agent_os_issue_labels.pr_branch_refresh_operator as operator
    import scripts.agent_os_issue_labels.pr_branch_refresh_provider as provider

    request = PullRequestBranchRefreshRequest(
        repository="Blummer92/agent-os",
        pr_number=1363,
        base_branch="main",
        expected_base_sha="b" * 40,
        expected_head_sha="a" * 40,
        current_main_sha="b" * 40,
        authorization_id="auth:1363",
        authorization_current=True,
        allowed_changed_paths=("x.py",),
        forbidden_paths=(".github/workflows/x.yml",),
        required_validation_command_ids=("pytest:pr-branch-refresh",),
        branch_refresh_authorized=True,
        label_write_authorized=True,
    )

    class FakeGitHubClient:
        requester = object()

    fake_client = FakeGitHubClient()
    monkeypatch.setattr(
        operator,
        "build_branch_refresh_github_client",
        lambda environment: fake_client,
    )

    monkeypatch.setattr(
        operator,
        "preflight_production_branch_refresh",
        lambda **kwargs: operator.BranchRefreshOperatorPreflight(
            repository=request.repository,
            pr_number=request.pr_number,
            expected_head_sha=request.expected_head_sha,
            current_main_sha=request.current_main_sha,
            authorization_id=request.authorization_id,
            ready=True,
            reason_codes=(),
        ),
    )

    calls = []

    def fake_run(**kwargs):
        calls.append(kwargs)
        return "result"

    monkeypatch.setattr(
        provider,
        "run_production_pull_request_branch_refresh",
        fake_run,
    )

    # run_branch_refresh_operator imports the function inside the call, so the
    # provider-module patch above is the exact seam exercised.
    result = operator.run_branch_refresh_operator(
        request=request,
        repository_root="/repo",
        invocation_id="invocation:1363",
        environment={"GITHUB_TOKEN": "redacted-test-token"},
    )

    assert result == "result"
    assert len(calls) == 1
    assert calls[0]["request"] is request
    assert calls[0]["github_client"] is fake_client
    assert calls[0]["invocation_id"] == "invocation:1363"


def test_preflight_is_non_mutating_and_reports_moved_head(monkeypatch):
    from scripts.agent_os_issue_labels.pr_branch_refresh import (
        PullRequestBranchRefreshRequest,
        PullRequestBranchSnapshot,
    )
    import scripts.agent_os_issue_labels.pr_branch_refresh_operator as operator
    import scripts.agent_os_issue_labels.pr_branch_refresh_provider as provider

    request = PullRequestBranchRefreshRequest(
        repository="Blummer92/agent-os",
        pr_number=1363,
        base_branch="main",
        expected_base_sha="b" * 40,
        expected_head_sha="a" * 40,
        current_main_sha="b" * 40,
        authorization_id="auth:1363",
        authorization_current=True,
        allowed_changed_paths=("x.py",),
        forbidden_paths=(".github/workflows/x.yml",),
        required_validation_command_ids=("pytest:pr-branch-refresh",),
        branch_refresh_authorized=True,
        label_write_authorized=True,
    )

    class FakeBacking:
        def __init__(self, **kwargs):
            pass

        def read_branch(self, repository, pr_number):
            return PullRequestBranchSnapshot(
                repository=repository,
                pr_number=pr_number,
                base_branch="main",
                base_sha="b" * 40,
                head_branch="agent/x",
                head_sha="c" * 40,
                current_main_sha="b" * 40,
                branch_state="behind",
                mergeability="mergeable",
                changed_paths=("x.py",),
            )

    monkeypatch.setattr(
        provider,
        "GitHubPullRequestBranchRefreshBackingProvider",
        FakeBacking,
    )

    result = operator.preflight_production_branch_refresh(
        github_client=object(),
        request=request,
        repository_root="/repo",
    )

    assert result.ready is False
    assert result.reason_codes == ("head.moved",)
