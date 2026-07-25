from __future__ import annotations

import inspect
import json
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.agent_os_issue_acceptance.models import Status
from scripts.agent_os_issue_labels import issue_create_cli
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
    def __init__(self, *, executable="gh", create=None, overrides=None):
        self.executable = executable
        self.create = create or IssueCreateProcessResult(
            0, "https://github.com/Blummer92/agent-os/issues/700\n", ""
        )
        self.overrides = overrides or {}
        self.calls = []

    def resolve_executable(self):
        return self.executable

    def run(self, argv, *, input_text=None, timeout=30.0):
        key = tuple(argv)
        self.calls.append((key, input_text, timeout))
        if key in self.overrides:
            return self.overrides[key]
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
        raise AssertionError(f"unexpected argv: {key}")


class MissingConfirmation:
    def confirm(self, plan):
        return None


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


def _request(
    *,
    validation=None,
    target=TARGET,
    invocation_id="inv-1",
    prior=(),
    optional=(),
):
    return IssueCreateRequest(
        validation=validation or _validation(),
        target=target,
        invocation_id=invocation_id,
        prior_fingerprints=prior,
        optional_metadata=optional,
    )


def _create_calls(runner):
    return [call for call in runner.calls if "--body-file=-" in call[0]]


def _repo_command(runner):
    return (
        runner.executable,
        "repo",
        "view",
        "github.com/Blummer92/agent-os",
        "--json",
        "nameWithOwner,url,hasIssuesEnabled,isArchived",
    )


def test_target_and_argv_are_explicit_and_safe():
    target = GitHubRepositoryTarget.parse("ghe.example.com/acme/widgets")
    argv = build_issue_create_argv(
        target,
        "-title",
        ("z", "-label", "z"),
        executable="/usr/local/bin/gh",
    )
    assert argv == (
        "/usr/local/bin/gh",
        "issue",
        "create",
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
    with pytest.raises(ValueError):
        build_issue_create_argv(target, "bad\ntitle", ())
    with pytest.raises(ValueError):
        build_issue_create_argv(target, "title", ("bad\rlabel",))


def test_operation_identity_is_stable_and_confirmation_is_fresh():
    first, first_failure = plan_issue_creation(
        _request(invocation_id="one"), FakeRunner()
    )
    second, second_failure = plan_issue_creation(
        _request(invocation_id="two"), FakeRunner()
    )
    assert first_failure is None and second_failure is None
    assert first.operation_identity == second.operation_identity
    assert first.operation_fingerprint != second.operation_fingerprint


def test_operation_changes_change_identity_and_confirmation():
    baseline, failure = plan_issue_creation(_request(), FakeRunner())
    assert failure is None
    validation = _validation()
    variants = (
        replace(validation, draft=replace(validation.draft, title="Changed title")),
        replace(validation, draft=replace(validation.draft, body="Changed body")),
        replace(
            validation,
            draft=replace(validation.draft, proposed_labels=("changed-label",)),
        ),
    )
    for variant in variants:
        changed, changed_failure = plan_issue_creation(
            _request(validation=variant), FakeRunner()
        )
        assert changed_failure is None
        assert changed.operation_identity != baseline.operation_identity
        assert changed.operation_fingerprint != baseline.operation_fingerprint


def test_account_capability_and_executable_change_confirmation():
    baseline, failure = plan_issue_creation(_request(), FakeRunner())
    assert failure is None
    changed, changed_failure = plan_issue_creation(
        _request(), FakeRunner(executable="/opt/gh/bin/gh")
    )
    assert changed_failure is None
    assert changed.argv[0] == changed.capability.executable_path == "/opt/gh/bin/gh"
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
def test_ineligible_and_upstream_state_drift_never_reach_runner(validation):
    runner = FakeRunner()
    plan, result = plan_issue_creation(_request(validation=validation()), runner)
    assert plan is None
    assert result.reason_code == IssueCreateReasonCode.VALIDATION_INELIGIBLE
    assert runner.calls == []
    assert result.write_authorized is False
    assert result.mutation_performed is False


def test_unsupported_metadata_is_blocked_not_omitted():
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
        (MissingConfirmation(), IssueCreateReasonCode.CONFIRMATION_MISSING),
        (
            Confirmation(confirmed=False),
            IssueCreateReasonCode.CONFIRMATION_CANCELLED,
        ),
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
    assert result.execution_attempted is False
    assert _create_calls(runner) == []


def test_warning_requires_exact_acknowledgement():
    request = _request(validation=_validation(warning=True))
    rejected_runner = FakeRunner()
    rejected = execute_issue_creation(
        request,
        rejected_runner,
        Confirmation(warnings=()),
    )
    accepted_runner = FakeRunner()
    accepted = execute_issue_creation(request, accepted_runner, Confirmation())
    assert rejected.reason_code == IssueCreateReasonCode.ELIGIBLE_WARNING_NOT_ACCEPTED
    assert _create_calls(rejected_runner) == []
    assert accepted.reason_code == IssueCreateReasonCode.CREATE_CONFIRMED
    assert len(_create_calls(accepted_runner)) == 1


def test_confirmed_create_uses_one_call_and_body_only_on_stdin():
    runner = FakeRunner()
    request = _request()
    result = execute_issue_creation(request, runner, Confirmation())
    calls = _create_calls(runner)
    assert result.reason_code == IssueCreateReasonCode.CREATE_CONFIRMED
    assert result.reason_codes == (IssueCreateReasonCode.CREATE_CONFIRMED,)
    assert result.exit_code == 0
    assert result.write_authorized is True
    assert result.mutation_state == MutationState.CONFIRMED
    assert result.mutation_performed is True
    assert result.created_issue_number == 700
    assert len(calls) == 1
    assert calls[0][1] == request.validation.draft.body
    assert request.validation.draft.body not in calls[0][0]


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
def test_failed_or_ambiguous_execution_is_uncertain(
    process,
    reason,
    exit_code,
):
    result = execute_issue_creation(
        _request(), FakeRunner(create=process), Confirmation()
    )
    assert result.reason_code == reason
    assert IssueCreateReasonCode.MUTATION_UNCERTAIN in result.reason_codes
    assert result.exit_code == exit_code
    assert result.mutation_state == MutationState.UNCERTAIN
    assert result.mutation_performed is False
    assert result.retry_allowed is False
    assert result.recovery_evidence


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        (
            {("gh", "--version"): IssueCreateProcessResult(1, "", "missing")},
            IssueCreateReasonCode.GH_UNAVAILABLE,
        ),
        (
            {
                ("gh", "issue", "create", "--help"): IssueCreateProcessResult(
                    0,
                    "--repository --title --body-file --label\n",
                    "",
                )
            },
            IssueCreateReasonCode.GH_CAPABILITY_UNSUPPORTED,
        ),
        (
            {
                (
                    "gh",
                    "auth",
                    "status",
                    "--active",
                    "--hostname",
                    "github.com",
                ): IssueCreateProcessResult(4, "", "not logged in")
            },
            IssueCreateReasonCode.AUTHENTICATION_UNAVAILABLE,
        ),
        (
            {
                (
                    "gh",
                    "auth",
                    "status",
                    "--active",
                    "--hostname",
                    "github.com",
                ): IssueCreateProcessResult(
                    0,
                    "Logged in to github.com account one\n"
                    "Logged in to github.com account two\n",
                    "",
                )
            },
            IssueCreateReasonCode.ACCOUNT_AMBIGUOUS_OR_MISMATCHED,
        ),
    ],
)
def test_capability_and_authentication_fail_closed(overrides, reason):
    plan, result = plan_issue_creation(
        _request(), FakeRunner(overrides=overrides)
    )
    assert plan is None
    assert result.reason_code == reason


def test_missing_executable_fails_closed():
    runner = FakeRunner()
    runner.executable = None
    plan, result = plan_issue_creation(_request(), runner)
    assert plan is None
    assert result.reason_code == IssueCreateReasonCode.GH_UNAVAILABLE


def test_version_is_informational_when_required_features_pass():
    plan, result = plan_issue_creation(
        _request(),
        FakeRunner(
            overrides={
                ("gh", "--version"): IssueCreateProcessResult(
                    0, "custom gh build\n", ""
                )
            }
        ),
    )
    assert result is None
    assert plan.capability.version == "custom gh build"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "nameWithOwner": "other/repo",
            "url": "https://github.com/other/repo",
            "hasIssuesEnabled": True,
            "isArchived": False,
        },
        {
            "nameWithOwner": "Blummer92/agent-os",
            "url": "https://github.com/Blummer92/agent-os",
            "hasIssuesEnabled": True,
            "isArchived": True,
        },
        {
            "nameWithOwner": "Blummer92/agent-os",
            "url": "https://github.com/Blummer92/agent-os",
            "hasIssuesEnabled": False,
            "isArchived": False,
        },
        {
            "nameWithOwner": "Blummer92/agent-os",
            "url": "https://github.com/Blummer92/agent-os?x=1",
            "hasIssuesEnabled": True,
            "isArchived": False,
        },
    ],
)
def test_repository_mismatch_archive_and_disabled_issues_fail_closed(payload):
    runner = FakeRunner()
    plan, result = plan_issue_creation(
        _request(),
        FakeRunner(
            overrides={
                _repo_command(runner): IssueCreateProcessResult(
                    0, json.dumps(payload), ""
                )
            }
        ),
    )
    assert plan is None
    assert result.reason_code == IssueCreateReasonCode.TARGET_MISMATCHED


def test_repeated_stable_identity_blocks_new_invocation():
    first, failure = plan_issue_creation(
        _request(invocation_id="first"), FakeRunner()
    )
    assert failure is None
    runner = FakeRunner()
    plan, result = plan_issue_creation(
        _request(
            invocation_id="second",
            prior=(first.operation_identity,),
        ),
        runner,
    )
    assert plan is None
    assert result.reason_code == IssueCreateReasonCode.REPEAT_INVOCATION_DETECTED
    assert result.exit_code == 80
    assert result.retry_allowed is False
    assert _create_calls(runner) == []


@pytest.mark.parametrize(
    "stderr",
    [
        "network unavailable",
        "rate limit exceeded",
        "permission denied",
        "authentication expired",
    ],
)
def test_external_failures_preserve_bounded_sanitized_evidence(stderr):
    result = execute_issue_creation(
        _request(),
        FakeRunner(create=IssueCreateProcessResult(1, "", stderr)),
        Confirmation(),
    )
    assert result.reason_code == IssueCreateReasonCode.COMMAND_FAILED
    assert stderr in result.sanitized_stderr
    assert IssueCreateReasonCode.MUTATION_UNCERTAIN in result.reason_codes


def test_redaction_covers_credentials_and_submitted_content():
    secret = "github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"
    title_secret = "private title"
    label_secret = "private-label"
    body_secret = "private body"
    validation = _validation()
    validation = replace(
        validation,
        draft=replace(
            validation.draft,
            title=title_secret,
            body=body_secret,
            proposed_labels=(label_secret,),
        ),
    )
    diagnostic = (
        "\x1b[31mAuthorization: Basic abc\nBearer abc.def\n"
        f"token={secret}\npassword='hunter2'\n"
        "https://u:p@example.com/\n"
        f"{title_secret}\n{label_secret}\n{body_secret}\n"
    )
    result = execute_issue_creation(
        _request(validation=validation),
        FakeRunner(create=IssueCreateProcessResult(1, secret, diagnostic)),
        Confirmation(),
    )
    combined = render_issue_create_result(result) + json.dumps(
        issue_create_result_to_dict(result), sort_keys=True
    )
    for value in (
        secret,
        "abc.def",
        "hunter2",
        "u:p@",
        title_secret,
        label_secret,
        body_secret,
    ):
        assert value not in combined
    assert "\x1b" not in combined


def test_redaction_and_truncation_are_independent():
    sanitized = sanitize_diagnostic_text(
        "ghp_ABCDEFGHIJKL\rsecret=abc\n\x08public"
    )
    assert "ABCDEFGHIJKL" not in sanitized
    assert "secret=abc" not in sanitized
    assert "\r" not in sanitized
    assert "\x08" not in sanitized
    assert "TRUNCATED" in sanitize_diagnostic_text(
        "public\n" + "x" * 5000, limit=100
    )


def test_unicode_body_and_control_rejection():
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


def test_cli_invalid_input_uses_offline_usage_exit(tmp_path, capsys):
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    code = issue_create_cli.main(
        ["--input", str(malformed), "--target", "Blummer92/agent-os"]
    )
    assert code == 64
    assert "issue-create input error" in capsys.readouterr().err


def test_cli_planning_mode_never_executes_create(monkeypatch, capsys):
    runner = FakeRunner()
    monkeypatch.setattr(issue_create_cli, "SubprocessGhRunner", lambda: runner)
    code = issue_create_cli.main(
        [
            "--input",
            str(FIXTURE),
            "--target",
            "Blummer92/agent-os",
            "--issue-form",
            str(FORM),
            "--label-map",
            str(MAP),
            "--format",
            "json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == IssueCreateExitCode.CONFIRMATION
    assert payload["reason_code"] == IssueCreateReasonCode.CONFIRMATION_MISSING.value
    assert _create_calls(runner) == []


def test_cli_confirmation_diagnostics_hide_raw_content(monkeypatch, capsys):
    validation = _validation()
    validation = replace(
        validation,
        draft=replace(
            validation.draft,
            title="secret title",
            proposed_labels=("secret-label",),
        ),
    )
    plan, failure = plan_issue_creation(
        _request(validation=validation), FakeRunner()
    )
    assert failure is None
    monkeypatch.setattr("builtins.input", lambda prompt: "no")
    confirmation = issue_create_cli._PromptConfirmation().confirm(plan)
    captured = capsys.readouterr()
    assert confirmation.confirmed is False
    assert "secret title" not in captured.err
    assert "secret-label" not in captured.err
    assert plan.operation_identity in captured.err


def test_serializers_derive_from_one_immutable_result():
    result = execute_issue_creation(
        _request(),
        FakeRunner(create=IssueCreateProcessResult(1, "", "failure")),
        Confirmation(),
    )
    payload = issue_create_result_to_dict(result)
    rendered = render_issue_create_result(result)
    assert payload["reason_code"] == result.reason_code.value
    assert IssueCreateReasonCode.MUTATION_UNCERTAIN.value in payload["reason_codes"]
    assert result.operation_identity in rendered
    assert result.operation_fingerprint in rendered


def test_concrete_runner_has_no_shell_or_forbidden_auth_paths():
    source = inspect.getsource(SubprocessGhRunner.run)
    module_source = Path(inspect.getsourcefile(SubprocessGhRunner)).read_text(
        encoding="utf-8"
    )
    assert "subprocess.Popen" in source
    assert "shell=False" in source
    for forbidden in (
        "shell=True",
        "os.system",
        "gh auth token",
        "--show-token",
        "gh auth refresh",
    ):
        assert forbidden not in module_source
    assert 'env.pop("GH_REPO"' in module_source
    assert 'env.pop("GH_HOST"' in module_source
