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


# --- Parser repair (#3677/#3678): attested heading forms + shared walk ---
# Fixtures below are trimmed verbatim excerpts of the real issue bodies
# whose criteria the pre-repair parser could not see (#3257, #3337), whose
# criterion identities disagreed between the preservation and satisfaction
# modules (#3258), or whose numbered requirements must stay manual-review
# in both modules (#3333). See the #3679 reconciliation report, section 5.

FIXTURE_3257 = '## Acceptance criteria and definition of done\n\n- [x] `imc-build` accepts an authorized visual selection and no longer refuses it (gate fails closed only when no runtime is configured).\n- [x] Each selected visual is planned into an exact slot with a stable role identity, producing image-insertion requests (repo-side).\n- [x] The #3130 slot-coverage check runs on the selection path and fails closed on uncovered required slots.\n- [x] A visuals-required MaterialRequirement completes only when every required slot is verified-placed (`require_all_required_visuals_placed`, repo-side).\n- [x] A missing placement runtime yields an explicit `placement-runtime-unavailable` blocked state, never "final".\n- [ ] **Live:** after a build against a real Doc and Slide, every placed visual is verified against the persisted artifact (slot, asset, content identity) and a persisted placement receipt is produced.\n- [ ] **Live canary:** `imc-build` with a non-empty governed selection and a configured `--placement-script-id` inserts the image, passes post-insertion readback verification, and persists the durable verified receipt.\n## Required tests, validation, and documentation\n'

FIXTURE_3337 = '### Acceptance criteria and definition of done\n\n- [ ] Identical frozen canonical task packets can be compared across candidate models/settings.\n- [ ] All seven task families and requested OpenAI/Anthropic/Muse identities are representable without fabricated capabilities.\n- [ ] #2744 configuration/continuity/source metadata is reused; model and actual reasoning setting are explicit.\n- [ ] Existing #1504 availability/reference/non-authority evidence mechanics are reused rather than duplicated.\n- [ ] Fixture-only evaluation performs zero external provider calls and needs no credentials.\n- [ ] Provider output stays untrusted and cannot authorize execution, readiness, merge, or closure.\n- [ ] Component metrics, comparability, contamination, sample sizes and unavailable costs/latency/tokens are reported faithfully.\n- [ ] Model-run cost/latency remains observational and does not redefine #520 or routing policy.\n- [ ] Future focused and exact-head validation passes.\nDefinition of done: a bounded offline harness, component report, mapping docs, and negative fixtures are reviewed; live results and automatic preference are not claimed from fake runs.\n\n### Tier 2 controls, when applicable\n\n_No response_\n\n### Safety confirmation\n\n- [x] No direct push to main, automatic merge, or autonomous issue closure is authorized.\n- [x] No production, governed-field, source-of-truth, sharing, or external-system write is authorized without explicit approval.\n- [x] Final implementation reporting will include files changed, tests run, docs updated, blockers, handoffs, and remaining risks.\n## 2026-10-13 — AI Navigation backlog reconciliation\n'

FIXTURE_3258 = '## Acceptance criteria\nRepository (satisfied by merged PR #3274):\n- [x] `final` / `succeeded` require a passing terminal content QA over persisted readback. Metadata-only verification yields `persisted`, not `final`.\n- [x] Any unresolved template token in a persisted artifact fails terminal QA with a token-level finding.\n- [x] Missing required content or required visuals fails QA, or reports manual review with the unresolved roles named. The output is never "final".\n- [x] Visual completeness and revision QA run in the build path, keyed to stable role identities.\n- [x] The CLI prints "final" only on QA pass.\n\nLive acceptance (pending, separately governed):\n- [ ] Terminal QA verified over persisted Docs/Slides readback on a real connected build.\n- [ ] Required-visual verification against #3257 placement receipts.\n'

FIXTURE_3333 = '## Acceptance criteria\n\n1. Current Codespace selection reuses the canonical resolver and fails closed for zero, multiple, stale, or invalid candidates.\n\n2. A currently admitted bounded implementation mission can invoke repository engineering operations on the selected Codespace without the user manually opening Codespaces or copying shell commands.\n'


def test_suffixed_level2_heading_yields_real_criteria_3257() -> None:
    criteria = parse_acceptance_criteria(FIXTURE_3257)
    assert len(criteria) == 7
    assert criteria[0].text.startswith("`imc-build` accepts an authorized visual selection")
    assert criteria[-1].text.startswith("**Live canary:**")
    # The following level-2 section is not part of the criteria section.
    assert all("Required tests" not in c.text for c in criteria)


def test_suffixed_level3_heading_yields_real_criteria_3337() -> None:
    criteria = parse_acceptance_criteria(FIXTURE_3337)
    # 9 acceptance checkboxes plus the 3 safety-confirmation checkboxes
    # that sit in the same level-2-delimited section of the real body.
    assert len(criteria) == 12
    assert criteria[0].text.startswith("Identical frozen canonical task packets")
    assert criteria[-1].text.startswith("Final implementation reporting will include")


def test_packet_for_3337_reports_unparsable_lines_as_manual_review() -> None:
    packet = build_criterion_packet(FIXTURE_3337)
    assert packet["criterion_count"] == 12
    assert packet["section_entry_count"] == 16
    manual = packet["manual_review_entries"]
    assert len(manual) == 4
    assert all(e["status"] == "manual-review" for e in manual)
    assert all(e["reason_code"] == "criterion-unparsable" for e in manual)
    # Parsable criteria keep their section positions: the 4 unparsable
    # lines sit between the 9 acceptance and 3 safety checkboxes.
    assert [c["index"] for c in packet["criteria"]] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 14, 15, 16]


def test_mixed_section_positions_and_packet_counts_3258() -> None:
    criteria = parse_acceptance_criteria(FIXTURE_3258)
    assert len(criteria) == 7
    # Two prose lines head the groups, so criteria sit at walk positions
    # 2-6 and 8-9, exactly where the satisfaction projection puts them.
    assert [c.index for c in criteria] == [2, 3, 4, 5, 6, 8, 9]
    packet = build_criterion_packet(FIXTURE_3258)
    assert packet["criterion_count"] == 7
    assert packet["section_entry_count"] == 9
    assert [e["index"] for e in packet["manual_review_entries"]] == [1, 7]
    assert packet["manual_review_entries"][0]["text"] == "Repository (satisfied by merged PR #3274):"


def test_numbered_requirements_are_never_promoted_3333() -> None:
    assert parse_acceptance_criteria(FIXTURE_3333) == ()
    packet = build_criterion_packet(FIXTURE_3333)
    assert packet["criterion_count"] == 0
    assert packet["section_entry_count"] == 2
    assert len(packet["manual_review_entries"]) == 2
    assert all(
        e["reason_code"] == "criterion-unparsable"
        for e in packet["manual_review_entries"]
    )


def test_supported_heading_variants_still_parse() -> None:
    for heading in (
        "## Acceptance criteria",
        "## Acceptance Criteria",
        "### Acceptance criteria",
        "## Acceptance criteria and definition of done",
        "### Acceptance criteria and definition of done",
    ):
        body = f"{heading}\n\n- [ ] Only criterion.\n"
        criteria = parse_acceptance_criteria(body)
        assert [c.text for c in criteria] == ["Only criterion."], heading


def test_unrecognized_headings_yield_no_criteria() -> None:
    from scripts.agent_os_issue_acceptance.criterion_preservation import (
        parse_criteria_section,
    )

    for heading in (
        "#### Acceptance criteria",
        "# Acceptance criteria",
        "## Acceptance criteria and definition of done, plus more",
        "## Acceptance criteria (draft)",
        "## Acceptance criteria checklist",
    ):
        body = f"{heading}\n\n- [ ] Not a criterion.\n"
        assert parse_acceptance_criteria(body) == (), heading
        assert parse_criteria_section(body) is None, heading


def test_empty_and_itemless_bodies_fail_closed() -> None:
    from scripts.agent_os_issue_acceptance.criterion_preservation import (
        parse_criteria_section,
    )

    assert parse_acceptance_criteria("") == ()
    assert parse_criteria_section("") is None
    heading_only = "## Acceptance criteria\n\n## Definition of done\n\n- [ ] Done item.\n"
    assert parse_acceptance_criteria(heading_only) == ()
    assert parse_criteria_section(heading_only) == ()
    packet = build_criterion_packet(heading_only)
    assert packet["criterion_count"] == 0
    assert packet["section_entry_count"] == 0
    assert packet["manual_review_entries"] == []


def test_packet_round_trip_for_suffixed_heading_3257() -> None:
    packet = build_criterion_packet(FIXTURE_3257)
    result = verify_criterion_packet(FIXTURE_3257, packet)
    assert result.status == "preserved"
    assert result.manual_review_indexes == ()
