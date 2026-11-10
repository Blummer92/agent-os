"""#3566: Day 1 worksheet-quality regression pins (instructional-materials-coach).

#3566 stays the single bounded owner of the Day 1 Marketing Detectives
worksheet-quality regression. These tests pin ONLY the mechanically governed
dimensions of its 10-item verification list that live in this package:

- (6) balanced pagination, structural side: #3416 heading keep-with-next via
  ``_evaluate_pagination`` (rendered-side reuse is pinned in
  tests/regressions/test_issue_3566_worksheet_quality_regression.py).
- (7) correct image placement and scale, presence/identity/attribution side:
  receipt-verified placement consumption (``_evaluate_visuals``), role/slot
  binding completeness (``visual_completeness``), and the revision render
  visual gate (``worksheet_revision_qa``). Rendered placement/scale
  correctness is PARKED: it needs the #3258 rendered-layout acceptance
  ownership determination (evidence producer + governed consumer) not yet
  named.
- (9) warm-up / exit-ticket presence: ``artifact_structure`` required-section
  checks (slide-spec level) and ``validate_required_worksheet_sections``
  (Docs-plan level). Instructional *completeness* is PARKED: human-scored
  under the rubric's "Worksheet usability" row.

PARKED (documented, not implemented): (1) readability, (2) conciseness,
(3) scaffold judgment, (4) table/cell spacing, (5) response-area size,
(7-rendered) rendered placement/scale, (8) grayscale, (9-completeness)
completeness, (10) human gate (no code). No production code is changed by
this file; no thresholds are invented.
"""

from __future__ import annotations

from instructional_materials_coach.artifact_content_qa import (
    QA_STATE_PAGINATION_UNVERIFIED,
    QA_STATE_PLACEMENT_UNVERIFIED,
    ArtifactObservation,
    VisualExpectation,
    _evaluate_pagination,
    _evaluate_visuals,
)
from instructional_materials_coach.placement_receipts import (
    BATCH_PROOF_CONTRACT,
    batch_proof_fingerprint,
)
from instructional_materials_coach.artifact_structure import (
    FAIL,
    PASS,
    validate_artifact_structure,
    validate_required_worksheet_sections,
)
from instructional_materials_coach.visual_completeness import (
    validate_visual_completeness,
)
from instructional_materials_coach.worksheet_pagination import HeadingParagraph
from instructional_materials_coach.worksheet_revision_qa import (
    validate_revision_render_visuals,
)

# --- (6) structural pagination: #3416 heading keep-with-next -------------------

_DAY1_HEADINGS = (
    HeadingParagraph(named_style_type="HEADING_1", keep_with_next=True, text="Warm-Up", start_index=0, end_index=None),
    HeadingParagraph(named_style_type="HEADING_1", keep_with_next=True, text="Mission 1", start_index=10, end_index=None),
    HeadingParagraph(named_style_type="HEADING_1", keep_with_next=True, text="Exit Ticket", start_index=20, end_index=None),
)


def _day1_observation(headings: tuple[HeadingParagraph, ...]) -> ArtifactObservation:
    return ArtifactObservation(
        artifact_type="docs",
        artifact_id="day1-marketing-detectives",
        revision_id="rev-day1-1",
        full_text="Warm-Up Mission 1 Exit Ticket",
        headings=headings,
    )


def test_day1_all_headings_keep_with_next_passes() -> None:
    assert _evaluate_pagination(_day1_observation(_DAY1_HEADINGS)) == []


def test_day1_stranded_heading_fails_pagination_unverified() -> None:
    stranded = (
        HeadingParagraph(named_style_type="HEADING_1", keep_with_next=True, text="Warm-Up", start_index=0, end_index=None),
        HeadingParagraph(named_style_type="HEADING_1", keep_with_next=False, text="Mission 1", start_index=10, end_index=None),
    )
    findings = _evaluate_pagination(_day1_observation(stranded))
    assert len(findings) == 1
    finding = findings[0]
    assert finding.code == "qa-heading-keep-with-next-missing"
    assert finding.state == QA_STATE_PAGINATION_UNVERIFIED
    assert finding.detail["count"] == 1


# --- (9) warm-up / exit-ticket presence ----------------------------------------

_DAY1_SPEC = {
    "slides": [
        {"kind": "warm-up", "title": "Day 1 warm-up",
         "regions": {"title": [0, 0, 100, 10], "body": [0, 12, 100, 40]}},
        {"kind": "independent-task", "title": "Mission 1 practice",
         "teaching_move_ids": ["move-practice-1"],
         "regions": {"title": [0, 0, 100, 10], "body": [0, 12, 100, 40], "action": [0, 54, 100, 20]}},
        {"kind": "exit-ticket", "title": "Day 1 exit ticket",
         "regions": {"title": [0, 0, 100, 10], "body": [0, 12, 100, 40], "check": [0, 54, 100, 20]}},
    ],
    "requirements": {"warm_up": True, "exit_ticket": True},
}


def test_day1_required_sections_present_passes() -> None:
    result = validate_artifact_structure(_DAY1_SPEC)
    assert result.status == PASS
    assert result.passed
    assert not [f for f in result.findings if f.code.startswith("artifact-required-")]


def test_day1_missing_warm_up_fails_required_section() -> None:
    spec = {
        "slides": [{"kind": "independent-task", "title": "Mission 1 practice"}],
        "requirements": {"warm_up": True, "exit_ticket": False},
    }
    result = validate_artifact_structure(spec)
    assert result.status == FAIL
    codes = [f.code for f in result.findings]
    assert "artifact-required-warm-up-missing" in codes


def test_day1_missing_exit_ticket_fails_required_section() -> None:
    spec = {
        "slides": [{"kind": "warm-up", "title": "Day 1 warm-up"}],
        "requirements": {"warm_up": False, "exit_ticket": True},
    }
    result = validate_artifact_structure(spec)
    assert result.status == FAIL
    codes = [f.code for f in result.findings]
    assert "artifact-required-exit-ticket-missing" in codes


def _day1_docs_requests(*tokens: str) -> tuple[dict, ...]:
    return tuple(
        {"replaceAllText": {"containsText": {"text": "{{" + token + "}}"}, "replaceText": "Day 1 content"}}
        for token in tokens
    )


def test_day1_worksheet_plan_covers_required_sections() -> None:
    result = validate_required_worksheet_sections(
        required_sections=("warm-up", "exit-ticket"),
        curriculum_decision_tokens={"warm-up": "warm_up", "exit-ticket": "exit_ticket"},
        docs_requests=_day1_docs_requests("warm_up", "exit_ticket"),
    )
    assert result.status == PASS
    assert result.passed


def test_day1_worksheet_plan_missing_exit_ticket_fails() -> None:
    result = validate_required_worksheet_sections(
        required_sections=("warm-up", "exit-ticket"),
        curriculum_decision_tokens={"warm-up": "warm_up", "exit-ticket": "exit_ticket"},
        docs_requests=_day1_docs_requests("warm_up"),
    )
    assert result.status == FAIL
    codes = [f.code for f in result.findings]
    assert "worksheet-required-section-missing-from-plan" in codes


# --- (7) visual presence / identity / receipt attribution -----------------------

_DAY1_VISUALS = (
    VisualExpectation(role_id="day1-hero-image", slot_id="slot-1", asset_id="asset-day1-hero",
                      content_identity={"sha256": "day1hero"}, required=True),
    VisualExpectation(role_id="day1-diagram", slot_id="slot-2", asset_id="asset-day1-diagram",
                      content_identity={"sha256": "day1diagram"}, required=True),
)


def _day1_receipt(role_id: str, slot_id: str, asset_id: str, content_identity: dict) -> dict:
    return {
        "state": "verified",
        "role_id": role_id,
        "slot_id": slot_id,
        "artifact_type": "docs",
        "artifact_id": "day1-marketing-detectives",
        "asset_id": asset_id,
        "content_identity": content_identity,
        "post_insertion_revision_id": "rev-day1-1",
        "inserted_element_id": "img-" + role_id,
    }


def _day1_batch_proof(records) -> dict:
    """Hand-built reconciled batch proof for the Day 1 receipts.

    Terminal QA's strict rule requires a batch proof for a multi-receipt
    batch; the proof is attested here (not synthesized by placement) and
    its fingerprint is recomputed by the verifier, so tampering is still
    caught.
    """
    members = [
        {
            "role_id": r["role_id"],
            "slot_id": r["slot_id"],
            "batch_artifact_type": "docs",
            "artifact_id": "day1-marketing-detectives",
            "asset_id": r.get("asset_id"),
            "drive_file_id": r.get("drive_file_id"),
            "content_identity": dict(r["content_identity"]),
            "inserted_element_id": r["inserted_element_id"],
            "post_insertion_revision_id": r["post_insertion_revision_id"],
            "member_source": "placed",
        }
        for r in records
    ]
    proof = {
        "proof_contract": BATCH_PROOF_CONTRACT,
        "idempotency_key": "day1-key",
        "batch_artifact_type": "docs",
        "artifact_id": "day1-marketing-detectives",
        "initial_revision_id": "rev-day1-0",
        "final_revision_id": "rev-day1-1",
        "ordered_members": members,
        "insertion_continuity": [],
        "reconciled_at": "2026-10-19T00:00:00+00:00",
    }
    proof["proof_fingerprint"] = batch_proof_fingerprint(proof)
    return proof


def test_day1_verified_visual_placement_passes() -> None:
    observation = ArtifactObservation(
        artifact_type="docs",
        artifact_id="day1-marketing-detectives",
        revision_id="rev-day1-1",
        full_text="Day 1 worksheet content",
        image_element_ids=("img-day1-hero-image", "img-day1-diagram"),
        headings=(),
    )
    records = tuple(
        _day1_receipt(v.role_id, v.slot_id, v.asset_id, dict(v.content_identity))
        for v in _DAY1_VISUALS
    )
    findings = _evaluate_visuals(
        artifact_type="docs",
        artifact_id="day1-marketing-detectives",
        observation=observation,
        visual_expectations=_DAY1_VISUALS,
        placement_records=records,
        batch_proofs=(_day1_batch_proof(records),),
    )
    assert findings == []


def test_day1_required_visual_without_receipt_is_unadmitted() -> None:
    observation = ArtifactObservation(
        artifact_type="docs",
        artifact_id="day1-marketing-detectives",
        revision_id="rev-day1-1",
        full_text="Day 1 worksheet content",
        image_element_ids=(),
        headings=(),
    )
    findings = _evaluate_visuals(
        artifact_type="docs",
        artifact_id="day1-marketing-detectives",
        observation=observation,
        visual_expectations=_DAY1_VISUALS,
        placement_records=(),
    )
    codes = [f.code for f in findings]
    assert codes.count("qa-placement-unverified") == 2
    assert all(f.state == QA_STATE_PLACEMENT_UNVERIFIED for f in findings if f.code == "qa-placement-unverified")


def test_day1_visual_completeness_all_verified_passes() -> None:
    result = validate_visual_completeness(
        required_roles=("day1-hero-image", "day1-diagram"),
        verified_roles=("day1-hero-image", "day1-diagram"),
    )
    assert result.status == "pass"


def test_day1_visual_completeness_missing_role_fails() -> None:
    result = validate_visual_completeness(
        required_roles=("day1-hero-image", "day1-diagram"),
        verified_roles=("day1-hero-image",),
    )
    assert result.status == "fail"
    assert "day1-diagram" in result.missing_roles


def test_day1_visual_completeness_unresolved_role_routes_to_manual_review() -> None:
    result = validate_visual_completeness(
        required_roles=("day1-hero-image", "day1-diagram"),
        verified_roles=("day1-hero-image",),
        unresolved_roles=("day1-diagram",),
    )
    assert result.status == "manual-review"


def test_day1_revision_render_visuals_present_passes() -> None:
    result = validate_revision_render_visuals(
        required_role_ids=("day1-hero-image", "day1-diagram"),
        rendered_visual_role_ids=("day1-hero-image", "day1-diagram"),
    )
    assert result.findings == ()


def test_day1_revision_render_unresolved_visual_needs_manual_review() -> None:
    result = validate_revision_render_visuals(
        required_role_ids=("day1-hero-image", "day1-diagram"),
        rendered_visual_role_ids=("day1-hero-image",),
        unresolved_visual_role_ids=("day1-diagram",),
    )
    codes = [f.code for f in result.findings]
    assert "worksheet-revision-render-visual-needs-review" in codes
