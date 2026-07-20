from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.agent_os_issue_acceptance.documentation_gap_report import (
    DocumentationGapCategory,
    build_documentation_gap_report,
    records_from_snapshot,
    render_documentation_gap_report_json,
    render_documentation_gap_report_text,
)
from scripts.agent_os_issue_acceptance.issue_scanner import IssueScannerRecord


def record(
    number: int,
    *,
    body: str,
    labels: tuple[str, ...] = ("type:implementation",),
    state: str = "open",
    revision: str | None = None,
    title: str = "Implementation work",
) -> IssueScannerRecord:
    timestamp = revision or f"2026-07-20T00:{number:02d}:00Z"
    return IssueScannerRecord(
        issue_number=number,
        title=title,
        state=state,
        body=body,
        labels=labels,
        url=f"https://github.com/example/repo/issues/{number}",
        created_at="2026-07-19T00:00:00Z",
        updated_at=timestamp,
        source_revision=timestamp,
    )


def authority_body(extra: str = "") -> str:
    return f"""
## Objective
Implement a bounded report.
## Owner
QA / Test Agent
## Source of truth
GitHub
## Scope
Local report only.
## Acceptance criteria
- [ ] Report is deterministic.
{extra}
"""


def category_for(item: IssueScannerRecord) -> DocumentationGapCategory:
    report = build_documentation_gap_report([item], evaluator_revision="abc123")
    return report.rows[0].category


def test_compliant_active_issue_is_already_compliant() -> None:
    item = record(
        1,
        body=authority_body(
            """
## Documentation impact
docs-not-required
## Documentation exemption reason
The report changes no public behavior.
"""
        ),
    )
    report = build_documentation_gap_report([item], evaluator_revision="abc123")
    assert report.rows[0].category == DocumentationGapCategory.ALREADY_COMPLIANT
    assert report.rows[0].documentation_impact == "docs-not-required"


def test_active_missing_contract_is_backfill_now() -> None:
    item = record(2, body=authority_body())
    row = build_documentation_gap_report([item], evaluator_revision="abc123").rows[0]
    assert row.category == DocumentationGapCategory.BACKFILL_NOW
    assert "legacy-metadata-missing" in row.reason_codes
    assert "documentation-impact-missing" in row.reason_codes
    assert "recent-active-implementation-candidate" in row.reason_codes


def test_blocked_missing_contract_is_deferred() -> None:
    item = record(3, body=authority_body(), labels=("type:implementation", "status:blocked"))
    assert category_for(item) == DocumentationGapCategory.DEFER_BLOCKED


def test_roadmap_is_not_applicable() -> None:
    item = record(4, body=authority_body(), labels=("type:roadmap",))
    assert category_for(item) == DocumentationGapCategory.NOT_APPLICABLE


def test_current_type_planning_label_is_not_applicable() -> None:
    item = record(19, body=authority_body(), labels=("type:planning", "type:documentation"))
    assert category_for(item) == DocumentationGapCategory.NOT_APPLICABLE


def test_current_roadmap_body_contract_is_not_applicable() -> None:
    item = record(
        20,
        body="""Roadmap issue — Level 1 contract.
## Objective
Coordinate child implementation issues.
## Owner
Integration Manager
## Source of truth
GitHub
## Scope
Track sequencing only.
## Acceptance criteria
- [ ] Child dependencies remain accurate.
""",
        labels=("type:documentation",),
    )
    assert category_for(item) == DocumentationGapCategory.NOT_APPLICABLE


def test_current_planning_only_body_contract_is_not_applicable() -> None:
    item = record(
        21,
        body="""## Objective
Review existing assets.
## Scope
Produce a recommendation.
## Acceptance criteria
- [ ] Recommendation is complete.

This is a planning and gap-analysis issue only. Do not implement code.
""",
        labels=(),
    )
    assert category_for(item) == DocumentationGapCategory.NOT_APPLICABLE


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ("## Source of truth\nGitHub\n## Objective\nWork\n## Scope\nLocal", "unclear-owner"),
        ("## Owner\nQA / Test Agent\n## Objective\nWork\n## Scope\nLocal", "unclear-source-of-truth"),
    ],
)
def test_missing_authority_requires_manual_decision(body: str, reason: str) -> None:
    row = build_documentation_gap_report([record(5, body=body)], evaluator_revision="abc123").rows[0]
    assert row.category == DocumentationGapCategory.MANUAL_OWNER_DECISION
    assert reason in row.reason_codes


def test_cleanup_candidate_is_recommendation_only() -> None:
    item = record(6, body=authority_body("\nSuperseded by #99\n"))
    row = build_documentation_gap_report([item], evaluator_revision="abc123").rows[0]
    assert row.category == DocumentationGapCategory.CLEANUP_CANDIDATE
    assert "do not mutate automatically" in row.recommended_action


def test_unknown_documentation_impact_requires_manual_decision() -> None:
    item = record(7, body=authority_body("\n## Documentation impact\ndocs-maybe\n"))
    row = build_documentation_gap_report([item], evaluator_revision="abc123").rows[0]
    assert row.category == DocumentationGapCategory.MANUAL_OWNER_DECISION
    assert "documentation-impact-unknown" in row.reason_codes


def test_duplicate_documentation_heading_requires_manual_decision() -> None:
    item = record(
        8,
        body=authority_body(
            """
## Documentation impact
docs-not-required
## Documentation exemption reason
No public behavior changes.
## Documentation impact
docs-not-required
"""
        ),
    )
    row = build_documentation_gap_report([item], evaluator_revision="abc123").rows[0]
    assert row.category == DocumentationGapCategory.MANUAL_OWNER_DECISION
    assert "duplicate-heading" in row.reason_codes


def test_closed_issue_is_excluded() -> None:
    report = build_documentation_gap_report(
        [record(9, body=authority_body(), state="closed")],
        evaluator_revision="abc123",
    )
    assert report.rows == ()
    assert report.metrics.open_issue_count == 0


def test_zero_denominator_metrics_are_safe() -> None:
    report = build_documentation_gap_report([], evaluator_revision="abc123")
    assert report.metrics.legacy_manual_review_rate == 0.0
    assert report.metrics.open_implementation_candidates == 0


def test_identical_duplicate_snapshots_do_not_duplicate_rows() -> None:
    item = record(10, body=authority_body())
    report = build_documentation_gap_report([item, item], evaluator_revision="abc123")
    assert len(report.rows) == 1


def test_conflicting_duplicate_snapshots_fail_closed() -> None:
    first = record(11, body=authority_body(), revision="2026-07-20T00:00:00Z")
    second = record(11, body=authority_body("\nchanged\n"), revision="2026-07-20T00:01:00Z")
    row = build_documentation_gap_report([first, second], evaluator_revision="abc123").rows[0]
    assert row.category == DocumentationGapCategory.MANUAL_OWNER_DECISION
    assert "duplicate-snapshot-conflict" in row.reason_codes
    assert "ambiguous-manual-review" in row.reason_codes


def test_ordering_and_rendering_are_deterministic() -> None:
    records = [record(14, body=authority_body()), record(12, body=authority_body()), record(13, body=authority_body())]
    first = build_documentation_gap_report(records, evaluator_revision="abc123")
    second = build_documentation_gap_report(reversed(records), evaluator_revision="abc123")
    assert first == second
    assert render_documentation_gap_report_json(first) == render_documentation_gap_report_json(second)
    assert render_documentation_gap_report_text(first) == render_documentation_gap_report_text(second)


def test_report_does_not_leak_issue_body_or_title() -> None:
    secret = "PRIVATE-BODY-CONTENT"
    item = record(15, body=authority_body(f"\n{secret}\n"), title="PRIVATE TITLE")
    rendered = render_documentation_gap_report_json(
        build_documentation_gap_report([item], evaluator_revision="abc123")
    )
    assert secret not in rendered
    assert "PRIVATE TITLE" not in rendered


def test_snapshot_reader_requires_complete_bounded_fields() -> None:
    payload = {
        "issues": [
            {
                "issue_number": 16,
                "title": "Work",
                "state": "open",
                "body": authority_body(),
                "labels": ["type:implementation"],
                "url": "https://github.com/example/repo/issues/16",
                "created_at": "2026-07-19T00:00:00Z",
                "updated_at": "2026-07-20T00:00:00Z",
                "source_revision": "2026-07-20T00:00:00Z",
            }
        ]
    }
    parsed = records_from_snapshot(json.loads(json.dumps(payload)))
    assert parsed[0].issue_number == 16
    with pytest.raises(ValueError, match="missing field"):
        records_from_snapshot({"issues": [{"issue_number": 1}]})


def test_module_has_no_network_or_write_surface() -> None:
    source = (
        Path(__file__).parents[2]
        / "scripts/agent_os_issue_acceptance/documentation_gap_report.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        "requests.",
        "urllib",
        "socket",
        "subprocess",
        "create_issue",
        "update_issue",
        "add_label",
        "delete_issue",
    )
    assert not any(value in source for value in forbidden)
    assert "execution_authorized: bool = False" in source
    assert "side_effects_performed: bool = False" in source


def test_yaml_and_heading_conflict_requires_manual_review() -> None:
    body = authority_body(
        """
```yaml
agent_os_issue_acceptance:
  documentation_impact: docs-required
```
## Documentation impact
docs-not-required
## Documentation exemption reason
No public behavior changes.
"""
    )
    row = build_documentation_gap_report([record(17, body=body)], evaluator_revision="abc123").rows[0]
    assert row.category == DocumentationGapCategory.MANUAL_OWNER_DECISION
    assert "ambiguous-manual-review" in row.reason_codes


def test_required_metric_names_are_rendered() -> None:
    report = build_documentation_gap_report([record(18, body=authority_body())], evaluator_revision="abc123")
    rendered = render_documentation_gap_report_text(report)
    for name in (
        "open_implementation_candidates",
        "legacy_missing_documentation_impact",
        "backfill_now_count",
        "defer_blocked_count",
        "manual_owner_decision_count",
        "cleanup_candidate_count",
        "not_applicable_count",
        "already_compliant_count",
        "legacy_manual_review_rate",
    ):
        assert f"{name}:" in rendered
