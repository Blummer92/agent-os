from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from scripts.agent_os_github_git_objects.branch_update import (
    BranchUpdateObservation,
    update_branch_with_expected_head,
)
from scripts.agent_os_github_git_objects.models import (
    ExpectedHeadBranchUpdateRequest,
    ExpectedHeadBranchUpdateStatus,
    MutationState,
)

OLD = "1" * 40
NEW = "2" * 40
MAIN = "3" * 40
MOVED = "4" * 40
REF = "refs/heads/agent/example"


def request(**overrides):
    values = {
        "repository": "Blummer92/agent-os",
        "branch": "agent/example",
        "expected_head_sha": OLD,
        "proposed_head_sha": NEW,
        "admitted_main_sha": MAIN,
        "invocation_id": "invocation-1381",
        "authorization_id": "authorization-1381",
        "authorization_current": True,
        "branch_update_authorized": True,
    }
    values.update(overrides)
    return ExpectedHeadBranchUpdateRequest(**values)


def observation(
    *,
    stdout="",
    return_code=0,
    started=True,
    timed_out=False,
    termination_confirmed=True,
):
    return BranchUpdateObservation(
        started=started,
        return_code=return_code,
        timed_out=timed_out,
        termination_confirmed=termination_confirmed,
        stdout=stdout,
    )


def remote(sha):
    return observation(stdout=f"{sha}\t{REF}\n")


class FakeRunner:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def run(self, argv, *, cwd, env):
        self.calls.append((argv, cwd, dict(env)))
        if not self.results:
            raise AssertionError("unexpected runner call")
        return self.results.pop(0)


def execute(runner, req=None):
    return update_branch_with_expected_head(
        req or request(),
        runner,
        repository_root="/repo",
        environment={"GIT_TERMINAL_PROMPT": "0"},
    )


def test_matching_head_performs_exactly_one_lease_bound_push_and_proves_new_head():
    runner = FakeRunner([remote(OLD), observation(), remote(NEW)])

    result = execute(runner)

    assert result.status is ExpectedHeadBranchUpdateStatus.CONFIRMED
    assert result.mutation_state is MutationState.CONFIRMED
    assert result.observed_head_before == OLD
    assert result.observed_head_after == NEW
    assert result.mutation_attempted is True
    assert len(runner.calls) == 3

    push = runner.calls[1][0]
    assert push == (
        "git",
        "push",
        f"--force-with-lease={REF}:{OLD}",
        "origin",
        f"{NEW}:{REF}",
    )
    assert "--force" not in push


def test_moved_expected_head_performs_zero_mutation():
    runner = FakeRunner([remote(MOVED)])

    result = execute(runner)

    assert result.status is ExpectedHeadBranchUpdateStatus.BLOCKED
    assert result.reason == "expected-head-mismatch"
    assert result.mutation_attempted is False
    assert result.mutation_state is MutationState.NOT_ATTEMPTED
    assert len(runner.calls) == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"authorization_current": False},
        {"branch_update_authorized": False},
    ],
)
def test_missing_or_stale_authorization_performs_zero_runner_calls(overrides):
    runner = FakeRunner([])

    result = execute(runner, request(**overrides))

    assert result.status is ExpectedHeadBranchUpdateStatus.BLOCKED
    assert result.reason == "authorization-required"
    assert result.mutation_state is MutationState.NOT_ATTEMPTED
    assert runner.calls == []


@pytest.mark.parametrize("branch", ["main", "master"])
def test_protected_branch_is_rejected_before_runner(branch):
    runner = FakeRunner([])

    with pytest.raises(ValueError):
        request(branch=branch)

    assert runner.calls == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"repository": "bad"},
        {"branch": "refs/heads/agent/example"},
        {"expected_head_sha": "bad"},
        {"proposed_head_sha": "bad"},
        {"admitted_main_sha": "bad"},
    ],
)
def test_malformed_identity_is_rejected_before_runner(overrides):
    runner = FakeRunner([])

    with pytest.raises(ValueError):
        request(**overrides)

    assert runner.calls == []


def test_push_that_does_not_start_is_failed_before_side_effect():
    runner = FakeRunner([
        remote(OLD),
        observation(started=False, return_code=None, termination_confirmed=False),
    ])

    result = execute(runner)

    assert result.status is ExpectedHeadBranchUpdateStatus.BLOCKED
    assert result.reason == "push-not-started"
    assert result.mutation_attempted is False
    assert result.mutation_state is MutationState.FAILED_BEFORE_SIDE_EFFECT
    assert len(runner.calls) == 2


@pytest.mark.parametrize(
    "push",
    [
        observation(timed_out=True, termination_confirmed=False),
        observation(return_code=None, termination_confirmed=False),
    ],
)
def test_ambiguous_push_is_uncertain_and_never_retried(push):
    runner = FakeRunner([remote(OLD), push])

    result = execute(runner)

    assert result.status is ExpectedHeadBranchUpdateStatus.UNCERTAIN
    assert result.reason == "push-outcome-uncertain"
    assert result.mutation_attempted is True
    assert result.mutation_state is MutationState.UNCERTAIN
    assert len(runner.calls) == 2
    assert result.retry_allowed is False


def test_rejected_force_with_lease_is_not_retried():
    runner = FakeRunner([
        remote(OLD),
        observation(return_code=1),
    ])

    result = execute(runner)

    assert result.status is ExpectedHeadBranchUpdateStatus.BLOCKED
    assert result.reason == "push-rejected"
    assert len(runner.calls) == 2
    assert result.retry_allowed is False


def test_success_response_without_exact_post_write_head_is_uncertain():
    runner = FakeRunner([remote(OLD), observation(), remote(MOVED)])

    result = execute(runner)

    assert result.status is ExpectedHeadBranchUpdateStatus.UNCERTAIN
    assert result.reason == "post-update-mismatch"
    assert result.observed_head_after == MOVED
    assert result.mutation_state is MutationState.UNCERTAIN
    assert len(runner.calls) == 3


def test_malformed_remote_read_performs_zero_mutation():
    runner = FakeRunner([
        observation(stdout=f"{OLD}\trefs/heads/some-other-branch\n"),
    ])

    result = execute(runner)

    assert result.status is ExpectedHeadBranchUpdateStatus.BLOCKED
    assert result.reason == "remote-head-unavailable"
    assert result.mutation_attempted is False
    assert len(runner.calls) == 1


def test_request_and_result_are_immutable_and_authority_stays_false():
    req = request()

    with pytest.raises(FrozenInstanceError):
        req.branch = "agent/other"

    runner = FakeRunner([remote(OLD), observation(), remote(NEW)])
    result = execute(runner, req)

    assert result.retry_allowed is False
    assert result.unconditional_force_used is False
    assert result.merge_authorized is False
    assert result.protected_branch_authorized is False
    assert result.workflow_mutation_authorized is False
    assert result.repository_setting_authorized is False

    with pytest.raises(FrozenInstanceError):
        result.reason = "changed"


def test_source_has_no_unconditional_force_or_fallback_mutation():
    source = Path(
        "scripts/agent_os_github_git_objects/branch_update.py"
    ).read_text()

    assert '"--force"' not in source
    assert "merge main" not in source.lower()
    assert "#568" not in source
    assert source.count('"push"') == 1
    assert "force-with-lease" in source
