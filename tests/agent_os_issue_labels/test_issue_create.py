from __future__ import annotations

import inspect
import json
from dataclasses import replace
from pathlib import Path

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


class Runner:
    def __init__(self, create=None):
        self.create = create or IssueCreateProcessResult(
            0, "https://github.com/Blummer92/agent-os/issues/700\n", ""
        )
        self.calls = []

    def resolve_executable(self):
        return "gh"

    def run(self, argv, *, input_text=None, timeout=30.0):
        key = tuple(argv)
        self.calls.append((key, input_text, timeout))
        defaults = {
            ("gh", "--version"): IssueCreateProcessResult(0, "gh version 2.80.0\n", ""),
            ("gh", "issue", "create", "--help"): IssueCreateProcessResult(0, "--repo --title --body-file --label\n", ""),
            ("gh", "auth", "status", "--active", "--hostname", "github.com"): IssueCreateProcessResult(0, "Logged in to github.com account tester\n", ""),
            ("gh", "repo", "view", "github.com/Blummer92/agent-os", "--json", "nameWithOwner,url,hasIssuesEnabled,isArchived"): IssueCreateProcessResult(0, json.dumps({"nameWithOwner": "Blummer92/agent-os", "url": "https://github.com/Blummer92/agent-os", "hasIssuesEnabled": True, "isArchived": False}), ""),
        }
        if key in defaults:
            return defaults[key]
        if "--body-file=-" in key:
            return self.create
        raise AssertionError(key)


class Confirm:
    def confirm(self, plan):
        return IssueCreateConfirmation(
            "inv-1", plan.operation_fingerprint, plan.target.canonical, True,
            plan.warning_reason_codes,
        )


def validation():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source = IssueDraftInput.from_mapping(payload)
    draft = build_issue_draft(source, FORM, MAP)
    return validate_issue_draft(draft, source, FORM)


def request(result=None, invocation="inv-1", prior=()):
    return IssueCreateRequest(result or validation(), TARGET, invocation, prior_fingerprints=prior)


def creates(runner):
    return [call for call in runner.calls if "--body-file=-" in call[0]]


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
    redacted = execute_issue_creation(
        request(protected),
        Runner(IssueCreateProcessResult(1, secret, diagnostic)),
        Confirm(),
    )
    combined = render_issue_create_result(redacted) + json.dumps(
        issue_create_result_to_dict(redacted)
    )
    for value in (
        secret, "abc.def", "hunter2", "u:p@", "private title",
        "private-label", "private body",
    ):
        assert value not in combined
    assert "TRUNCATED" in sanitize_diagnostic_text(
        "public\n" + "x" * 5000, limit=100
    )

    unicode_result = replace(
        base, draft=replace(base.draft, body=base.draft.body + "\nRésumé — 東京")
    )
    unicode_plan, error = plan_issue_creation(request(unicode_result), Runner())
    assert error is None and "東京" in unicode_plan.body
    bad = replace(base, draft=replace(base.draft, body=base.draft.body + "\x00"))
    bad_plan, bad_result = plan_issue_creation(request(bad), Runner())
    assert bad_plan is None
    assert bad_result.reason_code == IssueCreateReasonCode.VALIDATION_INELIGIBLE

    malformed = tmp_path / "bad.json"
    malformed.write_text("{", encoding="utf-8")
    assert issue_create_cli.main(
        ["--input", str(malformed), "--target", "Blummer92/agent-os"]
    ) == 64
    capsys.readouterr()
    cli_runner = Runner()
    monkeypatch.setattr(issue_create_cli, "SubprocessGhRunner", lambda: cli_runner)
    code = issue_create_cli.main([
        "--input", str(FIXTURE), "--target", "Blummer92/agent-os",
        "--issue-form", str(FORM), "--label-map", str(MAP), "--format", "json",
    ])
    assert code == IssueCreateExitCode.CONFIRMATION
    assert creates(cli_runner) == []

    source = inspect.getsource(SubprocessGhRunner.run)
    module = Path(inspect.getsourcefile(SubprocessGhRunner)).read_text(encoding="utf-8")
    assert "subprocess.Popen" in source and "shell=False" in source
    for forbidden in (
        "shell=True", "os.system", "gh auth token", "--show-token", "gh auth refresh",
    ):
        assert forbidden not in module
    assert 'env.pop("GH_REPO"' in module
    assert 'env.pop("GH_HOST"' in module
