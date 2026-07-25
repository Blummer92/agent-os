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
    build_issue_create_argv,
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
    def __init__(self, *, executable="gh", overrides=None):
        self.executable = executable
        self.overrides = overrides or {}
        self.calls = []

    def resolve_executable(self):
        return self.executable

    def run(self, argv, *, input_text=None, timeout=30.0):
        key = tuple(argv)
        self.calls.append((key, input_text, timeout))
        if key in self.overrides:
            return self.overrides[key]
        defaults = {
            (self.executable, "--version"): IssueCreateProcessResult(0, "gh version 2.80.0\n", ""),
            (self.executable, "issue", "create", "--help"): IssueCreateProcessResult(0, "--repo --title --body-file --label\n", ""),
            (self.executable, "auth", "status", "--active", "--hostname", "github.com"): IssueCreateProcessResult(0, "Logged in to github.com account tester\n", ""),
            (self.executable, "repo", "view", "github.com/Blummer92/agent-os", "--json", "nameWithOwner,url,hasIssuesEnabled,isArchived"): IssueCreateProcessResult(0, json.dumps({"nameWithOwner": "Blummer92/agent-os", "url": "https://github.com/Blummer92/agent-os", "hasIssuesEnabled": True, "isArchived": False}), ""),
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


def request(*, result=None, invocation="inv-1", prior=(), optional=()):
    return IssueCreateRequest(
        result or validation(), TARGET, invocation,
        prior_fingerprints=prior, optional_metadata=optional,
    )


def creates(runner):
    return [call for call in runner.calls if "--body-file=-" in call[0]]


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
    assert error is None and executable.operation_identity == first.operation_identity
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


@pytest.mark.parametrize("metadata", ("assignee", "milestone", "type", "parent", "project", "recover", "template", "web"))
def test_optional_metadata_is_blocked(metadata):
    plan, failure = plan_issue_creation(request(optional=(metadata,)), Runner())
    assert plan is None
    assert failure.reason_code == IssueCreateReasonCode.OPTIONAL_METADATA_UNSUPPORTED


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


def test_warning_and_repeat_boundaries():
    warned = replace(
        validation(), status=Status.WARN,
        reason_codes=(DraftReasonCode.ELIGIBLE_WARNING, DraftReasonCode.DUPLICATE_CANDIDATE_ADVISORY),
        submission_eligible=True,
    )
    rejected_runner = Runner()
    rejected = execute_issue_creation(request(result=warned), rejected_runner, Confirmation(warnings=()))
    assert rejected.reason_code == IssueCreateReasonCode.ELIGIBLE_WARNING_NOT_ACCEPTED
    accepted_runner = Runner()
    accepted = execute_issue_creation(request(result=warned), accepted_runner, Confirmation())
    assert accepted.reason_code == IssueCreateReasonCode.CREATE_CONFIRMED
    first, error = plan_issue_creation(request(invocation="first"), Runner())
    assert error is None
    plan, repeated = plan_issue_creation(request(invocation="second", prior=(first.operation_identity,)), Runner())
    assert plan is None and repeated.reason_code == IssueCreateReasonCode.REPEAT_INVOCATION_DETECTED


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
