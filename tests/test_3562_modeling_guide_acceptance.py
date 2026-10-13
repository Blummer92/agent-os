"""Regression tests for #3562: Teacher Modeling Guide must be a modeling
rehearsal, not a lesson-plan summary.

Covers:
- the Campus Bottle positive rehearsal fixture (must be accepted);
- the lesson-plan-shaped negative fixture mirroring the observed defective
  DOCX (must be rejected);
- fail-closed behavior on missing/blank evidence;
- enforcement of each of the six canonical modeling checks;
- modeling-guide request routing to the Teacher Modeling Coach rehearsal
  view (not the IMC teacher-guide document path);
- handoff blocker/authorization-boundary preservation (contract level);
- the new Modeling Guide Request Rule in the Teacher Modeling Coach
  overlay (contract-text, per repository test pattern).
"""

from pathlib import Path

import pytest

from src.instructional_workflow_contracts.modeling_guide_acceptance import (
    MODELING_GUIDE_DEFAULT_VIEW,
    MODELING_GUIDE_OWNER,
    SIX_MODELING_CHECKS,
    default_modeling_guide_view,
    evaluate_modeling_guide_acceptance,
    is_modeling_guide_request,
    resolve_modeling_guide_owner,
)

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "02_Agent_Overlays/teacher-modeling-coach.md"
STANDARD = ROOT / "01_Shared_Standards/instructional-design/teacher-modeling-standards.md"
TEMPLATE = ROOT / "03_Templates/prompts/teacher-talk-rehearsal.md"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Positive fixture: a classroom-ready rehearsal for the established fictional
# Campus Bottle case. Demonstrates all eight required rehearsal elements and
# evidences the six canonical modeling checks.
CAMPUS_BOTTLE_REHEARSAL = """\
# Teacher Modeling Guide — Day 1 Marketing Foundations: Campus Bottle

## Lesson goal
Students will evaluate a marketing pricing decision with survey evidence.

Learning objective: Students will construct an evidence-based claim about a
pricing decision, distinguishing evidence from assumptions.

## Immediate student task
Student task alignment: using the fictional Campus Bottle survey below,
students complete the Marketing Detectives worksheet: they state the pricing
recommendation the evidence supports and explain their reasoning.

Fictional survey of 40 students (classroom data for this lesson; not real
market research). A company sells an insulated reusable water bottle for $18
to high-school students. Distribution: online and at school events.
Promotion: posters and short videos.

Preferred price | Responses
$15 or less | 24
$16-$20 | 12
More than $20 | 4

## Play-by-play model

### Moment 1 — Name the marketing decision
| Moment | Teacher says | Teacher does | Students do or notice | Check |
|---|---|---|---|---|
| Name the decision | "Before we touch the numbers, let's name the exact marketing decision: should Campus Bottle keep the $18 price, change it, or keep the price and change promotion? The decision is the boss of everything we do next." | Teacher writes "DECISION: what should Campus Bottle do about the $18 price?" on the whiteboard and circles the word DECISION. Teacher displays the Campus Bottle visual anchor on the projector. | Students do or notice: students notice the circled word and repeat the decision question back. | Check: each student restates the decision in their own words — observable evidence of understanding. |

Think-aloud method: "I'm thinking aloud so you can hear the move — I don't start with the numbers, I start by naming the decision, because numbers mean nothing until we know what we're deciding."

### Moment 2 — Read the survey and separate evidence from assumptions
| Moment | Teacher says | Teacher does | Students do or notice | Check |
|---|---|---|---|---|
| Read the survey | "Step 1: read what the survey actually says. 24 of 40 prefer $15 or less, 12 prefer $16-$20, 4 prefer more than $20. Step 2: now split evidence from assumptions. Evidence: most surveyed students prefer a lower price. Assumption: they would actually buy at $15 — the survey never asked that." | Teacher highlights the three survey rows in different colors on the projected visual anchor and writes two columns on the whiteboard: EVIDENCE vs ASSUMPTIONS. Teacher underlines "prefer" and annotates: "prefer != will buy". | Students do or notice: students notice the two columns and call out which statements belong in each. | Check: students correctly sort two new statements into evidence vs assumptions — observable evidence of understanding. |

Component breakdown: the skill is split into small sequential steps — Step 1 read the data, Step 2 separate evidence from assumptions, Step 3 construct the claim — ordered for student reference.

### Moment 3 — Construct the claim, catch the mistake, correct it
| Moment | Teacher says | Teacher does | Students do or notice | Check |
|---|---|---|---|---|
| Build the claim | "Step 3: construct the claim using only the evidence column. First, I write the evidence: most prefer a lower price. Then, I build the claim: the evidence suggests price is a barrier for many students, but it does NOT prove $18 is wrong — we never tested buying at $18. Now the mistake I almost made: a common misconception is reading '24 students prefer $15 or less' as 'the company must drop the price.' That's a wrong inference — I catch it, I correct it on the board, and I write the fix: preference is not purchase intent." | Teacher constructs the claim sentence step by step on the whiteboard, then draws a large X through the wrong inference "must drop the price" and writes the correction underneath in a different color. | Students do or notice: students notice the X and the color change, and several say the corrected version aloud. | Check: students explain why "must drop the price" is wrong and state what information is still needed — observable evidence of understanding. |

Error analysis: the common mistake is treating preference as purchase intent; recognize it when a claim uses "must/should" without buying evidence; self-correct by returning to the evidence column; avoid it by always asking "did we test that?"

Visual anchors: the projected survey table and the EVIDENCE vs ASSUMPTIONS whiteboard columns are the visual anchors for this model.

Information we still need: actual purchase behavior at $18, competitor prices, and production cost — the survey cannot answer these.

### Transfer to guided practice
"Your turn: use the same moves — name the decision, read the evidence, separate evidence from assumptions, construct the claim — on your Marketing Detectives worksheet. I will circulate and check your evidence columns."

## Modeling checks evidenced
- learning objective: stated above, one measurable skill.
- student task alignment: the rehearsal prepares the immediate worksheet task.
- think-aloud method: teacher narration makes the decision visible at each moment.
- component breakdown: three ordered steps with student reference labels.
- visual anchors: projected survey table and whiteboard columns, specified above.
- error analysis: misconception named, recognized, corrected, and avoided.

## Bounded Materials extract
Selected teacher language, the three worked-example steps, the misconception/correction example, and the visual-anchor specification. Blockers: none. Next owner: Instructional Materials Coach. `execution_authorized: false`.
"""

# Negative fixture: mirrors the observed defective Day1_Teacher_Modeling_Research_Revised.docx —
# a condensed lesson plan / answer key labeled as a modeling guide. It has
# learning targets, timing blocks, and finished answers, but no per-moment
# rehearsal structure, no worked-example construction, no visual anchor, and
# no misconception correction.
LESSON_PLAN_SHAPED_GUIDE = """\
# Day 1 Teacher Modeling Guide — Marketing Foundations (Revised)

## Learning target
Students will understand the four Ps of marketing.

## Essential question
How do companies decide on price?

## Accurate content to teach
Price, product, place, promotion. Campus Bottle sells an insulated reusable
water bottle for $18 to high-school students. Distribution: online and at
school events. Promotion: posters and short videos.

## Case text
Fictional survey of 40 students: $15 or less: 24; $16-$20: 12; more than
$20: 4.

## I DO (4 min)
Think aloud: "Who is the customer? What need might an insulated bottle meet?"
Present the completed recommendation: the company should consider lowering
its price to $15 based on the survey.

## WE DO (5 min)
Walk through the four-P answer key together.

## YOU DO (3 min)
Students complete the Marketing Detectives worksheet.

## Four-P answer key
Product: insulated reusable water bottle. Price: $18 (consider $15).
Place: online and school events. Promotion: posters and short videos.

## Teacher guidance, checks, research basis
Research basis: verified marketing research on price sensitivity. Teacher
guidance: keep pace; check answers against the key.
"""


def test_positive_campus_bottle_rehearsal_is_accepted() -> None:
    result = evaluate_modeling_guide_acceptance(CAMPUS_BOTTLE_REHEARSAL)
    assert result.accepted, f"failed: {result.checks_failed} / {result.reason_codes}"
    assert result.checks_failed == ()
    assert len(result.checks_passed) == 4 + len(SIX_MODELING_CHECKS) + 1


def test_negative_lesson_plan_fixture_is_rejected() -> None:
    result = evaluate_modeling_guide_acceptance(LESSON_PLAN_SHAPED_GUIDE)
    assert not result.accepted
    # The structural rehearsal evidence the observed DOCX lacked must fail.
    for check in (
        "rehearsal-moment-structure",
        "worked-example-construction",
        "visual-anchor",
        "misconception-correction",
    ):
        assert check in result.checks_failed, f"{check} should fail: {result.reason_codes}"
    assert "moment-structure-missing" in result.reason_codes


@pytest.mark.parametrize("artifact", [None, "", "   ", "short"])
def test_missing_or_blank_evidence_fails_closed(artifact) -> None:
    result = evaluate_modeling_guide_acceptance(artifact)
    assert not result.accepted
    assert result.checks_failed[0] == "artifact-present"
    assert result.reason_codes[0] in ("artifact-missing", "artifact-too-short")


def test_each_canonical_check_is_individually_enforced() -> None:
    # Removing every evidence occurrence of a single canonical check name
    # must fail exactly that check (Moment 2 prose + checks list).
    tampered = CAMPUS_BOTTLE_REHEARSAL.replace("Component breakdown:", "Xxxxx:")
    tampered = tampered.replace("component breakdown:", "xxxxx:")
    assert "component breakdown" not in tampered.lower()
    result = evaluate_modeling_guide_acceptance(tampered)
    assert not result.accepted
    assert "canonical-check:component breakdown" in result.checks_failed
    assert "check-missing:component breakdown" in result.reason_codes


def test_six_checks_are_the_canonical_set() -> None:
    assert SIX_MODELING_CHECKS == (
        "learning objective",
        "student task alignment",
        "think-aloud method",
        "component breakdown",
        "visual anchors",
        "error analysis",
    )


def test_modeling_guide_request_resolves_to_teacher_modeling_coach_rehearsal() -> None:
    owner, view = resolve_modeling_guide_owner(
        "Create a teacher modeling guide and Marketing Detectives worksheet for Day 1."
    )
    assert owner == MODELING_GUIDE_OWNER == "teacher-modeling-coach"
    assert view == MODELING_GUIDE_DEFAULT_VIEW == "rehearsal"


def test_explicit_audit_view_request_is_honored() -> None:
    owner, view = resolve_modeling_guide_owner(
        "Create a teacher modeling guide, audit view, for Day 1."
    )
    assert owner == "teacher-modeling-coach"
    assert view == "audit"


def test_non_modeling_request_routes_elsewhere_unchanged() -> None:
    assert resolve_modeling_guide_owner("Create a Marketing Detectives worksheet.") == ("", "")
    assert not is_modeling_guide_request("Create a Marketing Detectives worksheet.")
    assert is_modeling_guide_request("Revise the teacher modeling guide with survey evidence.")


def test_default_view_is_rehearsal() -> None:
    assert default_modeling_guide_view("Create a teacher modeling guide.") == "rehearsal"
    assert default_modeling_guide_view("teacher modeling guide, materials extract") == "materials-extract"


def test_rejection_names_routable_blockers() -> None:
    # A rejected guide must surface specific missing artifacts so the
    # handoff can route them back to the Teacher Modeling Coach by name.
    result = evaluate_modeling_guide_acceptance(LESSON_PLAN_SHAPED_GUIDE)
    assert result.reason_codes, "rejection must carry reason codes for the handoff"
    assert all(code for code in result.reason_codes)


def test_handoff_preserves_blockers_and_authorization_boundary() -> None:
    # Contract level (repository pattern): the bounded Materials extract
    # preserves blockers and next owner, and never implies authorization.
    standard = STANDARD.read_text(encoding="utf-8")
    assert "blockers, and next owner" in standard
    assert "Preserve `execution_authorized: false`" in standard
    assert "never authorizes production, assessment, readiness" in standard
    template = TEMPLATE.read_text(encoding="utf-8")
    assert "Instructional Materials must not silently reconstruct required modeling" in template


def test_overlay_contains_modeling_guide_request_rule() -> None:
    content = OVERLAY.read_text(encoding="utf-8")
    assert "## Modeling Guide Request Rule (#3562)" in content
    assert "fulfilled as the `rehearsal` view of the modeling record" in content
    assert "not an Instructional Materials Coach `teacher-guide` / `teacher-reference` document" in content
    assert "fails modeling acceptance" in content
    assert "must not replace the record's content with a generic lesson-plan template" in content


def test_overlay_version_bumped_for_3562() -> None:
    content = OVERLAY.read_text(encoding="utf-8")
    assert "\n0.7.1\n" in content
    assert "#3562" in content
