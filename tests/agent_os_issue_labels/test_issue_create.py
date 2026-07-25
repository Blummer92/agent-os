from __future__ import annotations

import inspect
import json
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.agent_os_issue_labels import issue_create_cli
from scripts.agent_os_issue_labels.draft import IssueDraftInput, build_issue_draft
from scripts.agent_os_issue_labels.issue_create import (
    GitHubRepositoryTarget,
    IssueCreateConfirmation,
    IssueCreateExitCode,
    IssueCreateProcessResult,
    IssueCreateReasonCode,
    IssueCreateRequest,
    SubprocessGhRunner,
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
        raise AssertionError(key)


class Confirm:
    def confirm(self, plan):
        return IssueCreateConfirmation(
            invocation_id="inv-1",
            operation_fingerprint=plan.operation_fingerprint,
            target=plan.target.canonical,
            confirmed=True,
            accepted_warning_reason_codes=plan.warning_reason_codes,
        )


def _validation():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source = IssueDraftInput.from_mapping(payload)
    draft = build_issue_draft(source, FORM, MAP)
    return validate_issue_draft(draft, source, FORM)


def _request(*, validation=None, prior=()):
    return IssueCreateRequest(
        validation=validation or _validation(),
        target=TARGET,
        invocation_id="inv-1",
        prior_fingerprints=prior,
    )


def _creates(runner):
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
                    0, "--repository --title --body-file --label\n", ""
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
    plan, result = plan_issue_creation(_request(), FakeRunner(overrides=overrides))
    assert plan is None
    assert result.reason_code == reason


def test_missing_executable_and_nonstandard_version_behavior():
    missing = FakeRunner()
    missing.executable = None
    plan, result = plan_issue_creation(_request(), missing)
    assert plan is None
    assert result.reason_code == IssueCreateReasonCode.GH_UNAVAILABLE

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
def test_repository_metadata_fails_closed(payload):
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


def test_repeated_identity_blocks_and_does_not_retry():
    first, failure = plan_issue_creation(_request(), FakeRunner())
    assert failure is None
    runner = FakeRunner()
    plan, result = plan_issue_creation(
        _request(prior=(first.operation_identity,)), runner
    )
    assert plan is None
    assert result.reason_code == IssueCreateReasonCode.REPEAT_INVOCATION_DETECTED
    assert result.retry_allowed is False
    assert _creates(runner) == []


def test_redaction_and_submitted_content_are_not_exposed():
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
        "Authorization: Basic abc\nBearer abc.def\n"
        f"token={secret}\npassword='hunter2'\n"
        "https://u:p@example.com/\n"
        f"{title_secret}\n{label_secret}\n{body_secret}\n"
    )
    result = execute_issue_creation(
        _request(validation=validation),
        FakeRunner(create=IssueCreateProcessResult(1, secret, diagnostic)),
        Confirm(),
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


def test_redaction_and_truncation_helpers():
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


def test_cli_and_serializer_boundaries(monkeypatch, capsys, tmp_path):
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    assert issue_create_cli.main(
        ["--input", str(malformed), "--target", "Blummer92/agent-os"]
    ) == 64
    capsys.readouterr()

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
    assert _creates(runner) == []


def test_cli_confirmation_hides_raw_content(monkeypatch, capsys):
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
    issue_create_cli._PromptConfirmation().confirm(plan)
    captured = capsys.readouterr()
    assert "secret title" not in captured.err
    assert "secret-label" not in captured.err


def test_static_process_safety_contract():
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
