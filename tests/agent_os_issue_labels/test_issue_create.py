from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.agent_os_issue_labels.draft import IssueDraftInput, build_issue_draft
from scripts.agent_os_issue_labels.issue_create import (
    GitHubRepositoryTarget,
    IssueCreateConfirmation,
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


class Runner:
    def __init__(self):
        self.calls = []

    def resolve_executable(self):
        return "gh"

    def run(self, argv, *, input_text=None, timeout=30.0):
        key = tuple(argv)
        self.calls.append(key)
        defaults = {
            ("gh", "--version"): IssueCreateProcessResult(0, "gh version 2.80.0\n", ""),
            ("gh", "issue", "create", "--help"): IssueCreateProcessResult(0, "--repo --title --body-file --label\n", ""),
            ("gh", "auth", "status", "--active", "--hostname", "github.com"): IssueCreateProcessResult(0, "Logged in to github.com account tester\n", ""),
            ("gh", "repo", "view", "github.com/Blummer92/agent-os", "--json", "nameWithOwner,url,hasIssuesEnabled,isArchived"): IssueCreateProcessResult(0, json.dumps({"nameWithOwner": "Blummer92/agent-os", "url": "https://github.com/Blummer92/agent-os", "hasIssuesEnabled": True, "isArchived": False}), ""),
        }
        if key in defaults:
            return defaults[key]
        raise AssertionError(key)


class Confirmation:
    def __init__(self, *, invocation="inv-1", confirmed=True, fingerprint=None, target=None):
        self.invocation = invocation
        self.confirmed = confirmed
        self.fingerprint = fingerprint
        self.target = target

    def confirm(self, plan):
        return IssueCreateConfirmation(
            self.invocation,
            self.fingerprint or plan.operation_fingerprint,
            self.target or plan.target.canonical,
            self.confirmed,
            (),
        )


class Missing:
    def confirm(self, plan):
        return None


def request():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source = IssueDraftInput.from_mapping(payload)
    draft = build_issue_draft(source, FORM, MAP)
    validation = validate_issue_draft(draft, source, FORM)
    return IssueCreateRequest(validation, TARGET, "inv-1")


@pytest.mark.parametrize("provider, reason", (
    (Missing(), IssueCreateReasonCode.CONFIRMATION_MISSING),
    (Confirmation(confirmed=False), IssueCreateReasonCode.CONFIRMATION_CANCELLED),
    (Confirmation(fingerprint="stale"), IssueCreateReasonCode.CONFIRMATION_STALE_OR_MISMATCHED),
    (Confirmation(invocation="other"), IssueCreateReasonCode.CONFIRMATION_STALE_OR_MISMATCHED),
    (Confirmation(target="github.com/other/repo"), IssueCreateReasonCode.CONFIRMATION_STALE_OR_MISMATCHED),
))
def test_confirmation_failures_never_execute(provider, reason):
    runner = Runner()
    result = execute_issue_creation(request(), runner, provider)
    assert result.reason_code == reason, result
    assert not any("--body-file=-" in call for call in runner.calls)
