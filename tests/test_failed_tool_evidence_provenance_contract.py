from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "07_Agent_Tests" / "chatgpt-orchestrator.tests.md"


def test_failed_tool_result_cannot_become_computed_evidence() -> None:
    text = FIXTURES.read_text(encoding="utf-8")

    assert "## Test 44 - Failed Tool Result Cannot Become Computed Evidence" in text
    assert "preserves the computational result as unavailable/failed evidence" in text
    assert "makes zero tool-result-derived quantitative claims" in text
    assert "Intended analysis code or visually plausible values never substitute" in text


def test_canonical_write_preserves_failed_tool_provenance() -> None:
    text = FIXTURES.read_text(encoding="utf-8")

    assert "## Test 45 - Canonical Evidence Write Preserves Tool-Result Provenance" in text
    assert "distinguishes user-supplied evidence, qualitative/model inference" in text
    assert "Exact computed metrics require traceable successful tool output" in text
    assert "Failed-tool-derived values are excluded" in text
