from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "07_Agent_Tests" / "github-service-agent.tests.md"


def test_connected_issue_creation_supplies_and_verifies_known_labels() -> None:
    text = FIXTURES.read_text(encoding="utf-8")

    assert "## Test 23 - Connected Issue Creation Supplies Known Managed Labels" in text
    assert "accepts a `labels` list" in text
    assert "sends every supported known managed classification label" in text
    assert "immediately reacquires the created issue and proves those labels persisted" in text
    assert "A successful create response alone is not completion" in text


def test_connected_create_label_mismatch_reuses_existing_reconciler() -> None:
    text = FIXTURES.read_text(encoding="utf-8")

    assert "## Test 24 - Connected Create Label Mismatch Reuses Existing Reconciler" in text
    assert "does not create a second issue or label writer" in text
    assert "Reuses the existing #1962 bounded reconciler once" in text
    assert "preserves unmanaged labels" in text
    assert "rereads to prove convergence" in text
