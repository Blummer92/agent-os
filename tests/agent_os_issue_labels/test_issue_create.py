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


class Runner:
    def __init__(self, *, executable="gh"):
        self.executable = executable
        self.calls = []

    def resolve_executable(self):
        return self.executable

    def run(self, argv, *, input_text=None, timeout=30.0):
        key = tuple(argv)
        self.calls.append(key)
        defaults = {
            (self.executable, "--version"): IssueCreateProcessResult(0, "gh version 2.80.0\n", ""),
            (self.executable, "issue", "create", "--help"): IssueCreateProcessResult(0, "--repo --title --body-file --label\n", ""),
            (self.executable, "auth", "status", "--active", "--hostname", "github.com"): IssueCreateProcessResult(0, "Logged in to github.com account tester\n", ""),
            (self.executable, "repo", "view", "github.com/Blummer92/agent-os", "--json", "nameWithOwner,url,hasIssuesEnabled,isArchived"): IssueCreateProcessResult(0, json.dumps({"nameWithOwner": "Blummer92/agent-os", "url": "https://github.com/Blummer92/agent-os", "hasIssuesEnabled": True, "isArchived": False}), ""),
        }
        if key in defaults:
            return defaults[key]
        raise AssertionError(key)


def validation():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source = IssueDraftInput.from_mapping(payload)
    draft = build_issue_draft(source, FORM, MAP)
    return validate_issue_draft(draft, source, FORM)


def request(*, result=None, invocation="inv-1", optional=()):
    return IssueCreateRequest(
        result or validation(), TARGET, invocation, optional_metadata=optional
    )


@pytest.mark.parametrize("value", (
    "widgets", " github.com/acme/widgets", "github_com/acme/widgets",
    "github.com/./widgets", "github.com/../widgets",
    "github.com/acme/widgets/extra", "github.com/acme/", "例.example/acme/widgets",
))
def test_target_rejects_ambiguous_values(value):
    with pytest.raises(ValueError):
        GitHubRepositoryTarget.parse(value)


def test_safe_argv_and_identity_binding():
    target = GitHubRepositoryTarget.parse("ghe.example.com/acme/widgets")
    assert build_issue_create_argv(target, "-title", ("z", "-label", "z"), executable="/opt/gh") == (
        "/opt/gh", "issue", "create", "--repo=ghe.example.com/acme/widgets",
        "--title=-title", "--body-file=-", "--label=-label", "--label=z",
    )
    with pytest.raises(ValueError):
        build_issue_create_argv(target, "bad\ntitle", ())
    first, first_error = plan_issue_creation(request(invocation="one"), Runner())
    second, second_error = plan_issue_creation(request(invocation="two"), Runner())
    assert first_error is second_error is None
    assert first.operation_identity == second.operation_identity
    assert first.operation_fingerprint != second.operation_fingerprint
    changed_result = validation()
    changed_result = replace(changed_result, draft=replace(changed_result.draft, title="changed"))
    changed, error = plan_issue_creation(request(result=changed_result), Runner())
    assert error is None and changed.operation_identity != first.operation_identity
    executable, error = plan_issue_creation(request(), Runner(executable="/opt/gh"))
    assert error is None
    assert executable.operation_identity == first.operation_identity
    assert executable.operation_fingerprint != first.operation_fingerprint


@pytest.mark.parametrize("result", (
    lambda: replace(validation(), submission_eligible=False),
    lambda: replace(validation(), status=Status.MANUAL_REVIEW),
    lambda: replace(validation(), status=Status.FAIL),
    lambda: replace(validation(), write_authorized=True),
    lambda: replace(validation(), mutation_performed=True),
))
def test_ineligible_and_drifted_results_never_probe(result):
    runner = Runner()
    plan, failure = plan_issue_creation(request(result=result()), runner)
    assert plan is None
    assert failure.reason_code == IssueCreateReasonCode.VALIDATION_INELIGIBLE
    assert runner.calls == []


@pytest.mark.parametrize("metadata", (
    "assignee", "milestone", "type", "parent", "project", "recover", "template", "web",
))
def test_optional_metadata_is_blocked(metadata):
    plan, failure = plan_issue_creation(request(optional=(metadata,)), Runner())
    assert plan is None
    assert failure.reason_code == IssueCreateReasonCode.OPTIONAL_METADATA_UNSUPPORTED
