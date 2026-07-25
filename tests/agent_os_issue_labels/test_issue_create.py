from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.agent_os_issue_acceptance.models import Status
from scripts.agent_os_issue_labels.draft import IssueDraftInput, build_issue_draft
from scripts.agent_os_issue_labels.issue_create import (
    GitHubRepositoryTarget,
    IssueCreateProcessResult,
    IssueCreateReasonCode,
    IssueCreateRequest,
    build_issue_create_argv,
    plan_issue_creation,
)
from scripts.agent_os_issue_labels.validation import validate_issue_draft

ROOT = Path(__file__).resolve().parents[2]
FORM = ROOT / ".github/ISSUE_TEMPLATE/agent-os-task.yml"
MAP = ROOT / ".github/labeler/agent-os-issue-label-map.yml"
FIXTURE = ROOT / "tests/fixtures/agent_os_issue_labels/draft_minimum_valid.json"
TARGET = GitHubRepositoryTarget.parse("Blummer92/agent-os")


class FakeRunner:
    def __init__(self, *, executable="gh"):
        self.executable = executable
        self.calls = []

    def resolve_executable(self):
        return self.executable

    def run(self, argv, *, input_text=None, timeout=30.0):
        key = tuple(argv)
        self.calls.append((key, input_text, timeout))
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
        raise AssertionError(key)


def _validation():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source = IssueDraftInput.from_mapping(payload)
    draft = build_issue_draft(source, FORM, MAP)
    return validate_issue_draft(draft, source, FORM)


def _request(*, validation=None, invocation_id="inv-1", optional=()):
    return IssueCreateRequest(
        validation=validation or _validation(),
        target=TARGET,
        invocation_id=invocation_id,
        optional_metadata=optional,
    )


def test_target_and_argv_contract():
    target = GitHubRepositoryTarget.parse("ghe.example.com/acme/widgets")
    assert build_issue_create_argv(
        target,
        "-title",
        ("z", "-label", "z"),
        executable="/usr/local/bin/gh",
    )[-5:] == (
        "--repo=ghe.example.com/acme/widgets",
        "--title=-title",
        "--body-file=-",
        "--label=-label",
        "--label=z",
    )
    for value in (
        "widgets",
        " github.com/acme/widgets",
        "github_com/acme/widgets",
        "github.com/./widgets",
        "github.com/../widgets",
        "github.com/acme/widgets/extra",
        "github.com/acme/",
        "例.example/acme/widgets",
    ):
        with pytest.raises(ValueError):
            GitHubRepositoryTarget.parse(value)


def test_identity_freshness_and_operation_changes():
    first, first_failure = plan_issue_creation(
        _request(invocation_id="one"), FakeRunner()
    )
    second, second_failure = plan_issue_creation(
        _request(invocation_id="two"), FakeRunner()
    )
    assert first_failure is None and second_failure is None
    assert first.operation_identity == second.operation_identity
    assert first.operation_fingerprint != second.operation_fingerprint

    validation = _validation()
    for variant in (
        replace(validation, draft=replace(validation.draft, title="Changed title")),
        replace(validation, draft=replace(validation.draft, body="Changed body")),
        replace(
            validation,
            draft=replace(validation.draft, proposed_labels=("changed-label",)),
        ),
    ):
        changed, changed_failure = plan_issue_creation(
            _request(validation=variant), FakeRunner()
        )
        assert changed_failure is None
        assert changed.operation_identity != first.operation_identity


def test_account_and_executable_only_change_confirmation():
    baseline, failure = plan_issue_creation(_request(), FakeRunner())
    changed, changed_failure = plan_issue_creation(
        _request(), FakeRunner(executable="/opt/gh/bin/gh")
    )
    assert failure is None and changed_failure is None
    assert changed.operation_identity == baseline.operation_identity
    assert changed.operation_fingerprint != baseline.operation_fingerprint


@pytest.mark.parametrize(
    "validation",
    [
        lambda: replace(_validation(), submission_eligible=False),
        lambda: replace(_validation(), status=Status.MANUAL_REVIEW),
        lambda: replace(_validation(), status=Status.FAIL),
        lambda: replace(_validation(), write_authorized=True),
        lambda: replace(_validation(), mutation_performed=True),
    ],
)
def test_ineligible_states_execute_nothing(validation):
    runner = FakeRunner()
    plan, result = plan_issue_creation(_request(validation=validation()), runner)
    assert plan is None
    assert result.reason_code == IssueCreateReasonCode.VALIDATION_INELIGIBLE
    assert runner.calls == []


def test_all_optional_metadata_is_blocked():
    for name in (
        "assignee",
        "milestone",
        "type",
        "parent",
        "blocked-by",
        "blocking",
        "project",
        "recover",
        "template",
        "web",
    ):
        plan, result = plan_issue_creation(
            _request(optional=(name,)), FakeRunner()
        )
        assert plan is None
        assert result.reason_code == IssueCreateReasonCode.OPTIONAL_METADATA_UNSUPPORTED


def test_unicode_and_controls():
    validation = _validation()
    unicode_validation = replace(
        validation,
        draft=replace(
            validation.draft,
            body=validation.draft.body + "\nRésumé — 東京\n",
        ),
    )
    plan, failure = plan_issue_creation(
        _request(validation=unicode_validation), FakeRunner()
    )
    assert failure is None
    assert "東京" in plan.body

    bad = replace(
        validation,
        draft=replace(validation.draft, body=validation.draft.body + "\x00"),
    )
    plan, failure = plan_issue_creation(_request(validation=bad), FakeRunner())
    assert plan is None
    assert failure.reason_code == IssueCreateReasonCode.VALIDATION_INELIGIBLE
