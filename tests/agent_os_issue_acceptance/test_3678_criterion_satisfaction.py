"""Tests for #3678: criterion-level satisfaction verification.

Covers the seven acceptance criteria of #3678:
1. Exactly one disposition per criterion parsed from the canonical issue
   body, each carrying an evidence pointer or an explicit missing-evidence
   reason.
2. A criterion lacking any evidence reports overall satisfaction
   incomplete; missing, stale, or contradicted criteria never report
   complete satisfaction.
3. Evidence bound to a superseded PR head or to a prior issue-body
   version reports stale and does not satisfy its criterion.
4. A two-PR fixture accumulates evidence across both PRs; criteria
   evidenced by either report satisfied, the rest report unsatisfied.
5. Disagreeing evidence sources report contradicted; an unparsable
   criteria section returns manual-review for every affected criterion.
6. Informational registration preserves existing behavior: golden
   Acceptance Report output keeps identical overall results, blockers,
   and exit behavior before and after the change.
7. A partial PR can pass its own implementation QA while the parent
   issue's satisfaction report still reports incomplete, with the
   unsatisfied criteria named.

Plus adversarial attempts to obtain complete satisfaction from insufficient
evidence: merge-only, CI-only, review-only signals; evidence for a
different issue or unknown criterion; duplicated evidence; evidence from
a second open (non-primary) PR; and a lineage with two open primaries.
"""

from __future__ import annotations

import hashlib

import pytest

from scripts.agent_os_issue_acceptance.criterion_preservation import (
    build_criterion_packet,
    parse_acceptance_criteria,
)
from scripts.agent_os_issue_acceptance.criterion_satisfaction import (
    CriterionEvidence,
    Disposition,
    PrLineageEntry,
    attach_satisfaction_evidence,
    issue_body_digest,
    project_criterion_satisfaction,
    satisfaction_informational_checks,
)
from scripts.agent_os_issue_acceptance.models import (
    AcceptanceReport,
    CheckResult,
    Status,
)
from scripts.agent_os_issue_acceptance.report import exit_code_for, render_report

BODY_V1 = """## Issue tier

tier:2-governed-cross-system

## Acceptance criteria

- [ ] Alpha criterion is verified.
- [ ] Beta criterion is verified.
- [ ] Gamma criterion is verified.

## Definition of done

- [ ] Done when the projection reports honestly.
"""

# Same criteria, one unrelated line changed: a different body version.
BODY_V2 = BODY_V1.replace("Done when the projection reports honestly.", "Done.")

MERGED_PR = PrLineageEntry(pr_number=101, state="merged", head_sha="aaa111")
PRIMARY_PR = PrLineageEntry(pr_number=102, state="open-primary", head_sha="bbb222")
SECOND_OPEN_PR = PrLineageEntry(pr_number=103, state="open-non-primary", head_sha="ccc333")


def verdict(index: int, source: str, pr: PrLineageEntry, body: str, result: str = "supports"):
    return CriterionEvidence(
        criterion_index=index,
        kind="criterion-verdict",
        verdict=result,
        pr_number=pr.pr_number,
        pr_head_sha=pr.head_sha,
        issue_body_digest=issue_body_digest(body),
        source=source,
    )


def signal(index: int, source: str, pr: PrLineageEntry, body: str):
    return CriterionEvidence(
        criterion_index=index,
        kind="pr-signal",
        pr_number=pr.pr_number,
        pr_head_sha=pr.head_sha,
        issue_body_digest=issue_body_digest(body),
        source=source,
    )


def dispositions(projection):
    return {d.index: d for d in projection.criteria}


# --- Criterion 1: one disposition per criterion, evidence or reason -----


def test_one_disposition_per_criterion_with_pointer_or_reason():
    projection = project_criterion_satisfaction(
        BODY_V1, [verdict(1, "pr:101@aaa111/qa", MERGED_PR, BODY_V1)], [MERGED_PR]
    )
    assert [d.index for d in projection.criteria] == [1, 2, 3]
    canonical = parse_acceptance_criteria(BODY_V1)
    assert [d.identity for d in projection.criteria] == [c.identity for c in canonical]
    for item in projection.criteria:
        assert item.evidence, f"criterion {item.index} has neither pointer nor reason"
    assert dispositions(projection)[1].disposition is Disposition.SATISFIED
    assert dispositions(projection)[1].evidence == ("evidence=pr:101@aaa111/qa",)
    for index in (2, 3):
        item = dispositions(projection)[index]
        assert item.disposition is Disposition.MISSING
        assert item.reason_code == "evidence-missing"
        assert item.evidence == ("missing_reason=evidence-missing",)


def test_parse_matches_criterion_preservation_on_canonical_body():
    projection = project_criterion_satisfaction(BODY_V1)
    canonical = parse_acceptance_criteria(BODY_V1)
    assert [(d.index, d.text, d.identity) for d in projection.criteria] == [
        (c.index, c.text, c.identity) for c in canonical
    ]


# --- Criterion 2: incomplete on missing / stale / contradicted ----------


def test_missing_evidence_reports_incomplete():
    projection = project_criterion_satisfaction(BODY_V1, [], [MERGED_PR])
    assert not projection.complete
    assert all(d.disposition is Disposition.MISSING for d in projection.criteria)


@pytest.mark.parametrize("blocker", ["missing", "stale", "contradicted"])
def test_blocking_dispositions_never_complete(blocker):
    if blocker == "missing":
        evidence = [
            verdict(1, "pr:101@aaa111/qa", MERGED_PR, BODY_V1),
            verdict(2, "pr:101@aaa111/qa", MERGED_PR, BODY_V1),
        ]
    elif blocker == "stale":
        evidence = [
            verdict(1, "pr:101@aaa111/qa", MERGED_PR, BODY_V1),
            verdict(2, "pr:101@aaa111/qa", MERGED_PR, BODY_V1),
            CriterionEvidence(
                criterion_index=3,
                kind="criterion-verdict",
                verdict="supports",
                pr_number=101,
                pr_head_sha="000fff",  # superseded head; lineage head is aaa111
                issue_body_digest=issue_body_digest(BODY_V1),
                source="pr:101@000fff/qa",
            ),
        ]
    else:
        evidence = [
            verdict(1, "pr:101@aaa111/qa", MERGED_PR, BODY_V1),
            verdict(2, "pr:101@aaa111/qa", MERGED_PR, BODY_V1),
            verdict(3, "pr:101@aaa111/qa", MERGED_PR, BODY_V1, "supports"),
            verdict(3, "pr:102@bbb222/qa", PRIMARY_PR, BODY_V1, "contradicts"),
        ]
    projection = project_criterion_satisfaction(
        BODY_V1, evidence, [MERGED_PR, PRIMARY_PR]
    )
    assert not projection.complete
    assert dispositions(projection)[3].disposition is not Disposition.SATISFIED


def test_all_satisfied_is_complete():
    evidence = [
        verdict(i, f"pr:101@aaa111/qa-{i}", MERGED_PR, BODY_V1) for i in (1, 2, 3)
    ]
    projection = project_criterion_satisfaction(BODY_V1, evidence, [MERGED_PR])
    assert projection.complete
    assert projection.unsatisfied_criteria == ()


# --- Criterion 3: stale head / stale body version ------------------------


def test_superseded_pr_head_reports_stale():
    stale = CriterionEvidence(
        criterion_index=1,
        kind="criterion-verdict",
        verdict="supports",
        pr_number=102,
        pr_head_sha="000fff",  # lineage head is bbb222
        issue_body_digest=issue_body_digest(BODY_V1),
        source="pr:102@000fff/qa",
    )
    projection = project_criterion_satisfaction(BODY_V1, [stale], [PRIMARY_PR])
    item = dispositions(projection)[1]
    assert item.disposition is Disposition.STALE
    assert item.reason_code == "stale-pr-head"
    assert not projection.complete


def test_prior_issue_body_version_reports_stale():
    old = verdict(1, "pr:101@aaa111/qa", MERGED_PR, BODY_V1)
    projection = project_criterion_satisfaction(BODY_V2, [old], [MERGED_PR])
    item = dispositions(projection)[1]
    assert item.disposition is Disposition.STALE
    assert item.reason_code == "stale-issue-body-version"


def test_stale_plus_current_evidence_satisfies():
    stale = verdict(1, "pr:101@aaa111/qa-old-body", MERGED_PR, BODY_V2)
    current = verdict(1, "pr:101@aaa111/qa", MERGED_PR, BODY_V1)
    projection = project_criterion_satisfaction(BODY_V1, [stale, current], [MERGED_PR])
    assert dispositions(projection)[1].disposition is Disposition.SATISFIED


# --- Criterion 4: two-PR accumulation ------------------------------------


def test_two_pr_accumulation():
    evidence = [
        verdict(1, "pr:101@aaa111/qa", MERGED_PR, BODY_V1),  # earlier merged PR
        verdict(2, "pr:102@bbb222/qa", PRIMARY_PR, BODY_V1),  # open primary PR
        # The remaining criterion is evidenced by a PR and reported unsatisfied.
        verdict(3, "pr:101@aaa111/qa", MERGED_PR, BODY_V1, "contradicts"),
    ]
    projection = project_criterion_satisfaction(
        BODY_V1, evidence, [MERGED_PR, PRIMARY_PR]
    )
    found = dispositions(projection)
    assert found[1].disposition is Disposition.SATISFIED
    assert found[2].disposition is Disposition.SATISFIED
    assert found[3].disposition is Disposition.UNSATISFIED
    assert not projection.complete


def test_current_contradiction_reports_unsatisfied():
    evidence = [verdict(1, "pr:101@aaa111/qa", MERGED_PR, BODY_V1, "contradicts")]
    projection = project_criterion_satisfaction(BODY_V1, evidence, [MERGED_PR])
    item = dispositions(projection)[1]
    assert item.disposition is Disposition.UNSATISFIED
    assert item.reason_code == "criterion-reported-unsatisfied"


# --- Criterion 5: contradicted + unparsable -------------------------------


def test_disagreeing_sources_report_contradicted():
    evidence = [
        verdict(1, "pr:101@aaa111/qa", MERGED_PR, BODY_V1, "supports"),
        verdict(1, "pr:102@bbb222/qa", PRIMARY_PR, BODY_V1, "contradicts"),
    ]
    projection = project_criterion_satisfaction(
        BODY_V1, evidence, [MERGED_PR, PRIMARY_PR]
    )
    item = dispositions(projection)[1]
    assert item.disposition is Disposition.CONTRADICTED
    assert not projection.complete


def test_unparsable_section_manual_review_for_every_affected_criterion():
    body = BODY_V1.replace(
        "- [ ] Beta criterion is verified.", "Beta criterion is verified (free text)."
    )
    projection = project_criterion_satisfaction(body, [], [MERGED_PR])
    found = dispositions(projection)
    assert found[2].disposition is Disposition.MANUAL_REVIEW
    assert found[2].reason_code == "criterion-unparsable"
    assert found[1].disposition is Disposition.MISSING
    assert not projection.complete


def test_missing_criteria_section_is_manual_review_not_complete():
    projection = project_criterion_satisfaction("## Objective\n\nNothing here.\n")
    assert projection.criteria == ()
    assert not projection.complete
    assert projection.notes == ("criteria-section-missing",)


# --- Criterion 6: golden informational registration -----------------------


def _golden_report() -> AcceptanceReport:
    return AcceptanceReport(
        linked_issue=3678,
        overall_status=Status.WARN,
        checks=[
            CheckResult("required fields", Status.PASS, "ok", ["field=objective"]),
            CheckResult("docs", Status.WARN, "warn", ["field=docs"]),
        ],
        manual_review_items=["one manual item"],
        evidence=["base evidence"],
        blockers=[],
        remaining_risks=["a risk"],
    )


def test_attach_preserves_overall_blockers_and_exit_behavior():
    report = _golden_report()
    before_render = render_report(report)
    projection = project_criterion_satisfaction(
        BODY_V1, [verdict(1, "pr:101@aaa111/qa", MERGED_PR, BODY_V1)], [MERGED_PR]
    )
    attached = attach_satisfaction_evidence(report, projection)
    assert attached.overall_status == report.overall_status
    assert attached.blockers == report.blockers
    assert attached.manual_review_items == report.manual_review_items
    assert attached.checks == report.checks
    assert exit_code_for(attached.overall_status) == exit_code_for(report.overall_status)
    # The base report object is untouched, and its render is the legacy bytes.
    assert report.informational_checks == ()
    assert render_report(report) == before_render
    # The attached render only gains the informational section.
    rendered = render_report(attached)
    assert "criterion satisfaction (informational)" in rendered
    assert "disposition=missing" in rendered
    assert rendered.startswith(before_render.split("Reusable-capability evidence")[0])


def test_attach_complete_projection_is_informational_pass_only():
    evidence = [verdict(i, f"pr:101@aaa111/qa-{i}", MERGED_PR, BODY_V1) for i in (1, 2, 3)]
    projection = project_criterion_satisfaction(BODY_V1, evidence, [MERGED_PR])
    attached = attach_satisfaction_evidence(_golden_report(), projection)
    (check,) = attached.informational_checks
    assert check.status is Status.PASS
    assert attached.overall_status is Status.WARN  # unchanged base result
    assert any("authorization=informational-only" in line for line in check.evidence)


def test_attach_malformed_projection_degrades_to_informational_error():
    attached = attach_satisfaction_evidence(_golden_report(), object())
    (check,) = attached.informational_checks
    assert check.status is Status.MANUAL_REVIEW
    assert attached.overall_status is Status.WARN
    assert attached.blockers == []


# --- Criterion 7: partial PR, incomplete issue ----------------------------


def test_partial_pr_passes_own_qa_but_issue_stays_incomplete_and_named():
    # The partial PR's own QA verdict supports only criterion 1.
    evidence = [verdict(1, "pr:102@bbb222/implementation-qa", PRIMARY_PR, BODY_V1)]
    projection = project_criterion_satisfaction(BODY_V1, evidence, [PRIMARY_PR])
    assert not projection.complete
    named = {d.identity for d in projection.unsatisfied_criteria}
    canonical = parse_acceptance_criteria(BODY_V1)
    assert named == {canonical[1].identity, canonical[2].identity}
    check = satisfaction_informational_checks(projection)[0]
    for identity in named:
        assert any(identity in line for line in check.evidence)


# --- Adversarial: insufficient evidence must never complete --------------


@pytest.mark.parametrize(
    "kind_source",
    [
        "pr:101/merged",
        "pr:101/ci-green-aggregate",
        "pr:101/review-approved",
    ],
)
def test_pr_signals_never_satisfy(kind_source):
    evidence = [signal(i, kind_source, MERGED_PR, BODY_V1) for i in (1, 2, 3)]
    projection = project_criterion_satisfaction(BODY_V1, evidence, [MERGED_PR])
    assert not projection.complete
    for item in projection.criteria:
        assert item.disposition is Disposition.MISSING
        assert item.reason_code == "evidence-missing-criterion-verdict"


def test_evidence_for_other_issue_body_does_not_satisfy():
    foreign = [verdict(i, f"pr:101@aaa111/qa-{i}", MERGED_PR, BODY_V2) for i in (1, 2, 3)]
    projection = project_criterion_satisfaction(BODY_V1, foreign, [MERGED_PR])
    assert not projection.complete
    assert all(d.disposition is Disposition.STALE for d in projection.criteria)


def test_evidence_for_unknown_criterion_is_noted_and_ignored():
    evidence = [verdict(i, f"pr:101@aaa111/qa-{i}", MERGED_PR, BODY_V1) for i in (1, 2, 3)]
    evidence.append(verdict(9, "pr:101@aaa111/qa-9", MERGED_PR, BODY_V1))
    projection = project_criterion_satisfaction(BODY_V1, evidence, [MERGED_PR])
    assert projection.complete  # known criteria genuinely satisfied
    assert "evidence-for-unknown-criterion" in projection.notes


def test_duplicated_evidence_counts_once():
    one = verdict(1, "pr:101@aaa111/qa", MERGED_PR, BODY_V1, "supports")
    against = verdict(1, "pr:101@aaa111/qa", MERGED_PR, BODY_V1, "contradicts")
    # The same source cannot both support and contradict by duplication:
    # identical records dedupe; a distinct contradicting record is required.
    projection = project_criterion_satisfaction(BODY_V1, [one, one, one], [MERGED_PR])
    assert dispositions(projection)[1].disposition is Disposition.SATISFIED
    projection2 = project_criterion_satisfaction(BODY_V1, [one, against], [MERGED_PR])
    assert dispositions(projection2)[1].disposition is Disposition.CONTRADICTED


def test_second_open_pr_evidence_is_stale_not_current():
    evidence = [verdict(1, "pr:103@ccc333/qa", SECOND_OPEN_PR, BODY_V1)]
    projection = project_criterion_satisfaction(
        BODY_V1, evidence, [PRIMARY_PR, SECOND_OPEN_PR]
    )
    item = dispositions(projection)[1]
    assert item.disposition is Disposition.STALE
    assert item.reason_code == "stale-non-primary-pr"


def test_two_open_primaries_force_manual_review():
    other_primary = PrLineageEntry(pr_number=103, state="open-primary", head_sha="ccc333")
    evidence = [verdict(i, f"pr:102@bbb222/qa-{i}", PRIMARY_PR, BODY_V1) for i in (1, 2, 3)]
    projection = project_criterion_satisfaction(
        BODY_V1, evidence, [PRIMARY_PR, other_primary]
    )
    assert not projection.complete
    assert all(
        d.disposition is Disposition.MANUAL_REVIEW for d in projection.criteria
    )
    assert all(
        d.reason_code == "lineage-multiple-open-primary" for d in projection.criteria
    )


def test_unverifiable_source_is_stale():
    orphan = CriterionEvidence(
        criterion_index=1,
        kind="criterion-verdict",
        verdict="supports",
        pr_number=999,
        pr_head_sha="zzz999",
        issue_body_digest=issue_body_digest(BODY_V1),
        source="pr:999@zzz999/qa",
    )
    projection = project_criterion_satisfaction(BODY_V1, [orphan], [MERGED_PR])
    item = dispositions(projection)[1]
    assert item.disposition is Disposition.STALE
    assert item.reason_code == "stale-source-unverifiable"


def test_projection_is_deterministic():
    evidence = [
        verdict(2, "pr:102@bbb222/qa", PRIMARY_PR, BODY_V1),
        verdict(1, "pr:101@aaa111/qa", MERGED_PR, BODY_V1),
    ]
    first = project_criterion_satisfaction(BODY_V1, evidence, [MERGED_PR, PRIMARY_PR])
    second = project_criterion_satisfaction(
        BODY_V1, list(reversed(evidence)), [PRIMARY_PR, MERGED_PR]
    )
    assert first == second


def test_body_digest_binds_exact_version():
    assert issue_body_digest(BODY_V1) == hashlib.sha256(BODY_V1.encode()).hexdigest()
    assert issue_body_digest(BODY_V1) != issue_body_digest(BODY_V2)


# --- Parser repair (#3677/#3678): one shared section walk ---------------
# The trimmed real-body fixtures are defined in
# test_3677_criterion_preservation.py's repair section; the excerpts here
# are the same verbatim text, kept local so this file stays self-contained.

FIXTURE_3257 = '## Acceptance criteria and definition of done\n\n- [x] `imc-build` accepts an authorized visual selection and no longer refuses it (gate fails closed only when no runtime is configured).\n- [x] Each selected visual is planned into an exact slot with a stable role identity, producing image-insertion requests (repo-side).\n- [x] The #3130 slot-coverage check runs on the selection path and fails closed on uncovered required slots.\n- [x] A visuals-required MaterialRequirement completes only when every required slot is verified-placed (`require_all_required_visuals_placed`, repo-side).\n- [x] A missing placement runtime yields an explicit `placement-runtime-unavailable` blocked state, never "final".\n- [ ] **Live:** after a build against a real Doc and Slide, every placed visual is verified against the persisted artifact (slot, asset, content identity) and a persisted placement receipt is produced.\n- [ ] **Live canary:** `imc-build` with a non-empty governed selection and a configured `--placement-script-id` inserts the image, passes post-insertion readback verification, and persists the durable verified receipt.\n## Required tests, validation, and documentation\n'

FIXTURE_3337 = '### Acceptance criteria and definition of done\n\n- [ ] Identical frozen canonical task packets can be compared across candidate models/settings.\n- [ ] All seven task families and requested OpenAI/Anthropic/Muse identities are representable without fabricated capabilities.\n- [ ] #2744 configuration/continuity/source metadata is reused; model and actual reasoning setting are explicit.\n- [ ] Existing #1504 availability/reference/non-authority evidence mechanics are reused rather than duplicated.\n- [ ] Fixture-only evaluation performs zero external provider calls and needs no credentials.\n- [ ] Provider output stays untrusted and cannot authorize execution, readiness, merge, or closure.\n- [ ] Component metrics, comparability, contamination, sample sizes and unavailable costs/latency/tokens are reported faithfully.\n- [ ] Model-run cost/latency remains observational and does not redefine #520 or routing policy.\n- [ ] Future focused and exact-head validation passes.\nDefinition of done: a bounded offline harness, component report, mapping docs, and negative fixtures are reviewed; live results and automatic preference are not claimed from fake runs.\n\n### Tier 2 controls, when applicable\n\n_No response_\n\n### Safety confirmation\n\n- [x] No direct push to main, automatic merge, or autonomous issue closure is authorized.\n- [x] No production, governed-field, source-of-truth, sharing, or external-system write is authorized without explicit approval.\n- [x] Final implementation reporting will include files changed, tests run, docs updated, blockers, handoffs, and remaining risks.\n## 2026-10-13 — AI Navigation backlog reconciliation\n'

FIXTURE_3258 = '## Acceptance criteria\nRepository (satisfied by merged PR #3274):\n- [x] `final` / `succeeded` require a passing terminal content QA over persisted readback. Metadata-only verification yields `persisted`, not `final`.\n- [x] Any unresolved template token in a persisted artifact fails terminal QA with a token-level finding.\n- [x] Missing required content or required visuals fails QA, or reports manual review with the unresolved roles named. The output is never "final".\n- [x] Visual completeness and revision QA run in the build path, keyed to stable role identities.\n- [x] The CLI prints "final" only on QA pass.\n\nLive acceptance (pending, separately governed):\n- [ ] Terminal QA verified over persisted Docs/Slides readback on a real connected build.\n- [ ] Required-visual verification against #3257 placement receipts.\n'

FIXTURE_3333 = '## Acceptance criteria\n\n1. Current Codespace selection reuses the canonical resolver and fails closed for zero, multiple, stale, or invalid candidates.\n\n2. A currently admitted bounded implementation mission can invoke repository engineering operations on the selected Codespace without the user manually opening Codespaces or copying shell commands.\n'


def test_satisfaction_recognizes_suffixed_level2_section_3257():
    projection = project_criterion_satisfaction(FIXTURE_3257)
    assert projection.notes == ()
    assert len(projection.criteria) == 7
    canonical = parse_acceptance_criteria(FIXTURE_3257)
    assert [(d.index, d.text, d.identity) for d in projection.criteria] == [
        (c.index, c.text, c.identity) for c in canonical
    ]


def test_satisfaction_recognizes_suffixed_level3_section_3337():
    projection = project_criterion_satisfaction(FIXTURE_3337)
    assert projection.notes == ()
    parsable = [d for d in projection.criteria if d.reason_code != "criterion-unparsable"]
    unparsable = [d for d in projection.criteria if d.reason_code == "criterion-unparsable"]
    assert len(parsable) == 12
    assert len(unparsable) == 4
    assert all(d.disposition is Disposition.MANUAL_REVIEW for d in unparsable)
    assert not projection.complete
    canonical = parse_acceptance_criteria(FIXTURE_3337)
    assert [(d.index, d.text, d.identity) for d in parsable] == [
        (c.index, c.text, c.identity) for c in canonical
    ]


def test_preservation_and_satisfaction_agree_on_mixed_section_3258():
    packet = build_criterion_packet(FIXTURE_3258)
    projection = project_criterion_satisfaction(FIXTURE_3258)
    # Same set, same positions, same identities in both modules.
    assert packet["section_entry_count"] == len(projection.criteria) == 9
    assert packet["criterion_count"] == 7
    assert len(packet["manual_review_entries"]) == 2
    canonical = parse_acceptance_criteria(FIXTURE_3258)
    parsable = [d for d in projection.criteria if d.reason_code != "criterion-unparsable"]
    assert [(d.index, d.text, d.identity) for d in parsable] == [
        (c.index, c.text, c.identity) for c in canonical
    ]
    unparsable = [d for d in projection.criteria if d.reason_code == "criterion-unparsable"]
    assert [d.index for d in unparsable] == [
        e["index"] for e in packet["manual_review_entries"]
    ]
    assert all(d.disposition is Disposition.MANUAL_REVIEW for d in unparsable)


def test_numbered_requirements_manual_review_in_both_modules_3333():
    packet = build_criterion_packet(FIXTURE_3333)
    projection = project_criterion_satisfaction(FIXTURE_3333)
    assert packet["criterion_count"] == 0
    assert packet["section_entry_count"] == len(projection.criteria) == 2
    assert all(
        d.disposition is Disposition.MANUAL_REVIEW
        and d.reason_code == "criterion-unparsable"
        for d in projection.criteria
    )
    assert not projection.complete


def test_repaired_projection_is_deterministic():
    first = project_criterion_satisfaction(FIXTURE_3337)
    second = project_criterion_satisfaction(FIXTURE_3337)
    assert first == second
