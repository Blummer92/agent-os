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
    MutationState,
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
        if "--body-file=-" in key:
            return IssueCreateProcessResult(
                0, "https://github.com/Blummer92/agent-os/issues/700\n", ""
            )
        raise AssertionError(key)


class Confirmation:
    def __init__(self, *, warnings=None):
        self.warnings = warnings

    def confirm(self, plan):
        return IssueCreateConfirmation(
            invocation_id="inv-1",
            operation_fingerprint=plan.operation_fingerprint,
            target=plan.target.canonical,
            confirmed=True,
            accepted_warning_reason_codes=(
                plan.warning_reason_codes if self.warnings is None else self.warnings
            ),
        )


def _validation():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source = IssueDraftInput.from_mapping(payload)
    draft = build_issue_draft(source, FORM, MAP)
    return validate_issue_draft(draft, source, FORM)


def _request(*, warning=False):
    validation = _validation()
    if warning:
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


def _creates(runner):
    return [call for call in runner.calls if "--body-file=-" in call[0]]


def test_warning_requires_exact_acknowledgement():
    request = _request(warning=True)
    rejected_runner = FakeRunner()
    rejected = execute_issue_creation(
        request,
        rejected_runner,
        Confirmation(warnings=()),
    )
    assert rejected.reason_code == IssueCreateReasonCode.ELIGIBLE_WARNING_NOT_ACCEPTED
    assert _creates(rejected_runner) == []

    accepted_runner = FakeRunner()
    accepted = execute_issue_creation(
        request,
        accepted_runner,
        Confirmation(),
    )
    assert accepted.reason_code == IssueCreateReasonCode.CREATE_CONFIRMED
    assert len(_creates(accepted_runner)) == 1


def test_confirmed_success_contract():
    runner = FakeRunner()
    result = execute_issue_creation(_request(), runner, Confirmation())
    assert result.reason_code == IssueCreateReasonCode.CREATE_CONFIRMED
    assert result.reason_codes == (IssueCreateReasonCode.CREATE_CONFIRMED,)
    assert result.exit_code == 0
    assert result.write_authorized is True
    assert result.mutation_state == MutationState.CONFIRMED
    assert result.mutation_performed is True
    assert result.created_issue_number == 700
    assert len(_creates(runner)) == 1
