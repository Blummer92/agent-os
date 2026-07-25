from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from scripts.agent_os_issue_acceptance.models import Status
from scripts.agent_os_issue_labels.draft import IssueDraftInput, build_issue_draft
from scripts.agent_os_issue_labels.issue_create import (
    GitHubRepositoryTarget,
    IssueCreateConfirmation,
    IssueCreateProcessResult,
    IssueCreateReasonCode,
    IssueCreateRequest,
    execute_issue_creation,
)
from scripts.agent_os_issue_labels.validation import (
    DraftReasonCode,
    validate_issue_draft,
)

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
        raise AssertionError(key)


class RejectWarnings:
    def confirm(self, plan):
        return IssueCreateConfirmation(
            invocation_id="inv-1",
            operation_fingerprint=plan.operation_fingerprint,
            target=plan.target.canonical,
            confirmed=True,
            accepted_warning_reason_codes=(),
        )


def _request():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source = IssueDraftInput.from_mapping(payload)
    draft = build_issue_draft(source, FORM, MAP)
    validation = validate_issue_draft(draft, source, FORM)
    validation = replace(
        validation,
        status=Status.WARN,
        reason_codes=(
            DraftReasonCode.ELIGIBLE_WARNING,
            DraftReasonCode.DUPLICATE_CANDIDATE_ADVISORY,
        ),
        submission_eligible=True,
    )
    return IssueCreateRequest(validation, TARGET, "inv-1")


def test_warning_rejection_executes_nothing():
    runner = FakeRunner()
    result = execute_issue_creation(_request(), runner, RejectWarnings())
    assert result.reason_code == IssueCreateReasonCode.ELIGIBLE_WARNING_NOT_ACCEPTED
    assert [call for call in runner.calls if "--body-file=-" in call[0]] == []
