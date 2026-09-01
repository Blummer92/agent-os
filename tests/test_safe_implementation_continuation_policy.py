from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAFE_LANE = ROOT / "01_Shared_Standards/github/safe-implementation-lane.md"


def _normalized_section(heading: str) -> str:
    text = SAFE_LANE.read_text(encoding="utf-8")
    marker = f"## {heading}"
    start = text.index(marker) + len(marker)
    remainder = text[start:]
    end = remainder.find("\n## ")
    section = remainder if end == -1 else remainder[:end]
    return " ".join(section.split())


def test_existing_valid_work_is_normally_a_resume_target() -> None:
    section = _normalized_section("Execution Continuation")
    assert "normally a resume target, not a stop condition" in section
    assert "consume the existing `ResumePlan`" in section
    assert "canonical Scheduler lease evidence" in section


def test_active_lease_never_grants_takeover_or_retry() -> None:
    section = _normalized_section("Execution Continuation")
    assert "existing active Scheduler lease is the concurrency authority" in section
    assert "Do not create a competing branch, PR, execution, or lease" in section
    assert "do not steal, force-release, expire by age, or automatically retry" in section


def test_head_advanced_and_base_behind_are_distinct() -> None:
    section = _normalized_section("Execution Continuation")
    assert "same authorized branch advances from SHA A to SHA B" in section
    assert "invalidate only the head-bound evidence" in section
    assert "If `main` advanced and the PR branch is behind" in section
    assert "rather than treating base drift as ordinary `HEAD_ADVANCED`" in section


def test_cancelled_stale_head_requires_complete_supersession_proof() -> None:
    section = _normalized_section("Execution Continuation")
    assert "`SUPERSEDED_BY_NEW_HEAD` only when" in section
    assert "newer run/check for B exists in the same validation lane/concurrency group" in section
    assert "genuine test or configuration failure on A remains genuine failure evidence" in section
    assert "Only validation bound to the current exact head may satisfy Ready-for-Review" in section


def test_same_objective_diagnosis_correction_continues_without_second_prompt() -> None:
    section = _normalized_section("Bounded Diagnosis Correction")
    assert "not by itself a material scope change" in section
    assert "underlying issue objective is unchanged" in section
    assert "corrected target is directly necessary to solve the same proven defect" in section
    assert "continue without requiring ritual user phrases" in section
    assert "a second `work on` instruction" in section


def test_bounded_correction_requires_reacquired_current_authorization_evidence() -> None:
    section = _normalized_section("Bounded Diagnosis Correction")
    assert "Reacquire the live issue, current authorization, source of truth" in section
    assert "same canonical implementation owner applies" in section
    assert "no stale, conflicting, blocked, or ambiguous evidence" in section
    assert "update the issue or handoff with the corrected root cause" in section


def test_material_scope_or_excluded_surface_still_needs_decision() -> None:
    section = _normalized_section("Bounded Diagnosis Correction")
    assert "material scope change and stop with `needs-decision`" in section
    assert "changes the underlying objective, source of truth, canonical owner" in section
    assert "architecture/schema/compatibility contract" in section
    assert "enters an excluded surface" in section
    assert "Conversation continuity never converts a material scope change into authorization" in section


def test_stop_conditions_do_not_treat_bounded_correction_as_a_stop() -> None:
    section = _normalized_section("Stop Conditions")
    assert "bounded diagnosis correction under the contract above" in section
