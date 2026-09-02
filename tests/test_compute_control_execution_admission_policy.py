from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STANDARD = ROOT / "01_Shared_Standards/github/compute-control-execution-admission.md"


def test_all_canonical_dispositions_have_admission_semantics():
    text = STANDARD.read_text()
    for value in (
        "do-not-spend-compute-yet",
        "unavailable",
        "reuse-existing-evidence",
        "focused-validation-first",
        "final-cloud-validation-required",
        "duplicate-or-obsolete-run-risk",
        "run-now",
    ):
        assert value in text


def test_deterministic_blockers_stop_before_expensive_execution():
    text = STANDARD.read_text()
    assert "before that compute is spent" in text
    assert "merely to discover a blocker" in text
    assert "Missing, stale, malformed, conflicting, ambiguous, or incomplete" in text


def test_old_head_and_duplicate_run_risk_fail_closed():
    text = STANDARD.read_text()
    assert "Old-head evidence cannot suppress current-head validation" in text
    assert "cannot start a second run by default" in text


def test_projection_is_non_authorizing_and_not_a_second_router():
    text = STANDARD.read_text()
    assert "does not define a second compute router" in text
    assert "grants no implementation, merge, closure" in text
