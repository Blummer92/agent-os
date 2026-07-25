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
from scripts.agent_os_issue_labels.validation import DraftReasonCode, validate_issue_draft

ROOT = Path(__file__).resolve().parents[2]
FORM = ROOT / ".github/ISSUE_TEMPLATE/agent-os-task.yml"
MAP = ROOT / ".github/labeler/agent-os-issue-label-map.yml"
FIXTURE = ROOT / "tests/fixtures/agent_os_issue_labels/draft_minimum_valid.json"
TARGET = GitHubRepositoryTarget.parse("Blummer92/agent-os")


class Runner:
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
        self, *, invocation_id="inv-1", confirmed=True, fingerprint=None,
        target=None, warnings=None
    ):
        self.invocation_id = invocation_id
        self.confirmed = confirmed
        self.fingerprint = fingerprint
        self.target = target
        self.warnings = warnings

    def confirm(self, plan):
        return IssueCreateConfirmation(
            self.invocation_id,
            self.fingerprint or plan.operation_fingerprint,
            self.target or plan.target.canonical,
            self.confirmed,
            plan.warning_reason_codes if self.warnings is None else self.warnings,
        )


class MissingConfirmation:
    def confirm(self, plan):
        return None


def validation():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source = IssueDraftInput.from_mapping(payload)
    draft = build_issue_draft(source, FORM, MAP)
    return validate_issue_draft(draft, source, FORM)


def request(*, result=None, invocation="inv-1", prior=(), optional=()):
    return IssueCreateRequest(
        result or validation(), TARGET, invocation,
        prior_fingerprints=prior, optional_metadata=optional,
    )


def warning_validation():
    return replace(
        validation(), status=Status.WARN,
        reason_codes=(
            DraftReasonCode.ELIGIBLE_WARNING,
            DraftReasonCode.DUPLICATE_CANDIDATE_ADVISORY,
        ),
        submission_eligible=True,
    )


def creates(runner):
    return [call for call in runner.calls if "--body-file=-" in call[0]]


def repo_command(executable="gh"):
    return (
        executable, "repo", "view", "github.com/Blummer92/agent-os", "--json",
        "nameWithOwner,url,hasIssuesEnabled,isArchived",
    )


@pytest.mark.parametrize(
    "value",
    (
        "widgets", " github.com/acme/widgets", "github_com/acme/widgets",
        "github.com/./widgets", "github.com/../widgets",
        "github.com/acme/widgets/extra", "github.com/acme/", "例.example/acme/widgets",
    ),
)
def test_target_rejects_ambiguous_values(value):
    with pytest.raises(ValueError):
        GitHubRepositoryTarget.parse(value)


def test_safe_argv_and_controls():
    target = GitHubRepositoryTarget.parse("ghe.example.com/acme/widgets")
    assert build_issue_create_argv(
        target, "-title", ("z", "-label", "z"), executable="/usr/local/bin/gh"
    ) == (
        "/usr/local/bin/gh", "issue", "create",
        "--repo=ghe.example.com/acme/widgets", "--title=-title", "--body-file=-",
        "--label=-label", "--label=z",
    )
    with pytest.raises(ValueError):
        build_issue_create_argv(target, "bad\ntitle", ())
    with pytest.raises(ValueError):
        build_issue_create_argv(target, "title", ("bad\rlabel",))


def test_identity_and_fresh_confirmation():
    first, first_error = plan_issue_creation(request(invocation="one"), Runner())
    second, second_error = plan_issue_creation(request(invocation="two"), Runner())
    assert first_error is second_error is None
    assert first.operation_identity == second.operation_identity
    assert first.operation_fingerprint != second.operation_fingerprint
    changed = replace(validation(), draft=replace(validation().draft, title="changed"))
    altered, error = plan_issue_creation(request(result=changed), Runner())
    assert error is None and altered.operation_identity != first.operation_identity
    executable, error = plan_issue_creation(request(), Runner(executable="/opt/gh/bin/gh"))
    assert error is None and executable.operation_identity == first.operation_identity
    assert executable.operation_fingerprint != first.operation_fingerprint
    assert executable.argv[0] == "/opt/gh/bin/gh"


@pytest.mark.parametrize(
    "result",
    (
        lambda: replace(validation(), submission_eligible=False),
        lambda: replace(validation(), status=Status.MANUAL_REVIEW),
        lambda: replace(validation(), status=Status.FAIL),
        lambda: replace(validation(), write_authorized=True),
        lambda: replace(validation(), mutation_performed=True),
    ),
)
def test_ineligible_or_drifted_results_never_probe(result):
    runner = Runner()
    plan, failure = plan_issue_creation(request(result=result()), runner)
    assert plan is None and failure.reason_code == IssueCreateReasonCode.VALIDATION_INELIGIBLE
    assert runner.calls == [] and not failure.write_authorized and not failure.mutation_performed


@pytest.mark.parametrize(
    "name",
    ("assignee", "milestone", "type", "parent", "blocked-by", "blocking",
     "project", "recover", "template", "web"),
)
def test_optional_metadata_is_blocked(name):
    plan, failure = plan_issue_creation(request(optional=(name,)), Runner())
    assert plan is None
    assert failure.reason_code == IssueCreateReasonCode.OPTIONAL_METADATA_UNSUPPORTED


@pytest.mark.parametrize(
    "provider, reason",
    (
        (MissingConfirmation(), IssueCreateReasonCode.CONFIRMATION_MISSING),
        (Confirmation(confirmed=False), IssueCreateReasonCode.CONFIRMATION_CANCELLED),
        (Confirmation(fingerprint="stale"), IssueCreateReasonCode.CONFIRMATION_STALE_OR_MISMATCHED),
        (Confirmation(invocation_id="other"), IssueCreateReasonCode.CONFIRMATION_STALE_OR_MISMATCHED),
        (Confirmation(target="github.com/other/repo"), IssueCreateReasonCode.CONFIRMATION_STALE_OR_MISMATCHED),
    ),
)
def test_confirmation_failures_never_create(provider, reason):
    runner = Runner()
    result = execute_issue_creation(request(), runner, provider)
    assert result.reason_code == reason and result.exit_code == 70
    assert not result.execution_attempted and creates(runner) == []


def test_warning_acknowledgement_is_exact():
    draft = request(result=warning_validation())
    rejected_runner = Runner()
    rejected = execute_issue_creation(draft, rejected_runner, Confirmation(warnings=()))
    assert rejected.reason_code == IssueCreateReasonCode.ELIGIBLE_WARNING_NOT_ACCEPTED
    assert creates(rejected_runner) == []
    accepted_runner = Runner()
    accepted = execute_issue_creation(draft, accepted_runner, Confirmation())
    assert accepted.reason_code == IssueCreateReasonCode.CREATE_CONFIRMED
    assert len(creates(accepted_runner)) == 1


def test_confirmed_create_is_single_and_body_uses_stdin():
    runner, draft = Runner(), request()
    result = execute_issue_creation(draft, runner, Confirmation())
    calls = creates(runner)
    assert result.reason_code == IssueCreateReasonCode.CREATE_CONFIRMED
    assert result.reason_codes == (IssueCreateReasonCode.CREATE_CONFIRMED,)
    assert result.exit_code == 0 and result.write_authorized
    assert result.mutation_state == MutationState.CONFIRMED and result.mutation_performed
    assert result.created_issue_number == 700 and len(calls) == 1
    assert calls[0][1] == draft.validation.draft.body
    assert draft.validation.draft.body not in calls[0][0]


@pytest.mark.parametrize(
    "process, reason, code",
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
def test_uncertain_results(process, reason, code):
    result = execute_issue_creation(request(), Runner(create=process), Confirmation())
    assert result.reason_code == reason and result.exit_code == code
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
def test_capability_and_auth_fail_closed(overrides, reason):
    plan, failure = plan_issue_creation(request(), Runner(overrides=overrides))
    assert plan is None and failure.reason_code == reason


@pytest.mark.parametrize(
    "payload",
    (
        {"nameWithOwner": "other/repo", "url": "https://github.com/other/repo", "hasIssuesEnabled": True, "isArchived": False},
        {"nameWithOwner": "Blummer92/agent-os", "url": "https://github.com/Blummer92/agent-os", "hasIssuesEnabled": True, "isArchived": True},
        {"nameWithOwner": "Blummer92/agent-os", "url": "https://github.com/Blummer92/agent-os", "hasIssuesEnabled": False, "isArchived": False},
        {"nameWithOwner": "Blummer92/agent-os", "url": "https://github.com/Blummer92/agent-os?x=1", "hasIssuesEnabled": True, "isArchived": False},
    ),
)
def test_repository_metadata_fails_closed(payload):
    plan, failure = plan_issue_creation(
        request(), Runner(overrides={repo_command(): IssueCreateProcessResult(0, json.dumps(payload), "")})
    )
    assert plan is None and failure.reason_code == IssueCreateReasonCode.TARGET_MISMATCHED


def test_repeat_redaction_unicode_cli_and_static_boundaries(monkeypatch, capsys, tmp_path):
    first, error = plan_issue_creation(request(invocation="first"), Runner())
    assert error is None
    plan, repeated = plan_issue_creation(
        request(invocation="second", prior=(first.operation_identity,)), Runner()
    )
    assert plan is None and repeated.exit_code == 80 and not repeated.retry_allowed

    secret = "github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"
    base = validation()
    protected = replace(
        base, draft=replace(base.draft, title="private title", body="private body", proposed_labels=("private-label",))
    )
    diagnostic = f"Authorization: Basic abc\nBearer abc.def\ntoken={secret}\npassword=hunter2\nhttps://u:p@example.com/\nprivate title\nprivate-label\nprivate body"
    redacted = execute_issue_creation(
        request(result=protected), Runner(create=IssueCreateProcessResult(1, secret, diagnostic)), Confirmation()
    )
    combined = render_issue_create_result(redacted) + json.dumps(issue_create_result_to_dict(redacted))
    for value in (secret, "abc.def", "hunter2", "u:p@", "private title", "private-label", "private body"):
        assert value not in combined
    assert "TRUNCATED" in sanitize_diagnostic_text("public\n" + "x" * 5000, limit=100)

    unicode_result = replace(base, draft=replace(base.draft, body=base.draft.body + "\nRésumé — 東京"))
    unicode_plan, error = plan_issue_creation(request(result=unicode_result), Runner())
    assert error is None and "東京" in unicode_plan.body
    bad = replace(base, draft=replace(base.draft, body=base.draft.body + "\x00"))
    bad_plan, bad_result = plan_issue_creation(request(result=bad), Runner())
    assert bad_plan is None and bad_result.reason_code == IssueCreateReasonCode.VALIDATION_INELIGIBLE

    malformed = tmp_path / "bad.json"
    malformed.write_text("{", encoding="utf-8")
    assert issue_create_cli.main(["--input", str(malformed), "--target", "Blummer92/agent-os"]) == 64
    capsys.readouterr()
    cli_runner = Runner()
    monkeypatch.setattr(issue_create_cli, "SubprocessGhRunner", lambda: cli_runner)
    code = issue_create_cli.main([
        "--input", str(FIXTURE), "--target", "Blummer92/agent-os",
        "--issue-form", str(FORM), "--label-map", str(MAP), "--format", "json",
    ])
    assert code == IssueCreateExitCode.CONFIRMATION and creates(cli_runner) == []

    source = inspect.getsource(SubprocessGhRunner.run)
    module = Path(inspect.getsourcefile(SubprocessGhRunner)).read_text(encoding="utf-8")
    assert "subprocess.Popen" in source and "shell=False" in source
    for forbidden in ("shell=True", "os.system", "gh auth token", "--show-token", "gh auth refresh"):
        assert forbidden not in module
    assert 'env.pop("GH_REPO"' in module and 'env.pop("GH_HOST"' in module
