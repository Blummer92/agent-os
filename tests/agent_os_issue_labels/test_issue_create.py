from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.agent_os_issue_labels.draft import IssueDraftInput, build_issue_draft
from scripts.agent_os_issue_labels.issue_create import (
    GitHubRepositoryTarget,
    IssueCreateConfirmation,
    IssueCreateExitCode,
    IssueCreateProcessResult,
    IssueCreateReasonCode,
    IssueCreateRequest,
    execute_issue_creation,
)
from scripts.agent_os_issue_labels.validation import validate_issue_draft

ROOT = Path(__file__).resolve().parents[2]
FORM = ROOT / ".github/ISSUE_TEMPLATE/agent-os-task.yml"
MAP = ROOT / ".github/labeler/agent-os-issue-label-map.yml"
FIXTURE = ROOT / "tests/fixtures/agent_os_issue_labels/draft_minimum_valid.json"
TARGET = GitHubRepositoryTarget.parse("Blummer92/agent-os")


class FakeRunner:
    def __init__(self):
        self.calls = []

    def resolve_executable(self):
        return "gh"

    def run(self, argv, *, input_text=None, timeout=30.0):
        key = tuple(argv)
        self.calls.append((key, input_text, timeout))
        if key == ("gh", "--version"):
            return IssueCreateProcessResult(0, "gh version 2.80.0\n", "")
        if key == ("gh", "issue", "create", "--help"):
            return IssueCreateProcessResult(0, "--repo --title --body-file --label\n", "")
        if key == (
            "gh", "auth", "status", "--active", "--hostname", "github.com"
        ):
            return IssueCreateProcessResult(
                0, "Logged in to github.com account tester\n", ""
            )
        if key == (
            "gh", "repo", "view", "github.com/Blummer92/agent-os", "--json",
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
            return IssueCreateProcessResult(
                0, "https://github.com/Blummer92/agent-os/issues/700\n", ""
            )
        raise AssertionError(key)


class Missing:
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
    ):
        self.invocation_id = invocation_id
        self.confirmed = confirmed
        self.fingerprint = fingerprint
        self.target = target

    def confirm(self, plan):
        return IssueCreateConfirmation(
            invocation_id=self.invocation_id,
            operation_fingerprint=self.fingerprint or plan.operation_fingerprint,
            target=self.target or plan.target.canonical,
            confirmed=self.confirmed,
            accepted_warning_reason_codes=plan.warning_reason_codes,
        )


def _request():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source = IssueDraftInput.from_mapping(payload)
    draft = build_issue_draft(source, FORM, MAP)
    validation = validate_issue_draft(draft, source, FORM)
    return IssueCreateRequest(validation, TARGET, "inv-1")


def _creates(runner):
    return [call for call in runner.calls if "--body-file=-" in call[0]]


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
    assert result.execution_attempted is False
    assert _creates(runner) == []
