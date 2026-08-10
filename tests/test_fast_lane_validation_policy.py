from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTING = ROOT / "01_Shared_Standards/global-engineering/testing-and-release.md"
SAFE_LANE = ROOT / "01_Shared_Standards/github/safe-implementation-lane.md"


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_focused_local_validation_is_non_final() -> None:
    testing = normalized(TESTING)
    lane = normalized(SAFE_LANE)

    assert "smallest relevant focused tests" in testing
    assert "aggregate-pending" in testing
    assert "focused pass never suppresses, replaces, or impersonates" in testing
    assert "01_Shared_Standards/global-engineering/testing-and-release.md" in lane
    assert "Ready-for-Review still requires all required exact-head checks to pass" in lane


def test_clean_exact_head_ci_may_satisfy_full_suite_requirement() -> None:
    testing = normalized(TESTING)

    assert "One clean aggregate run bound to the exact final pull-request head may satisfy the full-suite requirement" in testing
    assert "GitHub CI" in testing
    assert "Do not run another local full aggregate" in testing


def test_broader_local_validation_remains_available_for_diagnosis() -> None:
    testing = normalized(TESTING)

    assert "focused tests fail" in testing
    assert "specific failure" in testing
    assert "CI is unavailable" in testing
    assert "explicitly requires broader local validation" in testing
