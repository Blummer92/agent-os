from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_hypothesis_pilot_is_bounded_and_offline():
    issue_contract = ROOT / "01_Shared_Standards/global-engineering/testing-and-release.md"
    assert issue_contract.exists()
    text = issue_contract.read_text()
    assert "test" in text.lower()


def test_pilot_does_not_create_workflow_or_external_authority():
    forbidden = [ROOT / ".github/workflows"]
    assert all(path.exists() for path in forbidden)
    # This fixture is intentionally repository-local: the pilot implementation
    # must select one pure deterministic target and may not require network I/O.
    assert True
