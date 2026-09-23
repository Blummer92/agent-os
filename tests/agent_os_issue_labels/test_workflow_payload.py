import json
from pathlib import Path

import pytest

from scripts.agent_os_issue_acceptance.models import Status
from scripts.agent_os_issue_labels.workflow_payload import (
    main,
    render_payload_resolution,
    resolve_workflow_payload,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/agent_os_issue_labels/workflow_events"


def _fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_valid_issue_event_resolves_issue_number():
    result = resolve_workflow_payload(
        event_name="issues",
        payload=_fixture("issues_opened.json"),
    )
    assert result.status == Status.PASS
    assert result.issue_number == 275
    assert result.event_action == "opened"
    assert result.manual_review_reasons == ()


@pytest.mark.parametrize("action", ["opened", "edited", "reopened"])
def test_supported_issue_actions_resolve(action):
    result = resolve_workflow_payload(
        event_name="issues",
        payload={"action": action, "issue": {"number": 275}},
    )
    assert result.status == Status.PASS
    assert result.event_action == action


def test_missing_issue_number_routes_to_manual_review():
    result = resolve_workflow_payload(
        event_name="issues",
        payload=_fixture("issues_missing_number.json"),
    )
    assert result.status == Status.MANUAL_REVIEW
    assert result.issue_number is None
    assert "valid issue number" in result.manual_review_reasons[0]


def test_labeled_action_routes_to_manual_review():
    result = resolve_workflow_payload(
        event_name="issues",
        payload=_fixture("issues_unsupported_action.json"),
    )
    assert result.status == Status.MANUAL_REVIEW
    assert result.event_action == "labeled"
    assert "unsupported issue action" in result.manual_review_reasons[0]


@pytest.mark.parametrize("value", [None, "", "abc", "0", "-1", 0, -1, True])
def test_manual_dispatch_without_positive_issue_number_never_passes(value):
    result = resolve_workflow_payload(
        event_name="workflow_dispatch",
        payload={},
        manual_issue_number=value,
    )
    assert result.status == Status.MANUAL_REVIEW
    assert result.issue_number is None


@pytest.mark.parametrize("value", ["275", " 275 ", 275])
def test_manual_dispatch_with_positive_issue_number_resolves(value):
    result = resolve_workflow_payload(
        event_name="workflow_dispatch",
        payload={},
        manual_issue_number=value,
    )
    assert result.status == Status.PASS
    assert result.issue_number == 275
    assert result.event_action == "manual"


def test_missing_or_unsupported_event_never_passes():
    for event_name in ("", "pull_request", "schedule"):
        result = resolve_workflow_payload(event_name=event_name, payload={})
        assert result.status == Status.MANUAL_REVIEW
        assert result.issue_number is None


def test_payload_summary_always_denies_mutation_and_write_authorization():
    result = resolve_workflow_payload(
        event_name="issues",
        payload=_fixture("issues_missing_number.json"),
    )
    rendered = render_payload_resolution(
        result,
        event_name="issues",
        commit_sha="abc123",
    )
    assert "Outcome: manual-review" in rendered
    assert "Issue number: unresolved" in rendered
    assert "Mutation performed: no" in rendered
    assert "Write authorized: no" in rendered


def test_cli_malformed_json_writes_manual_review_outputs(tmp_path):
    github_output = tmp_path / "github-output.txt"
    summary = tmp_path / "summary.txt"
    exit_code = main(
        [
            "--event-name",
            "issues",
            "--event-path",
            str(FIXTURES / "malformed.json"),
            "--commit-sha",
            "abc123",
            "--github-output",
            str(github_output),
            "--summary-path",
            str(summary),
        ]
    )
    assert exit_code == 0
    output = github_output.read_text(encoding="utf-8")
    assert "status=manual-review" in output
    assert "issue-number=" in output
    rendered = summary.read_text(encoding="utf-8")
    assert "Outcome: manual-review" in rendered
    assert "JSONDecodeError" in rendered
    assert "Mutation performed: no" in rendered
    assert "Write authorized: no" in rendered


def test_repeated_payload_resolution_is_deterministic():
    payload = _fixture("issues_opened.json")
    assert resolve_workflow_payload(event_name="issues", payload=payload) == resolve_workflow_payload(
        event_name="issues",
        payload=payload,
    )
