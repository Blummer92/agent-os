"""Regression guards for #1719 pending exact-head CI continuation."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAFE_LANE = ROOT / "01_Shared_Standards/github/safe-implementation-lane.md"
FIXTURE = ROOT / "07_Agent_Tests/fixtures/pending-ci-continuation.md"


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split()).lower()


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
    assert "a ci-routed pending state grants no ready-for-review or later authority" in safe_lane
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
