from pathlib import Path

from scripts.agent_os_issue_acceptance.models import Status
from scripts.agent_os_issue_labels.planner import plan_label_application, render_application_plan

ROOT = Path(__file__).resolve().parents[2]
FORM = ROOT / ".github/ISSUE_TEMPLATE/agent-os-task.yml"
MAP = ROOT / ".github/labeler/agent-os-issue-label-map.yml"
FIXTURES = ROOT / "tests/fixtures/agent_os_issue_labels"
TIERED_READY = (FIXTURES / "tiered_ready.md").read_text(encoding="utf-8")
LEGACY_READY = (FIXTURES / "legacy_ready.md").read_text(encoding="utf-8")
AVAILABLE = [
    line.strip()
    for line in (FIXTURES / "available_labels.txt").read_text(encoding="utf-8").splitlines()
    if line.strip()
]


def plan(body=TIERED_READY, existing=None, available=None):
    return plan_label_application(
        issue_body=body,
        existing_labels=[] if existing is None else existing,
        available_labels=AVAILABLE if available is None else available,
        issue_form_path=FORM,
        label_map_path=MAP,
    )


def test_application_plan_is_deterministic_and_idempotent():
    first = plan(existing=["status:ready", "status:ready"])
    second = plan(existing=["status:ready"])
    assert first == second
    assert first.outcome == Status.PASS
    assert first.approved_additions == ("agent-os", "owner:qa-test-agent")


def test_existing_safe_labels_are_skipped_as_already_present():
    result = plan(existing=["agent-os", "owner:qa-test-agent", "status:ready"])
    assert result.approved_additions == ()
    assert "agent-os" in result.already_present
    assert "owner:qa-test-agent" in result.already_present


def test_status_labels_are_never_proposed():
    result = plan(existing=[])
    assert "status:ready" in result.skipped_by_policy
    assert all(not label.startswith("status:") for label in result.candidate_additions)
    assert all(not label.startswith("status:") for label in result.approved_additions)


def test_conflicting_owner_routes_to_manual_review_and_withholds_additions():
    result = plan(existing=["owner:github-service-agent"])
    assert result.outcome == Status.MANUAL_REVIEW
    assert result.approved_additions == ()
    assert result.conflicting_labels == (
        "owner:github-service-agent",
        "owner:qa-test-agent",
    )


def test_multiple_existing_owners_conflict_even_when_desired_owner_is_present():
    result = plan(existing=["owner:qa-test-agent", "owner:github-service-agent"])
    assert result.outcome == Status.MANUAL_REVIEW
    assert result.approved_additions == ()
    assert result.conflicting_labels == (
        "owner:github-service-agent",
        "owner:qa-test-agent",
    )


def test_unavailable_safe_label_routes_to_manual_review():
    result = plan(existing=[], available=["agent-os", "status:ready"])
    assert result.outcome == Status.MANUAL_REVIEW
    assert result.approved_additions == ()
    assert result.unavailable_labels == ("owner:qa-test-agent",)


def test_unknown_metadata_routes_to_manual_review():
    body = TIERED_READY.replace("owner:qa-test-agent", "owner:unknown-agent")
    result = plan(body=body)
    assert result.outcome == Status.MANUAL_REVIEW
    assert "owner=owner:unknown-agent" in result.unknown_values
    assert result.approved_additions == ()


def test_malformed_metadata_routes_to_manual_review():
    result = plan(body="### Primary owner\n\nowner:qa-test-agent\n")
    assert result.outcome == Status.MANUAL_REVIEW
    assert result.approved_additions == ()
    assert any("issue metadata" in reason for reason in result.manual_review_reasons)


def test_free_form_existing_label_is_preserved_but_never_proposed():
    result = plan(existing=["custom:keep-me", "status:ready"])
    assert "custom:keep-me" in result.existing_labels
    assert "custom:keep-me" not in result.candidate_additions
    assert "custom:keep-me" not in result.approved_additions


def test_legacy_issue_remains_compatible_but_legacy_labels_are_report_only():
    result = plan(body=LEGACY_READY, existing=["status:ready"])
    assert result.outcome == Status.PASS
    assert result.approved_additions == ("agent-os", "owner:qa-test-agent")
    assert "implementation-phase-1" in result.skipped_by_policy
    assert "epic:issue-acceptance" in result.skipped_by_policy
    assert "type:tooling" in result.skipped_by_policy


def test_rendered_plan_contains_auditable_fields():
    rendered = render_application_plan(
        plan(existing=["status:ready"]),
        issue_number=275,
        event_type="issues:edited",
        commit_sha="abc123",
    )
    assert "Issue number: #275" in rendered
    assert "Event type: issues:edited" in rendered
    assert "Tested commit SHA: abc123" in rendered
    assert "Approved additions:" in rendered
    assert "Skipped by policy:" in rendered
    assert "Manual review reasons:" in rendered
    assert "Exit status: 0" in rendered
