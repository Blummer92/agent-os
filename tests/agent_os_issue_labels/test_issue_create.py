from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.agent_os_issue_labels.draft import IssueDraftInput, build_issue_draft
from scripts.agent_os_issue_labels.issue_create import (
    GitHubRepositoryTarget,
    IssueCreateProcessResult,
    IssueCreateReasonCode,
    IssueCreateRequest,
    plan_issue_creation,
)
from scripts.agent_os_issue_labels.validation import validate_issue_draft

ROOT = Path(__file__).resolve().parents[2]
FORM = ROOT / ".github/ISSUE_TEMPLATE/agent-os-task.yml"
MAP = ROOT / ".github/labeler/agent-os-issue-label-map.yml"
FIXTURE = ROOT / "tests/fixtures/agent_os_issue_labels/draft_minimum_valid.json"
TARGET = GitHubRepositoryTarget.parse("Blummer92/agent-os")


class Runner:
    def __init__(self, overrides=None):
        self.overrides = overrides or {}

    def resolve_executable(self):
        return "gh"

    def run(self, argv, *, input_text=None, timeout=30.0):
        key = tuple(argv)
        if key in self.overrides:
            return self.overrides[key]
        defaults = {
            ("gh", "--version"): IssueCreateProcessResult(0, "gh version 2.80.0\n", ""),
            ("gh", "issue", "create", "--help"): IssueCreateProcessResult(0, "--repo --title --body-file --label\n", ""),
            ("gh", "auth", "status", "--active", "--hostname", "github.com"): IssueCreateProcessResult(0, "Logged in to github.com account tester\n", ""),
            ("gh", "repo", "view", "github.com/Blummer92/agent-os", "--json", "nameWithOwner,url,hasIssuesEnabled,isArchived"): IssueCreateProcessResult(0, json.dumps({"nameWithOwner": "Blummer92/agent-os", "url": "https://github.com/Blummer92/agent-os", "hasIssuesEnabled": True, "isArchived": False}), ""),
        }
        if key in defaults:
            return defaults[key]
        raise AssertionError(key)


def request():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source = IssueDraftInput.from_mapping(payload)
    draft = build_issue_draft(source, FORM, MAP)
    validation = validate_issue_draft(draft, source, FORM)
    return IssueCreateRequest(validation, TARGET, "inv-1")


@pytest.mark.parametrize("overrides, reason", (
    ({("gh", "--version"): IssueCreateProcessResult(1, "", "missing")}, IssueCreateReasonCode.GH_UNAVAILABLE),
    ({("gh", "issue", "create", "--help"): IssueCreateProcessResult(0, "--repository --title --body-file --label\n", "")}, IssueCreateReasonCode.GH_CAPABILITY_UNSUPPORTED),
    ({("gh", "auth", "status", "--active", "--hostname", "github.com"): IssueCreateProcessResult(4, "", "no auth")}, IssueCreateReasonCode.AUTHENTICATION_UNAVAILABLE),
    ({("gh", "auth", "status", "--active", "--hostname", "github.com"): IssueCreateProcessResult(0, "Logged in to github.com account one\nLogged in to github.com account two\n", "")}, IssueCreateReasonCode.ACCOUNT_AMBIGUOUS_OR_MISMATCHED),
))
def test_capability_and_auth_fail_closed(overrides, reason):
    plan, failure = plan_issue_creation(request(), Runner(overrides=overrides))
    assert plan is None
    assert failure.reason_code == reason, failure


@pytest.mark.parametrize("payload", (
    {"nameWithOwner": "other/repo", "url": "https://github.com/other/repo", "hasIssuesEnabled": True, "isArchived": False},
    {"nameWithOwner": "Blummer92/agent-os", "url": "https://github.com/Blummer92/agent-os", "hasIssuesEnabled": True, "isArchived": True},
    {"nameWithOwner": "Blummer92/agent-os", "url": "https://github.com/Blummer92/agent-os", "hasIssuesEnabled": False, "isArchived": False},
))
def test_repository_metadata_fails_closed(payload):
    command = ("gh", "repo", "view", "github.com/Blummer92/agent-os", "--json", "nameWithOwner,url,hasIssuesEnabled,isArchived")
    plan, failure = plan_issue_creation(
        request(), Runner(overrides={command: IssueCreateProcessResult(0, json.dumps(payload), "")})
    )
    assert plan is None
    assert failure.reason_code == IssueCreateReasonCode.TARGET_MISMATCHED, failure
