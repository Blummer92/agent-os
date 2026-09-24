"""Regression guards for #1719 pending exact-head CI continuation."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAFE_LANE = ROOT / "01_Shared_Standards/github/safe-implementation-lane.md"
FIXTURE = ROOT / "07_Agent_Tests/fixtures/pending-ci-continuation.md"


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split()).lower()


def states_invariant(text: str, *terms: str, qualifier: str) -> bool:
    """One sentence must bind every term to the restricting qualifier (#2858)."""
    sentences = re.split(r"(?<=[.;])\s+", " ".join(text.split()))
    return any(
        all(term in sentence for term in terms)
        and re.search(rf"\b{re.escape(qualifier)}\b", sentence, re.IGNORECASE)
        for sentence in sentences
    )


def test_pending_ci_states_are_nonterminal() -> None:
    fixture = normalized(FIXTURE)
    for phrase in (
        "ci-not-yet-visible",
        "checks-pending",
        "continues without another user prompt",
        "stale-head validation never satisfies the current generation",
        "terminal red routes into the existing red-ci continuation owner",
    ):
        assert phrase in fixture


def test_pending_ci_preserves_existing_safe_lane_authority_ceiling() -> None:
    fixture = normalized(FIXTURE)
    safe_lane = normalized(SAFE_LANE)
    assert states_invariant(safe_lane, "ci-routed pending state", "ready-for-review", "authority", qualifier="no")
    for phrase in (
        "no merge",
        "issue-closure",
        "workflow",
        "protected-setting",
        "credential/iam",
        "production",
        "external-write",
        "background worker",
        "polling daemon",
    ):
        assert phrase in fixture


def test_no_run_materialization_has_bounded_terminal_blocker() -> None:
    fixture = normalized(FIXTURE)
    assert "bounded observation policy expires" in fixture
    assert "exact head" in fixture
    assert "bounded-attempt evidence" in fixture
    assert "clearing condition" in fixture
