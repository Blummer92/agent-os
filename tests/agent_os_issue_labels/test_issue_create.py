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


class FakeRunner:
    def __init__(self, *, create: IssueCreateProcessResult | None = None, overrides=None):
        self.create = create or IssueCreateProcessResult(
            0, "https://github.com/Blummer92/agent-os/issues/700\n", ""
        )
        self.overrides = overrides or {}
        self.calls: list[tuple[tuple[str, ...], str | None, float]] = []

    def run(self, argv, *, input_text=None, timeout=30.0):
        key = tuple(argv)
        self.calls.append((key, input_text, timeout))
        if key in self.overrides:
            return self.overrides[key]
        if key == ("gh", "--version"):
            return IssueCreateProcessResult(0, "gh version 2.80.0\n", "")
        if key == ("gh", "issue", "create", "--help"):
            return IssueCreateProcessResult(
                0, "--repo --title --body-file --label\n", ""
            )
        if key[:4] == ("gh", "auth", "status", "--active"):
            return IssueCreateProcessResult(
                0, "Logged in to github.com account tester\n", ""
            )
        if key[:3] == ("gh", "repo", "view"):
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
        raise AssertionError(f"unexpected argv: {key}")


class ExactConfirmation:
    def __init__(self, invocation_id="inv-1", *, confirmed=True, mismatch=False, warnings=None):
        self.invocation_id = invocation_id
        self.confirmed = confirmed
        self.mismatch = mismatch
        self.warnings = warnings

    def confirm(self, plan):
        return IssueCreateConfirmation(
            invocation_id=self.invocation_id,
            operation_fingerprint=("stale" if self.mismatch else plan.operation_fingerprint),
            target=plan.target.canonical,
            confirmed=self.confirmed,
            accepted_warning_reason_codes=(
                plan.warning_reason_codes if self.warnings is None else self.warnings
            ),
        )


class MissingConfirmation:
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
        local_issue_summaries=(
            "Add deterministic issue draft preview",
        ) if warning else (),
    )


def _request(*, validation=None, target=TARGET, prior=(), optional=()):
    return IssueCreateRequest(
        validation=validation or _validation(),
        target=target,
        invocation_id="inv-1",
        prior_fingerprints=prior,
        optional_metadata=optional,
    )


def _create_calls(runner):
    return [call for call in runner.calls if call[0][:3] == ("gh", "issue", "create")]


def test_explicit_target_parser_and_safe_argv():
    target = GitHubRepositoryTarget.parse("ghe.example.com/acme/widgets")
    argv = build_issue_create_argv(target, "-title", ("z", "-label", "z"))

    assert target.canonical == "ghe.example.com/acme/widgets"
    assert argv == (
        "gh",
        "issue",
        "create",
        "--repo=ghe.example.com/acme/widgets",
        "--title=-title",
        "--body-file=-",
        "--label=-label",
        "--label=z",
    )
    with pytest.raises(ValueError):
        GitHubRepositoryTarget.parse("widgets")


def test_eligible_result_plans_deterministically_without_execution():
    runner = FakeRunner()
    first, failure = plan_issue_creation(_request(), runner)
    second, second_failure = plan_issue_creation(_request(), FakeRunner())

    assert failure is None and second_failure is None
    assert first == second
    assert first.operation_fingerprint
    assert first.body_digest
    assert first.body_bytes == len(first.body.encode("utf-8"))
    assert not _create_calls(runner)


@pytest.mark.parametrize(
    ("validation", "reason"),
    [
        (lambda: replace(_validation(), submission_eligible=False), IssueCreateReasonCode.VALIDATION_INELIGIBLE),
        (lambda: replace(_validation(), status=Status.MANUAL_REVIEW), IssueCreateReasonCode.VALIDATION_INELIGIBLE),
        (lambda: replace(_validation(), status=Status.FAIL), IssueCreateReasonCode.VALIDATION_INELIGIBLE),
        (lambda: replace(_validation(), write_authorized=True), IssueCreateReasonCode.VALIDATION_INELIGIBLE),
        (lambda: replace(_validation(), mutation_performed=True), IssueCreateReasonCode.VALIDATION_INELIGIBLE),
    ],
)
def test_ineligible_or_upstream_state_drift_never_reaches_runner(validation, reason):
    runner = FakeRunner()
    plan, failure = plan_issue_creation(_request(validation=validation()), runner)

    assert plan is None
    assert failure.reason_code == reason
    assert runner.calls == []
    assert failure.write_authorized is False
    assert failure.mutation_performed is False


def test_unsupported_optional_metadata_is_blocked_not_dropped():
    runner = FakeRunner()
    plan, failure = plan_issue_creation(_request(optional=("project",)), runner)

    assert plan is None
    assert failure.reason_code == IssueCreateReasonCode.OPTIONAL_METADATA_UNSUPPORTED
    assert runner.calls == []


@pytest.mark.parametrize(
    ("provider", "reason"),
    [
        (MissingConfirmation(), IssueCreateReasonCode.CONFIRMATION_MISSING),
        (ExactConfirmation(confirmed=False), IssueCreateReasonCode.CONFIRMATION_CANCELLED),
        (ExactConfirmation(mismatch=True), IssueCreateReasonCode.CONFIRMATION_STALE_OR_MISMATCHED),
    ],
)
def test_missing_cancelled_or_stale_confirmation_executes_nothing(provider, reason):
    runner = FakeRunner()
    result = execute_issue_creation(_request(), runner, provider)

    assert result.reason_code == reason
    assert result.exit_code == IssueCreateExitCode.CONFIRMATION
    assert result.execution_attempted is False
    assert _create_calls(runner) == []


def test_warning_requires_exact_acknowledgement():
    request = _request(validation=_validation(warning=True))
    rejected_runner = FakeRunner()
    rejected = execute_issue_creation(
        request,
        rejected_runner,
        ExactConfirmation(warnings=()),
    )
    accepted_runner = FakeRunner()
    accepted = execute_issue_creation(request, accepted_runner, ExactConfirmation())

    assert rejected.reason_code == IssueCreateReasonCode.ELIGIBLE_WARNING_NOT_ACCEPTED
    assert _create_calls(rejected_runner) == []
    assert accepted.reason_code == IssueCreateReasonCode.CREATE_CONFIRMED
    assert len(_create_calls(accepted_runner)) == 1


def test_confirmed_execution_uses_one_argv_call_and_body_only_on_stdin():
    runner = FakeRunner()
    request = _request()
    result = execute_issue_creation(request, runner, ExactConfirmation())
    create_call = _create_calls(runner)

    assert result.reason_code == IssueCreateReasonCode.CREATE_CONFIRMED
    assert result.exit_code == 0
    assert result.mutation_state == MutationState.CONFIRMED
    assert result.mutation_performed is True
    assert result.write_authorized is True
    assert result.created_issue_number == 700
    assert len(create_call) == 1
    argv, stdin_body, _ = create_call[0]
    assert request.validation.draft.body == stdin_body
    assert request.validation.draft.body not in argv
    assert all(isinstance(value, str) for value in argv)


@pytest.mark.parametrize(
    ("process", "reason", "exit_code"),
    [
        (IssueCreateProcessResult(1, "", "network failed"), IssueCreateReasonCode.COMMAND_FAILED, 76),
        (IssueCreateProcessResult(None, "", "", timed_out=True), IssueCreateReasonCode.COMMAND_TIMEOUT, 77),
        (IssueCreateProcessResult(None, "", "", interrupted=True), IssueCreateReasonCode.COMMAND_INTERRUPTED, 77),
        (IssueCreateProcessResult(0, "created\n", ""), IssueCreateReasonCode.MALFORMED_SUCCESS_OUTPUT, 78),
        (
            IssueCreateProcessResult(
                0,
                "https://github.com/Blummer92/agent-os/issues/1\nhttps://github.com/Blummer92/agent-os/issues/2\n",
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
def test_failed_or_ambiguous_execution_is_uncertain_and_not_retryable(process, reason, exit_code):
    result = execute_issue_creation(
        _request(),
        FakeRunner(create=process),
        ExactConfirmation(),
    )

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
        (
            {("gh", "auth", "status", "--active", "--hostname", "github.com"): IssueCreateProcessResult(4, "", "not logged in")},
            IssueCreateReasonCode.AUTHENTICATION_UNAVAILABLE,
        ),
        (
            {("gh", "auth", "status", "--active", "--hostname", "github.com"): IssueCreateProcessResult(0, "account one account two", "")},
            IssueCreateReasonCode.ACCOUNT_AMBIGUOUS_OR_MISMATCHED,
        ),
    ],
)
def test_capability_and_auth_fail_closed(override, reason):
    plan, failure = plan_issue_creation(_request(), FakeRunner(overrides=override))

    assert plan is None
    assert failure.reason_code == reason


def test_repository_mismatch_archived_and_issues_disabled_fail_closed():
    command = (
        "gh",
        "repo",
        "view",
        "github.com/Blummer92/agent-os",
        "--json",
        "nameWithOwner,url,hasIssuesEnabled,isArchived",
    )
    for payload in (
        {"nameWithOwner": "other/repo", "url": "https://github.com/other/repo", "hasIssuesEnabled": True, "isArchived": False},
        {"nameWithOwner": "Blummer92/agent-os", "url": "https://github.com/Blummer92/agent-os", "hasIssuesEnabled": True, "isArchived": True},
        {"nameWithOwner": "Blummer92/agent-os", "url": "https://github.com/Blummer92/agent-os", "hasIssuesEnabled": False, "isArchived": False},
    ):
        runner = FakeRunner(overrides={command: IssueCreateProcessResult(0, json.dumps(payload), "")})
        plan, failure = plan_issue_creation(_request(), runner)
        assert plan is None
        assert failure.reason_code == IssueCreateReasonCode.TARGET_MISMATCHED


def test_repeat_fingerprint_blocks_execution():
    first, failure = plan_issue_creation(_request(), FakeRunner())
    assert failure is None
    repeated_runner = FakeRunner()
    plan, repeated = plan_issue_creation(
        _request(prior=(first.operation_fingerprint,)),
        repeated_runner,
    )

    assert plan is None
    assert repeated.reason_code == IssueCreateReasonCode.REPEAT_INVOCATION_DETECTED
    assert repeated.exit_code == 80
    assert _create_calls(repeated_runner) == []


def test_redaction_and_bounding_are_applied_to_all_result_output():
    secret = "github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"
    diagnostic = f"\x1b[31mAuthorization: Bearer {secret}\npassword=hunter2\nhttps://u:p@example.com/\n" + "x" * 5000
    sanitized = sanitize_diagnostic_text(diagnostic, limit=100)
    result = execute_issue_creation(
        _request(),
        FakeRunner(create=IssueCreateProcessResult(1, secret, diagnostic)),
        ExactConfirmation(),
    )

    assert secret not in sanitized
    assert "hunter2" not in sanitized
    assert "u:p@" not in sanitized
    assert "\x1b" not in sanitized
    assert "TRUNCATED" in sanitized
    rendered = render_issue_create_result(result)
    payload = json.dumps(issue_create_result_to_dict(result), sort_keys=True)
    assert secret not in rendered
    assert secret not in payload


def test_text_and_json_share_the_same_immutable_result():
    result = execute_issue_creation(_request(), FakeRunner(), ExactConfirmation())
    payload = issue_create_result_to_dict(result)
    rendered = render_issue_create_result(result)

    assert payload["reason_code"] == result.reason_code.value
    assert payload["mutation_state"] == result.mutation_state.value
    assert result.operation_fingerprint in rendered
    assert result.created_issue_url in rendered


def test_subprocess_boundary_is_non_shell_and_forbidden_commands_are_absent():
    source = inspect.getsource(SubprocessGhRunner.run)
    module_source = Path(inspect.getsourcefile(SubprocessGhRunner)).read_text(encoding="utf-8")

    assert "shell=False" in source
    assert "shell=True" not in module_source
    assert "gh auth token" not in module_source
    assert "--show-token" not in module_source
    assert "gh auth refresh" not in module_source
    assert "gh issue create" not in Path(__file__).read_text(encoding="utf-8")


def test_unicode_body_and_control_rejection():
    validation = _validation()
    unicode_draft = replace(
        validation.draft,
        body=validation.draft.body + "\nRésumé — 東京\n",
    )
    plan, failure = plan_issue_creation(
        _request(validation=replace(validation, draft=unicode_draft)),
        FakeRunner(),
    )
    assert failure is None
    assert "東京" in plan.body

    bad_draft = replace(validation.draft, body=validation.draft.body + "\x00")
    with pytest.raises(ValueError):
        plan_issue_creation(
            _request(validation=replace(validation, draft=bad_draft)),
            FakeRunner(),
        )
