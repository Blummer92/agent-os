"""Regression tests for #3677: preserve original issue requirements in PR
templates and implementation handoffs.

Covers the five acceptance criteria of #3677:
1. The shipped PR template contains a criterion-preservation section that
   names the linked issue and requires a per-criterion mapping or an
   explicit manual-review statement, and its linkage defaults to
   non-closing.
2. A fixture built from the shipped template, with only the non-closing
   linkage field filled in, returns zero GitHub-effective closing
   references from the canonical detector in parse_pr.py.
3. The handoff packet output reports every criterion parsed from the
   canonical issue body with its identity preserved; a fixture with one
   criterion dropped or reworded returns manual-review for that criterion.
4. Existing parser behavior for closing references, the non-closing
   directive, and bare references matches the pre-change results.
5. The updated standards and package README describe the new template
   default and packet behavior with no stale description of the old
   default.
"""

from __future__ import annotations

from pathlib import Path

from scripts.agent_os_issue_acceptance.criterion_preservation import (
    build_criterion_packet,
    parse_acceptance_criteria,
    verify_criterion_packet,
)
from scripts.agent_os_issue_acceptance.models import LinkedIssueParseStatus
from scripts.agent_os_issue_acceptance.parse_pr import (
    detect_github_effective_closing_references,
    parse_linked_issue_result,
)

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md"
LIFECYCLE_STANDARD = ROOT / "01_Shared_Standards" / "github" / "issue-lifecycle-standard.md"
AUTOMATION_STANDARD = (
    ROOT / "01_Shared_Standards" / "github" / "issue-acceptance-automation.md"
)
PACKAGE_README = ROOT / "scripts" / "agent_os_issue_acceptance" / "README.md"

ISSUE_BODY = """## Objective and value

Fixture objective.

## Acceptance criteria

- [ ] First criterion stays exact.
- [ ] Second criterion is preserved verbatim.
- [ ] Third criterion carries its identity.

## Definition of done

- [ ] Done item is not an acceptance criterion.
"""


def _template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


# --- Criterion 1: template structure --------------------------------------


def test_template_linkage_defaults_to_non_closing() -> None:
    template = _template()
    assert "Part of #N" in template
    assert "Closes #" not in template
    assert "non-closing by default" in template


def test_template_has_criterion_preservation_section() -> None:
    template = _template()
    assert "## Criterion preservation" in template
    section = template.split("## Criterion preservation", 1)[1]
    # The section names the linked issue and offers exactly the two
    # contract forms: per-criterion mapping or manual-review statement.
    assert "Linked issue: #N" in section
    assert "Per-criterion mapping" in section
    assert "Manual review:" in section
    assert "criterion_preservation.py" in template


def test_template_states_closing_opt_in_requires_admission() -> None:
    template = _template()
    assert "closure admission for this exact issue" in template


# --- Criterion 2: template fixture yields zero closing references ---------


def test_template_fixture_linkage_filled_has_zero_closing_references() -> None:
    fixture = _template().replace("Part of #N", "Part of #3677")
    assert detect_github_effective_closing_references(fixture) == ()


def test_template_fixture_all_placeholders_filled_has_zero_closing_references() -> None:
    fixture = _template().replace("#N", "#3677")
    assert detect_github_effective_closing_references(fixture) == ()


def test_template_raw_has_zero_closing_references() -> None:
    assert detect_github_effective_closing_references(_template()) == ()


# --- Criterion 4: pre-change parser behavior is unchanged -----------------


def test_parser_negated_prose_is_still_a_closing_reference() -> None:
    refs = detect_github_effective_closing_references(
        "This PR does not close #2772."
    )
    assert [(r.keyword, r.target) for r in refs] == [("close", "#2772")]


def test_parser_non_closing_directive_still_informational() -> None:
    result = parse_linked_issue_result("Part of #3372\nNon-closing: #3372")
    assert result.status is LinkedIssueParseStatus.INFORMATIONAL
    assert result.issue_number is None


def test_parser_explicit_closing_keyword_still_resolves() -> None:
    result = parse_linked_issue_result("Closes #3372")
    assert result.status is LinkedIssueParseStatus.RESOLVED
    assert result.issue_number == 3372


def test_parser_bare_reference_still_manual_review() -> None:
    result = parse_linked_issue_result("Part of #3372")
    assert result.status is LinkedIssueParseStatus.MANUAL_REVIEW


# --- Criterion 3: handoff packet round-trip --------------------------------


def test_parse_criteria_preserves_text_and_order() -> None:
    criteria = parse_acceptance_criteria(ISSUE_BODY)
    assert [c.text for c in criteria] == [
        "First criterion stays exact.",
        "Second criterion is preserved verbatim.",
        "Third criterion carries its identity.",
    ]
    assert [c.index for c in criteria] == [1, 2, 3]
    assert len({c.identity for c in criteria}) == 3


def test_parse_criteria_ignores_other_sections() -> None:
    criteria = parse_acceptance_criteria(ISSUE_BODY)
    assert all("Done item" not in c.text for c in criteria)
    assert parse_acceptance_criteria("## Summary\n\n- [ ] Not a criterion.\n") == ()


def test_packet_reports_every_criterion_with_identity() -> None:
    packet = build_criterion_packet(ISSUE_BODY)
    criteria = parse_acceptance_criteria(ISSUE_BODY)
    assert packet["criterion_count"] == 3
    assert packet["criteria"] == [
        {"index": c.index, "identity": c.identity, "text": c.text} for c in criteria
    ]


def test_packet_round_trip_verifies_preserved() -> None:
    packet = build_criterion_packet(ISSUE_BODY)
    result = verify_criterion_packet(ISSUE_BODY, packet)
    assert result.status == "preserved"
    assert result.manual_review_indexes == ()
    assert [r.reason_code for r in result.results] == ["criterion-preserved"] * 3


def test_packet_dropped_criterion_is_manual_review_for_that_criterion() -> None:
    packet = build_criterion_packet(ISSUE_BODY)
    packet["criteria"] = [
        entry for entry in packet["criteria"] if entry["index"] != 2
    ]
    result = verify_criterion_packet(ISSUE_BODY, packet)
    assert result.status == "manual-review"
    assert result.manual_review_indexes == (2,)
    by_index = {r.index: r for r in result.results}
    assert by_index[2].reason_code == "criterion-dropped"
    assert by_index[1].status == "preserved"
    assert by_index[3].status == "preserved"


def test_packet_reworded_criterion_is_manual_review_for_that_criterion() -> None:
    packet = build_criterion_packet(ISSUE_BODY)
    packet["criteria"][1]["text"] = "Second criterion, loosely restated."
    result = verify_criterion_packet(ISSUE_BODY, packet)
    assert result.status == "manual-review"
    assert result.manual_review_indexes == (2,)
    by_index = {r.index: r for r in result.results}
    assert by_index[2].reason_code == "criterion-reworded"


def test_packet_missing_identity_is_manual_review() -> None:
    packet = build_criterion_packet(ISSUE_BODY)
    del packet["criteria"][0]["identity"]
    result = verify_criterion_packet(ISSUE_BODY, packet)
    assert result.status == "manual-review"
    assert result.manual_review_indexes == (1,)
    by_index = {r.index: r for r in result.results}
    assert by_index[1].reason_code == "criterion-identity-mismatch"


def test_packet_forged_identity_is_manual_review() -> None:
    packet = build_criterion_packet(ISSUE_BODY)
    packet["criteria"][2]["identity"] = "criterion-3-000000000000"
    result = verify_criterion_packet(ISSUE_BODY, packet)
    assert result.status == "manual-review"
    assert result.manual_review_indexes == (3,)
    by_index = {r.index: r for r in result.results}
    assert by_index[3].reason_code == "criterion-identity-mismatch"


def test_packet_with_unrecognized_criterion_is_manual_review() -> None:
    packet = build_criterion_packet(ISSUE_BODY)
    packet["criteria"].append(
        {"index": 4, "identity": "criterion-4-000000000000", "text": "Invented."}
    )
    result = verify_criterion_packet(ISSUE_BODY, packet)
    assert result.status == "manual-review"
    assert result.manual_review_indexes == (4,)


def test_empty_canonical_criteria_never_verifies_preserved() -> None:
    result = verify_criterion_packet("## Summary\n\nNo criteria here.\n", {"criteria": []})
    assert result.status == "manual-review"


# --- Criterion 5: docs describe the new default, no stale text ------------


def test_docs_describe_new_template_default_and_packet() -> None:
    for path in (LIFECYCLE_STANDARD, AUTOMATION_STANDARD, PACKAGE_README):
        text = path.read_text(encoding="utf-8")
        assert "Part of #N" in text, path
        assert "criterion" in text.lower(), path
    assert "criterion_preservation.py" in PACKAGE_README.read_text(encoding="utf-8")
    assert "criterion_preservation.py" in LIFECYCLE_STANDARD.read_text(encoding="utf-8")


def test_docs_have_no_stale_old_default_description() -> None:
    for path in (LIFECYCLE_STANDARD, AUTOMATION_STANDARD, PACKAGE_README, TEMPLATE):
        text = path.read_text(encoding="utf-8")
        assert "Closes #" not in text, path
        assert "Exactly one closing keyword and issue number" not in text, path
