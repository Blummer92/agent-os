from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTING = ROOT / "01_Shared_Standards/global-engineering/testing-and-release.md"
SAFE_LANE = ROOT / "01_Shared_Standards/github/safe-implementation-lane.md"


def normalized_text(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def normalized_section(path: Path, heading: str) -> str:
    text = path.read_text(encoding="utf-8")
    marker = f"## {heading}"
    start = text.index(marker) + len(marker)
    remainder = text[start:]
    end = remainder.find("\n## ")
    section = remainder if end == -1 else remainder[:end]
    return " ".join(section.split())


def test_focused_local_validation_is_non_final() -> None:
    developer_loop = normalized_section(TESTING, "Developer Loop Validation")
    authoritative = normalized_section(TESTING, "Authoritative Final Validation")
    lane = normalized_section(SAFE_LANE, "Validation Loop")

    assert (
        "A focused pass is non-final evidence: treat it as `aggregate-pending`, "
        "not as final validation success."
    ) in developer_loop
    assert (
        "A focused pass never suppresses, replaces, or impersonates the required "
        "final exact-head aggregate."
    ) in authoritative
    assert "01_Shared_Standards/global-engineering/testing-and-release.md" in lane
    assert "Ready-for-Review still requires all required exact-head checks to pass." in lane


def test_clean_exact_head_ci_may_satisfy_full_suite_requirement() -> None:
    developer_loop = normalized_section(TESTING, "Developer Loop Validation")
    authoritative = normalized_section(TESTING, "Authoritative Final Validation")

    assert (
        "Do not run another local full aggregate solely before pushing when a clean "
        "exact-head CI aggregate will run the full suite."
    ) in developer_loop
    assert (
        "One clean aggregate run bound to the exact final pull-request head may satisfy "
        "the full-suite requirement, including when that run is performed by GitHub CI."
    ) in authoritative
    assert (
        "The full suite remains required before release or Ready-for-Review when the "
        "governing repository workflow requires aggregate validation."
    ) in authoritative
    assert "Release only with required exact-head evidence and checklist status." in authoritative


def test_broader_local_validation_remains_available_for_diagnosis() -> None:
    developer_loop = normalized_section(TESTING, "Developer Loop Validation")

    assert (
        "Expand local testing when focused tests fail, when exact-head CI reports a "
        "specific failure that needs diagnosis, when CI is unavailable, or when the "
        "governing issue explicitly requires broader local validation."
    ) in developer_loop
