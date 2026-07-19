import json

from scripts.agent_os_issue_acceptance.legacy_preflight import (
    LegacyIssueSnapshot,
    classify_legacy_issue,
    evaluate_legacy_preflight,
    legacy_preflight_to_dict,
    render_legacy_preflight,
)


def ready_body(extra: str = "") -> str:
    return f"""
Issue tier: tier:0

## Objective

Test the issue.

## Owner

QA / Test Agent

## Allowed files

tests/

## Validation

Run focused tests.

## Completion

The focused tests pass.

{extra}
"""


def snapshot(
    number: int,
    *,
    body: str | None = None,
    labels: list[str] | None = None,
    state: str = "open",
    updated_at: str = "2026-07-19T00:00:00Z",
    open_pr_numbers: list[int] | None = None,
    title: str = "Implementation issue",
) -> dict:
    return {
        "number": number,
        "title": title,
        "state": state,
        "body": ready_body() if body is None else body,
        "labels": labels or [],
        "updated_at": updated_at,
        "open_pr_numbers": open_pr_numbers or [],
    }


def test_ready_legacy_issue_predicts_needs_decision_and_counts_blast_radius():
    report = evaluate_legacy_preflight(
        {
            "evaluator_sha": "abc123",
            "issues": [snapshot(1, labels=["status:ready", "type:tooling"])],
        }
    )

    assessment = report.assessments[0]
    assert assessment.classification == "active-implementation"
    assert assessment.predicted_documentation_status == "manual-review"
    assert assessment.predicted_transition == "ready->needs-decision"
    assert assessment.reason_codes == (
        "currently-labeled-ready",
        "legacy-metadata-missing",
    )
    assert report.metrics["currently_ready_label_missing_contract"] == 1
    assert report.metrics["would_change_ready_to_needs_decision"] == 1
    assert report.metrics["manual_review_rate_estimate"] == 1.0
    assert report.evaluator_sha == "abc123"


def test_blocked_and_open_pr_issues_are_classified_without_weakening_blockers():
    report = evaluate_legacy_preflight(
        {
            "issues": [
                snapshot(2, labels=["status:blocked"]),
                snapshot(3, labels=["status:ready"], open_pr_numbers=[44]),
            ]
        }
    )

    blocked, linked = report.assessments
    assert blocked.classification == "blocked-dependency"
    assert blocked.predicted_transition == "blocked->blocked"
    assert "already-blocked" in blocked.reason_codes
    assert linked.classification == "open-pr-linked"
    assert linked.open_pr_numbers == (44,)
    assert linked.predicted_transition == "ready->needs-decision"
    assert report.metrics["already_blocked_missing_contract"] == 1
    assert report.metrics["open_pr_linked_issue_missing_contract"] == 1


def test_compliant_required_docs_issue_is_already_compliant():
    body = ready_body(
        """
### Documentation impact

docs-required

### Required documentation paths or bounded areas

01_Shared_Standards/github

### Expected documentation change

Document the new operator behavior.
"""
    )

    assessment = classify_legacy_issue(
        LegacyIssueSnapshot.from_mapping(snapshot(4, body=body, labels=["status:ready"]))
    )

    assert assessment.classification == "already-compliant"
    assert assessment.documentation_impact == "docs-required"
    assert assessment.predicted_documentation_status == "pass"
    assert assessment.predicted_transition == "ready->ready"
    assert assessment.reason_codes == ("documentation-impact-present",)


def test_unknown_conflicting_and_duplicate_contracts_are_bounded_manual_review():
    unknown = ready_body("### Documentation impact\n\nfuture-value\n")
    conflicting = ready_body(
        """
```yaml
agent_os_issue_acceptance:
  documentation_impact: docs-required
```

### Documentation impact

docs-not-required
"""
    )
    duplicate = ready_body(
        """
### Documentation impact

docs-required

### Documentation impact

docs-required
"""
    )

    report = evaluate_legacy_preflight(
        {
            "issues": [
                snapshot(5, body=unknown, labels=["status:ready"]),
                snapshot(6, body=conflicting, labels=["status:ready"]),
                snapshot(7, body=duplicate, labels=["status:ready"]),
            ]
        }
    )

    by_number = {item.number: item for item in report.assessments}
    assert "documentation-impact-unknown" in by_number[5].reason_codes
    assert "documentation-source-conflict" in by_number[6].reason_codes
    assert "duplicate-documentation-heading" in by_number[7].reason_codes
    assert report.metrics["unknown_or_conflicting_contract"] == 2
    assert report.metrics["duplicate_heading_candidates"] == 1


def test_tracker_and_closed_issues_do_not_inflate_implementation_metrics():
    tracker_body = """
Issue tier: tier:2

## Role

Parent tracker only.

## Goal

Coordinate the roadmap.
"""
    report = evaluate_legacy_preflight(
        {
            "issues": [
                snapshot(
                    8,
                    title="DOC roadmap",
                    body=tracker_body,
                    labels=["type:planning", "status:ready"],
                ),
                snapshot(9, state="closed", labels=["status:ready"]),
            ]
        }
    )

    assert [item.number for item in report.assessments] == [8]
    assert report.assessments[0].classification == "tracker-or-roadmap"
    assert report.metrics["open_implementation_candidates"] == 0
    assert report.metrics["manual_review_rate_estimate"] == 0.0


def test_duplicate_snapshots_keep_newest_update_and_output_is_deterministic():
    report = evaluate_legacy_preflight(
        {
            "issues": [
                snapshot(
                    10,
                    labels=["status:blocked"],
                    updated_at="2026-07-18T00:00:00Z",
                ),
                snapshot(
                    10,
                    labels=["status:ready"],
                    updated_at="2026-07-19T00:00:00Z",
                ),
                snapshot(11, labels=["status:ready"]),
            ]
        }
    )

    assert [item.number for item in report.assessments] == [10, 11]
    assert report.assessments[0].status_label == "status:ready"
    assert render_legacy_preflight(report) == render_legacy_preflight(report)
    assert legacy_preflight_to_dict(report) == legacy_preflight_to_dict(report)


def test_rendered_and_json_outputs_do_not_leak_issue_body():
    secret = "DO-NOT-LEAK-THIS-FULL-BODY-TEXT"
    report = evaluate_legacy_preflight(
        {
            "issues": [
                snapshot(
                    12,
                    body=ready_body(f"Unrelated prose: {secret}"),
                    labels=["status:ready"],
                )
            ]
        }
    )

    text = render_legacy_preflight(report)
    encoded = json.dumps(legacy_preflight_to_dict(report), sort_keys=True)
    assert secret not in text
    assert secret not in encoded
    assert "issue=12" in text
    assert "legacy-metadata-missing" in encoded


def test_invalid_snapshot_number_is_rejected():
    try:
        LegacyIssueSnapshot.from_mapping({"number": True})
    except ValueError as error:
        assert "integer" in str(error)
    else:
        raise AssertionError("expected invalid snapshot number to be rejected")
