from __future__ import annotations

import json
from pathlib import Path

from scripts.agent_os_issue_labels.draft import IssueDraftInput, build_issue_draft
from scripts.agent_os_issue_labels.issue_create import (
    GitHubRepositoryTarget,
    IssueCreateConfirmation,
    IssueCreateProcessResult,
    IssueCreateReasonCode,
    IssueCreateRequest,
    MutationState,
    execute_issue_creation,
    plan_issue_creation,
)
from scripts.agent_os_issue_labels.validation import validate_issue_draft

ROOT = Path(__file__).resolve().parents[2]
FORM = ROOT / ".github/ISSUE_TEMPLATE/agent-os-task.yml"
MAP = ROOT / ".github/labeler/agent-os-issue-label-map.yml"
FIXTURE = ROOT / "tests/fixtures/agent_os_issue_labels/draft_minimum_valid.json"
TARGET = GitHubRepositoryTarget.parse("Blummer92/agent-os")


class FakeRunner:
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
            "gh", "repo", "view", "github.com/Blummer92/agent-os",
            "--json", "nameWithOwner,url,hasIssuesEnabled,isArchived",
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


def _request(invocation_id="inv-1"):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source = IssueDraftInput.from_mapping(payload)
    draft = build_issue_draft(source, FORM, MAP)
    validation = validate_issue_draft(draft, source, FORM)
    return IssueCreateRequest(validation, TARGET, invocation_id)


def test_minimum_plan_is_stable_and_fresh():
    first, first_failure = plan_issue_creation(_request("one"), FakeRunner())
    second, second_failure = plan_issue_creation(_request("two"), FakeRunner())
    assert first_failure is None and second_failure is None
    assert first.operation_identity == second.operation_identity
    assert first.operation_fingerprint != second.operation_fingerprint


def test_minimum_confirmed_create_contract():
    runner = FakeRunner()
    result = execute_issue_creation(_request(), runner, Confirm())
    assert result.reason_code == IssueCreateReasonCode.CREATE_CONFIRMED
    assert result.mutation_state == MutationState.CONFIRMED
    assert result.mutation_performed is True
    assert len([call for call in runner.calls if "--body-file=-" in call[0]]) == 1


def test_minimum_uncertain_contract():
    runner = FakeRunner(IssueCreateProcessResult(1, "", "network failed"))
    result = execute_issue_creation(_request(), runner, Confirm())
    assert result.reason_code == IssueCreateReasonCode.COMMAND_FAILED
    assert IssueCreateReasonCode.MUTATION_UNCERTAIN in result.reason_codes
    assert result.mutation_state == MutationState.UNCERTAIN
    assert result.retry_allowed is False
