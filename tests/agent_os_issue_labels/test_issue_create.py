from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.agent_os_issue_acceptance.models import Status
from scripts.agent_os_issue_labels.draft import IssueDraftInput, build_issue_draft
from scripts.agent_os_issue_labels.issue_create import (
    GitHubRepositoryTarget,
    IssueCreateConfirmation,
    IssueCreateProcessResult,
    IssueCreateReasonCode,
    IssueCreateRequest,
    execute_issue_creation,
    plan_issue_creation,
)
from scripts.agent_os_issue_labels.validation import DraftReasonCode, validate_issue_draft

ROOT = Path(__file__).resolve().parents[2]
FORM = ROOT / ".github/ISSUE_TEMPLATE/agent-os-task.yml"
MAP = ROOT / ".github/labeler/agent-os-issue-label-map.yml"
FIXTURE = ROOT / "tests/fixtures/agent_os_issue_labels/draft_minimum_valid.json"
TARGET = GitHubRepositoryTarget.parse("Blummer92/agent-os")


class Runner:
    def __init__(self, overrides=None):
        self.overrides = overrides or {}
        self.calls = []

    def resolve_executable(self):
        return "gh"

    def run(self, argv, *, input_text=None, timeout=30.0):
        key = tuple(argv)
        self.calls.append((key, input_text, timeout))
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
        if "--body-file=-" in key:
            return IssueCreateProcessResult(0, "https://github.com/Blummer92/agent-os/issues/700\n", "")
        raise AssertionError(key)


class Confirmation:
    def __init__(self, *, invocation="inv-1", confirmed=True, fingerprint=None, target=None, warnings=None):
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


class Missing:
    def confirm(self, plan):
        return None


def validation():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source = IssueDraftInput.from_mapping(payload)
    draft = build_issue_draft(source, FORM, MAP)
    return validate_issue_draft(draft, source, FORM)


def request(result=None):
    return IssueCreateRequest(result or validation(), TARGET, "inv-1")


def creates(runner):
    return [call for call in runner.calls if "--body-file=-" in call[0]]


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
    assert result.reason_code == reason
    assert creates(runner) == []


def test_warning_acknowledgement_is_exact():
    warned = replace(
        validation(), status=Status.WARN,
        reason_codes=(DraftReasonCode.ELIGIBLE_WARNING, DraftReasonCode.DUPLICATE_CANDIDATE_ADVISORY),
        submission_eligible=True,
    )
    rejected_runner = Runner()
    rejected = execute_issue_creation(request(warned), rejected_runner, Confirmation(warnings=()))
    assert rejected.reason_code == IssueCreateReasonCode.ELIGIBLE_WARNING_NOT_ACCEPTED
    assert creates(rejected_runner) == []
    accepted_runner = Runner()
    accepted = execute_issue_creation(request(warned), accepted_runner, Confirmation())
    assert accepted.reason_code == IssueCreateReasonCode.CREATE_CONFIRMED
    assert len(creates(accepted_runner)) == 1


@pytest.mark.parametrize("overrides, reason", (
    ({("gh", "--version"): IssueCreateProcessResult(1, "", "missing")}, IssueCreateReasonCode.GH_UNAVAILABLE),
    ({("gh", "issue", "create", "--help"): IssueCreateProcessResult(0, "--repository --title --body-file --label\n", "")}, IssueCreateReasonCode.GH_CAPABILITY_UNSUPPORTED),
    ({("gh", "auth", "status", "--active", "--hostname", "github.com"): IssueCreateProcessResult(4, "", "no auth")}, IssueCreateReasonCode.AUTHENTICATION_UNAVAILABLE),
    ({("gh", "auth", "status", "--active", "--hostname", "github.com"): IssueCreateProcessResult(0, "Logged in to github.com account one\nLogged in to github.com account two\n", "")}, IssueCreateReasonCode.ACCOUNT_AMBIGUOUS_OR_MISMATCHED),
))
def test_capability_and_auth_fail_closed(overrides, reason):
    plan, failure = plan_issue_creation(request(), Runner(overrides=overrides))
    assert plan is None and failure.reason_code == reason


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
    assert plan is None and failure.reason_code == IssueCreateReasonCode.TARGET_MISMATCHED
