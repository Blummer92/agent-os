from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STANDARD = ROOT / "01_Shared_Standards" / "typescript-react" / "README.md"
ALIASES = ROOT / "04_Registry" / "navigation-alias-registry.md"
AGENT_REGISTRY = ROOT / "04_Registry" / "agent-inheritance-registry.md"


def test_typescript_react_standard_covers_required_shared_baseline():
    text = STANDARD.read_text(encoding="utf-8")

    required_sections = (
        "## Canonical Contract Boundary",
        "## TypeScript",
        "## React Components And Hooks",
        "## Props, State, Derived State, And Context",
        "## Async Data And Errors",
        "## Forms And Validation",
        "## Accessibility",
        "## Testing",
        "## Dependencies And Versions",
        "## Organization And Naming",
        "## Security And Secrets",
        "## Performance",
        "## Documentation",
        "## Web And Native Extensions",
    )

    for section in required_sections:
        assert section in text

    assert "strict type checking" in text
    assert "loading, empty, error, success, disabled" in text
    assert "must not silently become a second source of truth" in text
    assert "Do not require Next.js, Vite, Expo, React Native" in text
    assert "Accessibility is a first-class implementation requirement" in text
    assert "Avoid snapshot-only proof for interactive behavior" in text


def test_typescript_react_standard_is_discoverable_without_creating_an_agent():
    alias_text = ALIASES.read_text(encoding="utf-8")
    registry_text = AGENT_REGISTRY.read_text(encoding="utf-8")

    assert "### @typescript-react" in alias_text
    assert "01_Shared_Standards/typescript-react/README.md" in alias_text
    assert "Do not infer a framework, production write, or new executable agent" in alias_text

    agent_table = registry_text.split("## Technical Execution Architecture", 1)[0]
    assert "TypeScript + React" not in agent_table
    assert "React Agent" not in agent_table
    assert "JavaScript Agent" not in agent_table
