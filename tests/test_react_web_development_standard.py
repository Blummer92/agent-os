from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STANDARD = ROOT / "01_Shared_Standards/global-engineering/react-web-development.md"
INDEX = ROOT / "01_Shared_Standards/global-engineering/README.md"


def test_react_web_standard_is_registered_and_extends_shared_standard():
    standard = STANDARD.read_text(encoding="utf-8")
    index = INDEX.read_text(encoding="utf-8")

    assert "react-web-development.md" in index
    assert "typescript-react-development.md" in standard
    assert "extends `typescript-react-development.md`" in standard


def test_react_web_standard_covers_web_specific_acceptance_contract():
    standard = STANDARD.read_text(encoding="utf-8")

    required_sections = (
        "## Semantic web structure",
        "## CSS and responsive layout",
        "## Keyboard, focus, and interaction",
        "## Accessibility acceptance",
        "## Forms and browser-native behavior",
        "## Routing and navigation",
        "## Rendering and framework selection",
        "## Progressive enhancement and browser compatibility",
        "## Performance",
        "## Metadata and SEO",
        "## Browser security boundary",
        "## User-visible and offline states",
        "## Testing and browser acceptance",
        "## Web versus shared/native decision rule",
    )
    for section in required_sections:
        assert section in standard

    assert "Do not choose Next.js, Vite, or another framework globally" in standard
    assert "React Native Web remains an option" in standard
    assert "keyboard-only completion" in standard
    assert "representative narrow, medium, and wide viewport classes" in standard
    assert "Do not claim WCAG conformance from automated checks alone" in standard
    assert "dangerouslySetInnerHTML" in standard
