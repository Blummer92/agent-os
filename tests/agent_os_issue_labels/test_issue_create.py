from __future__ import annotations

import inspect
import json
import tempfile
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
from scripts.agent_os_issue_labels.validation import DraftReasonCode, validate_issue_draft

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
        defaults = {
            (self.executable, "--version"): IssueCreateProcessResult(
                0, "gh version 2.80.0\n", ""
            ),
            (self.executable, "issue", "create", "--help"): IssueCreateProcessResult(
                0, "--repo --title --body-file --label\n", ""
            ),
            (
                self.executable, "auth", "status", "--active", "--hostname",
                "github.com",
            ): IssueCreateProcessResult(
                0, "Logged in to github.com account tester\n", ""
            ),
            (
                self.executable, "repo", "view", "github.com/Blummer92/agent-os",
                "--json", "nameWithOwner,url,hasIssuesEnabled,isArchived",
            ): IssueCreateProcessResult(
                0,
                json.dumps({
                    "nameWithOwner": "Blummer92/agent-os",
                    "url": "https://github.com/Blummer92/agent-os",
                    "hasIssuesEnabled": True,
                    "isArchived": False,
                }),
                "",
            ),
        }
        if key in defaults:
            return defaults[key]
        if "--body-file=-" in key:
            return self.create
        raise AssertionError(key)


class Confirmation:
    def __init__(
        self, *, invocation="inv-1", confirmed=True, fingerprint=None,
        target=None, warnings=None
    ):
        self.invocation = invocation
        self.confirmed = confirmed
        self.fingerprint = fingerprint
        self.target = target
        self.warnings = warnings

    def confirm(self, plan):
        return IssueCreateConfirmation(
            self.invocation,
            self.fingerprint or plan.operation_fingerprint,
            self.target or plan.target.canonical,
            self.confirmed,
            plan.warning_reason_codes if self.warnings is None else self.warnings,
        )


class MissingConfirmation:
    def confirm(self, plan):
        return None


def make_validation():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source = IssueDraftInput.from_mapping(payload)
    draft = build_issue_draft(source, FORM, MAP)
    return validate_issue_draft(draft, source, FORM)


def make_request(*, validation=None, invocation="inv-1", prior=(), optional=()):
    return IssueCreateRequest(
        validation or make_validation(), TARGET, invocation,
        prior_fingerprints=prior, optional_metadata=optional,
    )


def create_calls(runner):
    return [call for call in runner.calls if "--body-file=-" in call[0]]


def warning_validation():
    return replace(
        make_validation(), status=Status.WARN,
        reason_codes=(
            DraftReasonCode.ELIGIBLE_WARNING,
            DraftReasonCode.DUPLICATE_CANDIDATE_ADVISORY,
        ),
        submission_eligible=True,
    )


@pytest.mark.parametrize(
    "value",
    (
        "widgets", " github.com/acme/widgets", "github_com/acme/widgets",
        "github.com/./widgets", "github.com/../widgets",
        "github.com/acme/widgets/extra", "github.com/acme/",
        "例.example/acme/widgets",
    ),
)
def test_explicit_target_parsing(value):
    with pytest.raises(ValueError):
        GitHubRepositoryTarget.parse(value)


def test_safe_immutable_argv_and_controls():
    target = GitHubRepositoryTarget.parse("ghe.example.com/acme/widgets")
    assert build_issue_create_argv(
        target, "-title", ("z", "-label", "z"), executable="/opt/gh"
    ) == (
        "/opt/gh", "issue", "create", "--repo=ghe.example.com/acme/widgets",
        "--title=-title", "--body-file=-", "--label=-label", "--label=z",
    )
    with pytest.raises(ValueError):
        build_issue_create_argv(target, "bad\ntitle", ())
    with pytest.raises(ValueError):
        build_issue_create_argv(target, "title", ("bad\rlabel",))


def test_identity_eligibility_and_optional_metadata():
    first, error = plan_issue_creation(make_request(invocation="one"), FakeRunner())
    second, second_error = plan_issue_creation(
        make_request(invocation="two"), FakeRunner()
    )
    assert error is second_error is None
    assert first.operation_identity == second.operation_identity
    assert first.operation_fingerprint != second.operation_fingerprint
    for changed in (
        replace(make_validation(), submission_eligible=False),
        replace(make_validation(), status=Status.MANUAL_REVIEW),
        replace(make_validation(), status=Status.FAIL),
        replace(make_validation(), write_authorized=True),
        replace(make_validation(), mutation_performed=True),
    ):
        runner = FakeRunner()
        plan, failure = plan_issue_creation(make_request(validation=changed), runner)
        assert plan is None
        assert failure.reason_code == IssueCreateReasonCode.VALIDATION_INELIGIBLE
        assert runner.calls == []
    plan, failure = plan_issue_creation(
        make_request(optional=("assignee",)), FakeRunner()
    )
    assert plan is None
    assert failure.reason_code == IssueCreateReasonCode.OPTIONAL_METADATA_UNSUPPORTED


@pytest.mark.parametrize(
    "provider, expected",
    (
        (MissingConfirmation(), IssueCreateReasonCode.CONFIRMATION_MISSING),
        (Confirmation(confirmed=False), IssueCreateReasonCode.CONFIRMATION_CANCELLED),
        (
            Confirmation(fingerprint="stale"),
            IssueCreateReasonCode.CONFIRMATION_STALE_OR_MISMATCHED,
        ),
        (
            Confirmation(invocation="other"),
            IssueCreateReasonCode.CONFIRMATION_STALE_OR_MISMATCHED,
        ),
        (
            Confirmation(target="github.com/other/repo"),
            IssueCreateReasonCode.CONFIRMATION_STALE_OR_MISMATCHED,
        ),
    ),
)
def test_confirmation_failures(provider, expected):
    runner = FakeRunner()
    result = execute_issue_creation(make_request(), runner, provider)
    assert result.reason_code == expected
    assert create_calls(runner) == []


def test_warning_success_stdin_repeat_and_serializers():
    warning = warning_validation()
    rejected_runner = FakeRunner()
    rejected = execute_issue_creation(
        make_request(validation=warning), rejected_runner, Confirmation(warnings=())
    )
    assert rejected.reason_code == IssueCreateReasonCode.ELIGIBLE_WARNING_NOT_ACCEPTED
    assert create_calls(rejected_runner) == []
    runner = FakeRunner()
    request = make_request(validation=warning)
    result = execute_issue_creation(request, runner, Confirmation())
    call = create_calls(runner)[0]
    assert result.reason_code == IssueCreateReasonCode.CREATE_CONFIRMED
    assert result.mutation_state == MutationState.CONFIRMED
    assert call[1] == request.validation.draft.body
    assert request.validation.draft.body not in call[0]
    plan, error = plan_issue_creation(make_request(invocation="first"), FakeRunner())
    assert error is None
    repeated_plan, repeated = plan_issue_creation(
        make_request(invocation="second", prior=(plan.operation_identity,)),
        FakeRunner(),
    )
    assert repeated_plan is None and repeated.exit_code == 80
    payload = issue_create_result_to_dict(result)
    assert payload["reason_code"] == result.reason_code.value
    assert result.operation_identity in render_issue_create_result(result)


@pytest.mark.parametrize(
    "process, reason, exit_code",
    (
        (IssueCreateProcessResult(1, "", "network"), IssueCreateReasonCode.COMMAND_FAILED, 76),
        (IssueCreateProcessResult(None, timed_out=True), IssueCreateReasonCode.COMMAND_TIMEOUT, 77),
        (IssueCreateProcessResult(None, interrupted=True), IssueCreateReasonCode.COMMAND_INTERRUPTED, 77),
        (IssueCreateProcessResult(0, "created\n", ""), IssueCreateReasonCode.MALFORMED_SUCCESS_OUTPUT, 78),
        (IssueCreateProcessResult(0, "https://github.com/Blummer92/agent-os/issues/1\nhttps://github.com/Blummer92/agent-os/issues/1\n", ""), IssueCreateReasonCode.MALFORMED_SUCCESS_OUTPUT, 78),
        (IssueCreateProcessResult(0, "https://github.com/Blummer92/agent-os/issues/1?x=1\n", ""), IssueCreateReasonCode.MALFORMED_SUCCESS_OUTPUT, 78),
        (IssueCreateProcessResult(0, "http://github.com/Blummer92/agent-os/issues/1\n", ""), IssueCreateReasonCode.MALFORMED_SUCCESS_OUTPUT, 78),
        (IssueCreateProcessResult(0, "https://github.com/other/repo/issues/1\n", ""), IssueCreateReasonCode.WRONG_TARGET_SUCCESS_OUTPUT, 79),
    ),
)
def test_uncertain_mutation_matrix(process, reason, exit_code):
    result = execute_issue_creation(
        make_request(), FakeRunner(create=process), Confirmation()
    )
    assert result.reason_code == reason and result.exit_code == exit_code
    assert IssueCreateReasonCode.MUTATION_UNCERTAIN in result.reason_codes
    assert result.mutation_state == MutationState.UNCERTAIN
    assert not result.mutation_performed and not result.retry_allowed


@pytest.mark.parametrize(
    "overrides, reason",
    (
        ({("gh", "--version"): IssueCreateProcessResult(1, "", "missing")}, IssueCreateReasonCode.GH_UNAVAILABLE),
        ({("gh", "issue", "create", "--help"): IssueCreateProcessResult(0, "--repository --title --body-file --label\n", "")}, IssueCreateReasonCode.GH_CAPABILITY_UNSUPPORTED),
        ({("gh", "auth", "status", "--active", "--hostname", "github.com"): IssueCreateProcessResult(4, "", "no auth")}, IssueCreateReasonCode.AUTHENTICATION_UNAVAILABLE),
        ({("gh", "auth", "status", "--active", "--hostname", "github.com"): IssueCreateProcessResult(0, "Logged in to github.com account one\nLogged in to github.com account two\n", "")}, IssueCreateReasonCode.ACCOUNT_AMBIGUOUS_OR_MISMATCHED),
    ),
)
def test_capability_and_authentication(overrides, reason):
    plan, failure = plan_issue_creation(
        make_request(), FakeRunner(overrides=overrides)
    )
    assert plan is None and failure.reason_code == reason


@pytest.mark.parametrize(
    "payload",
    (
        {"nameWithOwner": "other/repo", "url": "https://github.com/other/repo", "hasIssuesEnabled": True, "isArchived": False},
        {"nameWithOwner": "Blummer92/agent-os", "url": "https://github.com/Blummer92/agent-os", "hasIssuesEnabled": True, "isArchived": True},
        {"nameWithOwner": "Blummer92/agent-os", "url": "https://github.com/Blummer92/agent-os", "hasIssuesEnabled": False, "isArchived": False},
    ),
)
def test_repository_target_metadata(payload):
    command = (
        "gh", "repo", "view", "github.com/Blummer92/agent-os", "--json",
        "nameWithOwner,url,hasIssuesEnabled,isArchived",
    )
    plan, failure = plan_issue_creation(
        make_request(),
        FakeRunner(overrides={
            command: IssueCreateProcessResult(0, json.dumps(payload), "")
        }),
    )
    assert plan is None
    assert failure.reason_code == IssueCreateReasonCode.TARGET_MISMATCHED


def test_redaction_unicode_cli_and_static_safety(monkeypatch, capsys, tmp_path):
    secret = "github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"
    base = make_validation()
    protected = replace(
        base,
        draft=replace(
            base.draft,
            title="private title",
            body="private body",
            proposed_labels=("private-label",),
        ),
    )
    diagnostic = (
        f"Authorization: Basic abc\nBearer abc.def\ntoken={secret}\n"
        "password=hunter2\nhttps://u:p@example.com/\n"
        "private title\nprivate-label\nprivate body"
    )
    result = execute_issue_creation(
        make_request(validation=protected),
        FakeRunner(create=IssueCreateProcessResult(1, secret, diagnostic)),
        Confirmation(),
    )
    combined = render_issue_create_result(result) + json.dumps(
        issue_create_result_to_dict(result)
    )
    for value in (
        secret, "abc.def", "hunter2", "u:p@", "private title",
        "private-label", "private body",
    ):
        assert value not in combined
    assert "TRUNCATED" in sanitize_diagnostic_text(
        "public\n" + "x" * 5000, limit=100
    )
    unicode_validation = replace(
        base, draft=replace(base.draft, body=base.draft.body + "\nRésumé — 東京")
    )
    plan, error = plan_issue_creation(
        make_request(validation=unicode_validation), FakeRunner()
    )
    assert error is None and "東京" in plan.body
    malformed = tmp_path / "bad.json"
    malformed.write_text("{", encoding="utf-8")
    assert issue_create_cli.main(
        ["--input", str(malformed), "--target", "Blummer92/agent-os"]
    ) == 64
    capsys.readouterr()
    cli_runner = FakeRunner()
    monkeypatch.setattr(issue_create_cli, "SubprocessGhRunner", lambda: cli_runner)
    assert issue_create_cli.main([
        "--input", str(FIXTURE), "--target", "Blummer92/agent-os",
        "--issue-form", str(FORM), "--label-map", str(MAP), "--format", "json",
    ]) == IssueCreateExitCode.CONFIRMATION
    assert create_calls(cli_runner) == []
    source = inspect.getsource(SubprocessGhRunner.run)
    module = Path(inspect.getsourcefile(SubprocessGhRunner)).read_text(encoding="utf-8")
    assert "subprocess.Popen" in source and "shell=False" in source
    for forbidden in (
        "shell=True", "os.system", "gh auth token", "--show-token", "gh auth refresh",
    ):
        assert forbidden not in module
    assert 'env.pop("GH_REPO"' in module
    assert 'env.pop("GH_HOST"' in module


def _run_ci_self_diagnostic():
    stage = "baseline-validation"
    try:
        baseline = make_validation()
        assert baseline.status == Status.PASS, baseline
        assert baseline.submission_eligible is True, baseline
        stage = "baseline-planning"
        plan, failure = plan_issue_creation(make_request(), FakeRunner())
        assert failure is None and plan is not None, failure
        stage = "confirmed-execution"
        runner = FakeRunner()
        confirmed = execute_issue_creation(make_request(), runner, Confirmation())
        assert confirmed.reason_code == IssueCreateReasonCode.CREATE_CONFIRMED, confirmed
        assert len(create_calls(runner)) == 1
        stage = "warning-execution"
        warned = warning_validation()
        rejected = execute_issue_creation(
            make_request(validation=warned), FakeRunner(), Confirmation(warnings=())
        )
        assert rejected.reason_code == IssueCreateReasonCode.ELIGIBLE_WARNING_NOT_ACCEPTED
        accepted = execute_issue_creation(
            make_request(validation=warned), FakeRunner(), Confirmation()
        )
        assert accepted.reason_code == IssueCreateReasonCode.CREATE_CONFIRMED, accepted
        stage = "uncertain-output"
        uncertain = execute_issue_creation(
            make_request(),
            FakeRunner(create=IssueCreateProcessResult(0, "created\n", "")),
            Confirmation(),
        )
        assert uncertain.reason_code == IssueCreateReasonCode.MALFORMED_SUCCESS_OUTPUT
        assert uncertain.mutation_state == MutationState.UNCERTAIN
        stage = "redaction"
        secret = "github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"
        redacted = sanitize_diagnostic_text(
            f"Authorization: Bearer abc.def\ntoken={secret}\npassword=hunter2"
        )
        assert secret not in redacted and "abc.def" not in redacted
        assert "hunter2" not in redacted
        stage = "cli-invalid-input"
        with tempfile.TemporaryDirectory() as directory:
            malformed = Path(directory) / "bad.json"
            malformed.write_text("{", encoding="utf-8")
            assert issue_create_cli.main(
                ["--input", str(malformed), "--target", "Blummer92/agent-os"]
            ) == 64
        stage = "static-safety"
        module = Path(inspect.getsourcefile(SubprocessGhRunner)).read_text(
            encoding="utf-8"
        )
        assert "shell=True" not in module and "os.system" not in module
    except BaseException as exc:
        pytest.exit(
            f"ISSUE_CREATE_DIAGNOSTIC_FAIL stage={stage} "
            f"type={type(exc).__name__} detail={exc!r}",
            returncode=3,
        )
    pytest.exit("ISSUE_CREATE_DIAGNOSTIC_ALL_STAGES_PASS", returncode=0)


_run_ci_self_diagnostic()
