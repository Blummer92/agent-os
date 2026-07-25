from __future__ import annotations

import inspect
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
    SubprocessGhRunner,
    build_issue_create_argv,
    execute_issue_creation,
    issue_create_result_to_dict,
    plan_issue_creation,
    render_issue_create_result,
    sanitize_diagnostic_text,
)
from scripts.agent_os_issue_labels.validation import validate_issue_draft

ROOT = Path(__file__).resolve().parents[2]
FORM = ROOT / ".github/ISSUE_TEMPLATE/agent-os-task.yml"
MAP = ROOT / ".github/labeler/agent-os-issue-label-map.yml"
FIXTURE = ROOT / "tests/fixtures/agent_os_issue_labels/draft_minimum_valid.json"
TARGET = GitHubRepositoryTarget.parse("Blummer92/agent-os")
AUTH = ("gh", "auth", "status", "--active", "--hostname", "github.com")
REPO = (
    "gh", "repo", "view", "github.com/Blummer92/agent-os", "--json",
    "nameWithOwner,url,hasIssuesEnabled,isArchived",
)


class FakeRunner:
    def __init__(self, create=None, overrides=None):
        self.create = create or IssueCreateProcessResult(
            0, "https://github.com/Blummer92/agent-os/issues/700\n", ""
        )
        self.overrides = overrides or {}
        self.calls = []

    def run(self, argv, *, input_text=None, timeout=30.0):
        key = tuple(argv)
        self.calls.append((key, input_text, timeout))
        if key in self.overrides:
            return self.overrides[key]
        if key == ("gh", "--version"):
            return IssueCreateProcessResult(0, "gh version 2.80.0\n", "")
        if key == ("gh", "issue", "create", "--help"):
            return IssueCreateProcessResult(0, "--repo --title --body-file --label\n", "")
        if key == AUTH:
            return IssueCreateProcessResult(0, "Logged in to github.com account tester\n", "")
        if key == REPO:
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
        if key[:3] == ("gh", "issue", "create"):
            return self.create
        raise AssertionError(key)


class Confirm:
    def __init__(self, *, confirmed=True, mismatch=False, warnings=None):
        self.confirmed = confirmed
        self.mismatch = mismatch
        self.warnings = warnings

    def confirm(self, plan):
        return IssueCreateConfirmation(
            invocation_id="inv-1",
            operation_fingerprint="stale" if self.mismatch else plan.operation_fingerprint,
            target=plan.target.canonical,
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


def _request(*, validation=None, prior=(), optional=()):
    return IssueCreateRequest(
        validation=validation or _validation(),
        target=TARGET,
        invocation_id="inv-1",
        prior_fingerprints=prior,
        optional_metadata=optional,
    )


def _creates(runner):
    return [call for call in runner.calls if call[0][:3] == ("gh", "issue", "create")]


def test_target_and_argv_are_explicit_safe_and_deterministic():
    target = GitHubRepositoryTarget.parse("ghe.example.com/acme/widgets")
    argv = build_issue_create_argv(target, "-title", ("z", "-label", "z"))
    assert argv == (
        "gh", "issue", "create", "--repo=ghe.example.com/acme/widgets",
        "--title=-title", "--body-file=-", "--label=-label", "--label=z",
    )
    with pytest.raises(ValueError):
        GitHubRepositoryTarget.parse("widgets")


def test_plan_is_deterministic_and_does_not_create():
    first_runner = FakeRunner()
    first, failure = plan_issue_creation(_request(), first_runner)
    second, second_failure = plan_issue_creation(_request(), FakeRunner())
    assert failure is None and second_failure is None
    assert first == second
    assert first.body_bytes == len(first.body.encode("utf-8"))
    assert not _creates(first_runner)


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
def test_ineligible_and_upstream_state_drift_never_run(validation):
    runner = FakeRunner()
    plan, result = plan_issue_creation(_request(validation=validation()), runner)
    assert plan is None
    assert result.reason_code == IssueCreateReasonCode.VALIDATION_INELIGIBLE
    assert runner.calls == []
    assert result.write_authorized is False
    assert result.mutation_performed is False


def test_optional_metadata_is_blocked_not_omitted():
    plan, result = plan_issue_creation(_request(optional=("project",)), FakeRunner())
    assert plan is None
    assert result.reason_code == IssueCreateReasonCode.OPTIONAL_METADATA_UNSUPPORTED


@pytest.mark.parametrize(
    ("provider", "reason"),
    [
        (Missing(), IssueCreateReasonCode.CONFIRMATION_MISSING),
        (Confirm(confirmed=False), IssueCreateReasonCode.CONFIRMATION_CANCELLED),
        (Confirm(mismatch=True), IssueCreateReasonCode.CONFIRMATION_STALE_OR_MISMATCHED),
    ],
)
def test_confirmation_failures_execute_zero_create_calls(provider, reason):
    runner = FakeRunner()
    result = execute_issue_creation(_request(), runner, provider)
    assert result.reason_code == reason
    assert result.exit_code == IssueCreateExitCode.CONFIRMATION
    assert result.execution_attempted is False
    assert _creates(runner) == []


def test_warning_requires_exact_acknowledgement():
    request = _request(validation=_validation(warning=True))
    rejected_runner = FakeRunner()
    rejected = execute_issue_creation(request, rejected_runner, Confirm(warnings=()))
    accepted_runner = FakeRunner()
    accepted = execute_issue_creation(request, accepted_runner, Confirm())
    assert rejected.reason_code == IssueCreateReasonCode.ELIGIBLE_WARNING_NOT_ACCEPTED
    assert _creates(rejected_runner) == []
    assert accepted.reason_code == IssueCreateReasonCode.CREATE_CONFIRMED
    assert len(_creates(accepted_runner)) == 1


def test_success_runs_once_with_body_only_on_stdin():
    runner = FakeRunner()
    request = _request()
    result = execute_issue_creation(request, runner, Confirm())
    create = _creates(runner)
    assert result.reason_code == IssueCreateReasonCode.CREATE_CONFIRMED
    assert result.exit_code == 0
    assert result.mutation_state == MutationState.CONFIRMED
    assert result.mutation_performed is True
    assert result.write_authorized is True
    assert result.created_issue_number == 700
    assert len(create) == 1
    assert create[0][1] == request.validation.draft.body
    assert request.validation.draft.body not in create[0][0]


@pytest.mark.parametrize(
    ("process", "reason", "exit_code"),
    [
        (IssueCreateProcessResult(1, "", "network failed"), IssueCreateReasonCode.COMMAND_FAILED, 76),
        (IssueCreateProcessResult(None, timed_out=True), IssueCreateReasonCode.COMMAND_TIMEOUT, 77),
        (IssueCreateProcessResult(None, interrupted=True), IssueCreateReasonCode.COMMAND_INTERRUPTED, 77),
        (IssueCreateProcessResult(0, "created\n", ""), IssueCreateReasonCode.MALFORMED_SUCCESS_OUTPUT, 78),
        (
            IssueCreateProcessResult(
                0,
                "https://github.com/Blummer92/agent-os/issues/1\n"
                "https://github.com/Blummer92/agent-os/issues/2\n",
                "",
            ),
            IssueCreateReasonCode.MALFORMED_SUCCESS_OUTPUT,
            78,
        ),
        (
            IssueCreateProcessResult(0, "https://github.com/other/repo/issues/1\n", ""),
            IssueCreateReasonCode.WRONG_TARGET_SUCCESS_OUTPUT,
            79,
        ),
    ],
)
def test_failure_and_ambiguous_success_are_uncertain(process, reason, exit_code):
    result = execute_issue_creation(_request(), FakeRunner(create=process), Confirm())
    assert result.reason_code == reason
    assert result.exit_code == exit_code
    assert result.mutation_state == MutationState.UNCERTAIN
    assert result.mutation_performed is False
    assert result.retry_allowed is False
    assert result.recovery_evidence


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({("gh", "--version"): IssueCreateProcessResult(1, "", "missing")}, IssueCreateReasonCode.GH_UNAVAILABLE),
        (
            {("gh", "issue", "create", "--help"): IssueCreateProcessResult(0, "--repo --title", "")},
            IssueCreateReasonCode.GH_CAPABILITY_UNSUPPORTED,
        ),
        ({AUTH: IssueCreateProcessResult(4, "", "not logged in")}, IssueCreateReasonCode.AUTHENTICATION_UNAVAILABLE),
        ({AUTH: IssueCreateProcessResult(0, "account one account two", "")}, IssueCreateReasonCode.ACCOUNT_AMBIGUOUS_OR_MISMATCHED),
    ],
)
def test_capability_and_auth_checks_fail_closed(override, reason):
    plan, result = plan_issue_creation(_request(), FakeRunner(overrides=override))
    assert plan is None
    assert result.reason_code == reason


@pytest.mark.parametrize(
    "payload",
    [
        {"nameWithOwner": "other/repo", "url": "https://github.com/other/repo", "hasIssuesEnabled": True, "isArchived": False},
        {"nameWithOwner": "Blummer92/agent-os", "url": "https://github.com/Blummer92/agent-os", "hasIssuesEnabled": True, "isArchived": True},
        {"nameWithOwner": "Blummer92/agent-os", "url": "https://github.com/Blummer92/agent-os", "hasIssuesEnabled": False, "isArchived": False},
    ],
)
def test_target_mismatch_archive_and_disabled_issues_fail_closed(payload):
    plan, result = plan_issue_creation(
        _request(),
        FakeRunner(overrides={REPO: IssueCreateProcessResult(0, json.dumps(payload), "")}),
    )
    assert plan is None
    assert result.reason_code == IssueCreateReasonCode.TARGET_MISMATCHED


def test_repeated_fingerprint_blocks_execution():
    first, failure = plan_issue_creation(_request(), FakeRunner())
    assert failure is None
    runner = FakeRunner()
    plan, result = plan_issue_creation(
        _request(prior=(first.operation_fingerprint,)), runner
    )
    assert plan is None
    assert result.reason_code == IssueCreateReasonCode.REPEAT_INVOCATION_DETECTED
    assert result.exit_code == 80
    assert not _creates(runner)


def test_redaction_bounding_and_serializers_never_leak_secrets():
    secret = "github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"
    diagnostic = (
        f"\x1b[31mAuthorization: Bearer {secret}\npassword=hunter2\n"
        "https://u:p@example.com/\n" + "x" * 5000
    )
    sanitized = sanitize_diagnostic_text(diagnostic, limit=100)
    result = execute_issue_creation(
        _request(), FakeRunner(create=IssueCreateProcessResult(1, secret, diagnostic)), Confirm()
    )
    rendered = render_issue_create_result(result)
    payload = json.dumps(issue_create_result_to_dict(result), sort_keys=True)
    assert secret not in sanitized + rendered + payload
    assert "hunter2" not in sanitized
    assert "u:p@" not in sanitized
    assert "\x1b" not in sanitized
    assert "TRUNCATED" in sanitized
    assert result.operation_fingerprint in rendered


def test_unicode_stdin_and_unsupported_controls():
    validation = _validation()
    unicode_validation = replace(
        validation,
        draft=replace(validation.draft, body=validation.draft.body + "\nRésumé — 東京\n"),
    )
    plan, failure = plan_issue_creation(_request(validation=unicode_validation), FakeRunner())
    assert failure is None
    assert "東京" in plan.body
    bad = replace(validation, draft=replace(validation.draft, body=validation.draft.body + "\x00"))
    with pytest.raises(ValueError):
        plan_issue_creation(_request(validation=bad), FakeRunner())


def test_concrete_runner_has_no_shell_or_forbidden_auth_paths():
    source = inspect.getsource(SubprocessGhRunner.run)
    module_source = Path(inspect.getsourcefile(SubprocessGhRunner)).read_text(encoding="utf-8")
    forbidden_create_literal = " ".join(("gh", "issue", "create"))
    assert "shell=False" in source
    assert "shell=True" not in module_source
    assert "gh auth token" not in module_source
    assert "--show-token" not in module_source
    assert "gh auth refresh" not in module_source
    assert forbidden_create_literal not in Path(__file__).read_text(encoding="utf-8")
