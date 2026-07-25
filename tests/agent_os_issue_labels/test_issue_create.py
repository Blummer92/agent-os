from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.agent_os_issue_acceptance.models import Status
from scripts.agent_os_issue_labels.draft import IssueDraftInput, build_issue_draft
from scripts.agent_os_issue_labels.issue_create import (
    GitHubRepositoryTarget,
    IssueCreateConfirmation,
    IssueCreateExitCode,
    IssueCreateProcessResult,
    IssueCreateReasonCode,
    IssueCreateRequest,
    MutationState,
    build_issue_create_argv,
    execute_issue_creation,
    plan_issue_creation,
)
from scripts.agent_os_issue_labels.validation import validate_issue_draft

ROOT = Path(__file__).resolve().parents[2]
FORM = ROOT / ".github/ISSUE_TEMPLATE/agent-os-task.yml"
MAP = ROOT / ".github/labeler/agent-os-issue-label-map.yml"
FIXTURE = ROOT / "tests/fixtures/agent_os_issue_labels/draft_minimum_valid.json"
TARGET = GitHubRepositoryTarget.parse("Blummer92/agent-os")


class FakeRunner:
    def __init__(self, *, executable="gh", create=None):
        self.executable = executable
        self.create = create or IssueCreateProcessResult(
            0, "https://github.com/Blummer92/agent-os/issues/700\n", ""
        )
        self.calls = []

    def resolve_executable(self):
        return self.executable

    def run(self, argv, *, input_text=None, timeout=30.0):
        key = tuple(argv)
        self.calls.append((key, input_text, timeout))
        if key == (self.executable, "--version"):
            return IssueCreateProcessResult(0, "gh version 2.80.0\n", "")
        if key == (self.executable, "issue", "create", "--help"):
            return IssueCreateProcessResult(0, "--repo --title --body-file --label\n", "")
        if key == (
            self.executable,
            "auth",
            "status",
            "--active",
            "--hostname",
            "github.com",
        ):
            return IssueCreateProcessResult(
                0, "Logged in to github.com account tester\n", ""
            )
        if key == (
            self.executable,
            "repo",
            "view",
            "github.com/Blummer92/agent-os",
            "--json",
            "nameWithOwner,url,hasIssuesEnabled,isArchived",
        ):
            return IssueCreateProcessResult(
                0,
                json.dumps(
                    {
                        "nameWithOwner": "Blummer92/agent-os",
                        "url": "https://github.com/Blummer92/agent-os",
                        "hasIssuesEnabled": True,
                        "isArchived": False,
                    }
                ),
                "",
            )
        if "--body-file=-" in key:
            return self.create
        raise AssertionError(key)


class Confirmation:
    def __init__(
        self,
        *,
        invocation_id="inv-1",
        confirmed=True,
        fingerprint=None,
        target=None,
        warnings=None,
    ):
        self.invocation_id = invocation_id
        self.confirmed = confirmed
        self.fingerprint = fingerprint
        self.target = target
        self.warnings = warnings

    def confirm(self, plan):
        return IssueCreateConfirmation(
            invocation_id=self.invocation_id,
            operation_fingerprint=self.fingerprint or plan.operation_fingerprint,
            target=self.target or plan.target.canonical,
            confirmed=self.confirmed,
            accepted_warning_reason_codes=(
                plan.warning_reason_codes if self.warnings is None else self.warnings
            ),
        )


class Missing:
    def confirm(self, plan):
        return None


def _validation(*, warning=False):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source = IssueDraftInput.from_mapping(payload)
    draft = build_issue_draft(source, FORM, MAP)
    return validate_issue_draft(
        draft,
        source,
        FORM,
        local_issue_summaries=("Add deterministic issue draft preview",) if warning else (),
    )


def _request(*, validation=None, invocation_id="inv-1", prior=(), optional=()):
    return IssueCreateRequest(
        validation=validation or _validation(),
        target=TARGET,
        invocation_id=invocation_id,
        prior_fingerprints=prior,
        optional_metadata=optional,
    )


def _creates(runner):
    return [call for call in runner.calls if "--body-file=-" in call[0]]


def test_target_and_argv_contract():
    target = GitHubRepositoryTarget.parse("ghe.example.com/acme/widgets")
    assert build_issue_create_argv(
        target,
        "-title",
        ("z", "-label", "z"),
        executable="/usr/local/bin/gh",
    )[-5:] == (
        "--repo=ghe.example.com/acme/widgets",
        "--title=-title",
        "--body-file=-",
        "--label=-label",
        "--label=z",
    )
    for value in (
        "widgets",
        " github.com/acme/widgets",
        "github_com/acme/widgets",
        "github.com/./widgets",
        "github.com/../widgets",
        "github.com/acme/widgets/extra",
        "github.com/acme/",
        "例.example/acme/widgets",
    ):
        with pytest.raises(ValueError):
            GitHubRepositoryTarget.parse(value)


def test_identity_freshness_and_operation_changes():
    first, first_failure = plan_issue_creation(
        _request(invocation_id="one"), FakeRunner()
    )
    second, second_failure = plan_issue_creation(
        _request(invocation_id="two"), FakeRunner()
    )
    assert first_failure is None and second_failure is None
    assert first.operation_identity == second.operation_identity
    assert first.operation_fingerprint != second.operation_fingerprint

    validation = _validation()
    for variant in (
        replace(validation, draft=replace(validation.draft, title="Changed title")),
        replace(validation, draft=replace(validation.draft, body="Changed body")),
        replace(
            validation,
            draft=replace(validation.draft, proposed_labels=("changed-label",)),
        ),
    ):
        changed, changed_failure = plan_issue_creation(
            _request(validation=variant), FakeRunner()
        )
        assert changed_failure is None
        assert changed.operation_identity != first.operation_identity


def test_account_and_executable_only_change_confirmation():
    baseline, failure = plan_issue_creation(_request(), FakeRunner())
    changed, changed_failure = plan_issue_creation(
        _request(), FakeRunner(executable="/opt/gh/bin/gh")
    )
    assert failure is None and changed_failure is None
    assert changed.operation_identity == baseline.operation_identity
    assert changed.operation_fingerprint != baseline.operation_fingerprint


@pytest.mark.parametrize(
    "validation",
    [
        lambda: replace(_validation(), submission_eligible=False),
        lambda: replace(_validation(), status=Status.MANUAL_REVIEW),
        lambda: replace(_validation(), status=Status.FAIL),
        lambda: replace(_validation(), write_authorized=True),
        lambda: replace(_validation(), mutation_performed=True),
    ],
)
def test_ineligible_states_execute_nothing(validation):
    runner = FakeRunner()
    plan, result = plan_issue_creation(_request(validation=validation()), runner)
    assert plan is None
    assert result.reason_code == IssueCreateReasonCode.VALIDATION_INELIGIBLE
    assert runner.calls == []


def test_all_optional_metadata_is_blocked():
    for name in (
        "assignee",
        "milestone",
        "type",
        "parent",
        "blocked-by",
        "blocking",
        "project",
        "recover",
        "template",
        "web",
    ):
        plan, result = plan_issue_creation(
            _request(optional=(name,)), FakeRunner()
        )
        assert plan is None
        assert result.reason_code == IssueCreateReasonCode.OPTIONAL_METADATA_UNSUPPORTED


@pytest.mark.parametrize(
    ("provider", "reason"),
    [
        (Missing(), IssueCreateReasonCode.CONFIRMATION_MISSING),
        (Confirmation(confirmed=False), IssueCreateReasonCode.CONFIRMATION_CANCELLED),
        (
            Confirmation(fingerprint="stale"),
            IssueCreateReasonCode.CONFIRMATION_STALE_OR_MISMATCHED,
        ),
        (
            Confirmation(invocation_id="other"),
            IssueCreateReasonCode.CONFIRMATION_STALE_OR_MISMATCHED,
        ),
        (
            Confirmation(target="github.com/other/repo"),
            IssueCreateReasonCode.CONFIRMATION_STALE_OR_MISMATCHED,
        ),
    ],
)
def test_confirmation_failures_execute_nothing(provider, reason):
    runner = FakeRunner()
    result = execute_issue_creation(_request(), runner, provider)
    assert result.reason_code == reason
    assert result.exit_code == IssueCreateExitCode.CONFIRMATION
    assert _creates(runner) == []


def test_warning_acknowledgement_and_confirmed_success():
    warning_request = _request(validation=_validation(warning=True))
    rejected_runner = FakeRunner()
    rejected = execute_issue_creation(
        warning_request,
        rejected_runner,
        Confirmation(warnings=()),
    )
    assert rejected.reason_code == IssueCreateReasonCode.ELIGIBLE_WARNING_NOT_ACCEPTED
    assert _creates(rejected_runner) == []

    runner = FakeRunner()
    request = _request()
    result = execute_issue_creation(request, runner, Confirmation())
    assert result.reason_code == IssueCreateReasonCode.CREATE_CONFIRMED
    assert result.reason_codes == (IssueCreateReasonCode.CREATE_CONFIRMED,)
    assert result.mutation_state == MutationState.CONFIRMED
    assert result.mutation_performed is True
    assert len(_creates(runner)) == 1
    assert _creates(runner)[0][1] == request.validation.draft.body


@pytest.mark.parametrize(
    ("process", "reason", "exit_code"),
    [
        (
            IssueCreateProcessResult(1, "", "network failed"),
            IssueCreateReasonCode.COMMAND_FAILED,
            76,
        ),
        (
            IssueCreateProcessResult(None, timed_out=True),
            IssueCreateReasonCode.COMMAND_TIMEOUT,
            77,
        ),
        (
            IssueCreateProcessResult(None, interrupted=True),
            IssueCreateReasonCode.COMMAND_INTERRUPTED,
            77,
        ),
        (
            IssueCreateProcessResult(0, "created\n", ""),
            IssueCreateReasonCode.MALFORMED_SUCCESS_OUTPUT,
            78,
        ),
        (
            IssueCreateProcessResult(
                0,
                "https://github.com/Blummer92/agent-os/issues/1\n"
                "https://github.com/Blummer92/agent-os/issues/1\n",
                "",
            ),
            IssueCreateReasonCode.MALFORMED_SUCCESS_OUTPUT,
            78,
        ),
        (
            IssueCreateProcessResult(
                0,
                "https://github.com/Blummer92/agent-os/issues/1?x=1\n",
                "",
            ),
            IssueCreateReasonCode.MALFORMED_SUCCESS_OUTPUT,
            78,
        ),
        (
            IssueCreateProcessResult(
                0,
                "http://github.com/Blummer92/agent-os/issues/1\n",
                "",
            ),
            IssueCreateReasonCode.MALFORMED_SUCCESS_OUTPUT,
            78,
        ),
        (
            IssueCreateProcessResult(
                0,
                "https://github.com/other/repo/issues/1\n",
                "",
            ),
            IssueCreateReasonCode.WRONG_TARGET_SUCCESS_OUTPUT,
            79,
        ),
    ],
)
def test_uncertain_mutation_contract(process, reason, exit_code):
    result = execute_issue_creation(
        _request(), FakeRunner(create=process), Confirmation()
    )
    assert result.reason_code == reason
    assert IssueCreateReasonCode.MUTATION_UNCERTAIN in result.reason_codes
    assert result.exit_code == exit_code
    assert result.mutation_state == MutationState.UNCERTAIN
    assert result.mutation_performed is False
    assert result.retry_allowed is False


def test_unicode_and_controls():
    validation = _validation()
    unicode_validation = replace(
        validation,
        draft=replace(
            validation.draft,
            body=validation.draft.body + "\nRésumé — 東京\n",
        ),
    )
    plan, failure = plan_issue_creation(
        _request(validation=unicode_validation), FakeRunner()
    )
    assert failure is None
    assert "東京" in plan.body

    bad = replace(
        validation,
        draft=replace(validation.draft, body=validation.draft.body + "\x00"),
    )
    plan, failure = plan_issue_creation(_request(validation=bad), FakeRunner())
    assert plan is None
    assert failure.reason_code == IssueCreateReasonCode.VALIDATION_INELIGIBLE
