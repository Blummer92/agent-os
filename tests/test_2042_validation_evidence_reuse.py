"""Regression fixture for #2042's redundant aggregate validation admission."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LANE = ROOT / "01_Shared_Standards/github/safe-implementation-lane.md"


def normalized() -> str:
    return " ".join(LANE.read_text(encoding="utf-8").split())


def test_current_exact_head_evidence_is_reused_when_still_valid() -> None:
    lane = normalized()
    assert "Only validation bound to the current exact head may satisfy Ready-for-Review." in lane
    assert "When the existing exact-head CI aggregate subsumes the focused checks, one clean exact-head aggregate may satisfy both obligations without duplicate local execution." in lane


def test_head_change_invalidates_stale_head_validation() -> None:
    lane = normalized()
    assert "When the same authorized branch advances from SHA A to SHA B" in lane
    assert "invalidate only the head-bound evidence required by existing contracts" in lane
    assert "stale-head CI is insufficient" in lane


def test_draft_or_metadata_continuation_does_not_require_aggregate_by_default() -> None:
    lane = normalized()
    assert "this lane does not require aggregate validation on ordinary Draft PR updates" in lane
    assert "does not create or modify a workflow to obtain validation" in lane
