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
    MutationState,
    execute_issue_creation,
)
from scripts.agent_os_issue_labels.validation import validate_issue_draft

ROOT = Path(__file__).resolve().parents[2]
FORM = ROOT / ".github/ISSUE_TEMPLATE/agent-os-task.yml"
MAP = ROOT / ".github/labeler/agent-os-issue-label-map.yml"
FIXTURE = ROOT / "tests/fixtures/agent_os_issue_labels/draft_minimum_valid.json"
TARGET = GitHubRepositoryTarget.parse("Blummer92/agent-os")


class Runner:
    def __init__(self, process):
        self.process = process

    def resolve_executable(self):
        return "gh"

    def run(self, argv, *, input_text=None, timeout=30.0):
        key = tuple(argv)
        if key == ("gh", "--version"):
            return IssueCreateProcessResult(0, "gh version 2.80.0\n", "")
        if key == ("gh", "issue", "create", "--help"):
            return IssueCreateProcessResult(0, "--repo --title --body-file --label\n", "")
        if key == ("gh", "auth", "status", "--active", "--hostname", "github.com"):
            return IssueCreateProcessResult(0, "Logged in to github.com account tester\n", "")
        if key == (
            "gh", "repo", "view", "github.com/Blummer92/agent-os", "--json",
            "nameWithOwner,url,hasIssuesEnabled,isArchived",
        ):
            return IssueCreateProcessResult(
                0,
                json.dumps({
                    "nameWithOwner": "Blummer92/agent-os",
                    "url": "https://github.com/Blummer92/agent-os",
                    "hasIssuesEnabled": True,
                    "isArchived": False,
                }),
                "",
            )
        if "--body-file=-" in key:
            return self.process
        raise AssertionError(key)


class Confirm:
    def confirm(self, plan):
        return IssueCreateConfirmation(
            "inv-1",
            plan.operation_fingerprint,
            plan.target.canonical,
            True,
            plan.warning_reason_codes,
        )


def _request():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source = IssueDraftInput.from_mapping(payload)
    draft = build_issue_draft(source, FORM, MAP)
    validation = validate_issue_draft(draft, source, FORM)
    return IssueCreateRequest(validation, TARGET, "inv-1")


@pytest.mark.parametrize(
    ("process", "reason", "exit_code"),
    [
        (IssueCreateProcessResult(1, "", "network failed"), IssueCreateReasonCode.COMMAND_FAILED, 76),
        (IssueCreateProcessResult(None, timed_out=True), IssueCreateReasonCode.COMMAND_TIMEOUT, 77),
        (IssueCreateProcessResult(None, interrupted=True), IssueCreateReasonCode.COMMAND_INTERRUPTED, 77),
        (IssueCreateProcessResult(0, "created\n", ""), IssueCreateReasonCode.MALFORMED_SUCCESS_OUTPUT, 78),
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
            IssueCreateProcessResult(0, "https://github.com/Blummer92/agent-os/issues/1?x=1\n", ""),
            IssueCreateReasonCode.MALFORMED_SUCCESS_OUTPUT,
            78,
        ),
        (
            IssueCreateProcessResult(0, "http://github.com/Blummer92/agent-os/issues/1\n", ""),
            IssueCreateReasonCode.MALFORMED_SUCCESS_OUTPUT,
            78,
        ),
        (
            IssueCreateProcessResult(0, "https://github.com/other/repo/issues/1\n", ""),
            IssueCreateReasonCode.WRONG_TARGET_SUCCESS_OUTPUT,
            79,
        ),
    ],
)
def test_uncertain_result_matrix(process, reason, exit_code):
    result = execute_issue_creation(_request(), Runner(process), Confirm())
    assert result.reason_code == reason
    assert IssueCreateReasonCode.MUTATION_UNCERTAIN in result.reason_codes
    assert result.exit_code == exit_code
    assert result.mutation_state == MutationState.UNCERTAIN
    assert result.mutation_performed is False
    assert result.retry_allowed is False
