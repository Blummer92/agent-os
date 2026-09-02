from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STANDARD = ROOT / "01_Shared_Standards/github/zero-runtime-connector-native-default.md"


def test_zero_runtime_prefers_connector_native():
    text = STANDARD.read_text()
    assert "required runtime capabilities = empty" in text
    assert "connector-native GitHub route" in text
    assert "Do not invoke the governed runner" in text


def test_runtime_required_work_is_excluded():
    text = STANDARD.read_text()
    for marker in ("Python/TypeScript/JavaScript", "lint/build/compile", "package/build validation"):
        assert marker in text
    assert "remain on the governed runtime path" in text


def test_continuation_reroutes_only_when_connector_is_insufficient():
    text = STANDARD.read_text()
    assert "If the connector becomes insufficient" in text
    assert "#1237/#918 reroute semantics" in text
    assert "Do not silently escalate" in text


def test_zero_runtime_does_not_require_vm_or_dependency_health():
    text = STANDARD.read_text()
    assert "does not require VM health, dependency readiness" in text
    assert "GitHub Service Agent remains the sole repository writer" in text
