from pathlib import Path


def _inheritance_tokens() -> list[str]:
    text = Path("04_Registry/agent-inheritance-registry.md").read_text(encoding="utf-8")
    first_section = text.split("## Legacy Alias Resolution", 1)[0]
    tokens: list[str] = []
    for line in first_section.splitlines():
        if not line.startswith("|") or line.startswith("|---") or "| Agent |" in line:
            continue
        columns = [part.strip() for part in line.strip("|").split("|")]
        if len(columns) == 3:
            tokens.extend(part.strip() for part in columns[1].split(","))
    return tokens


def test_no_shorthand_in_inheritance_registry():
    shorthand = {
        "Global",
        "Source-of-Truth",
        "Testing/Release",
        "Python",
        "Workspace",
        "Notion",
        "QA/Test",
        "Instructional Design",
        "Navigation Registry",
    }
    assert shorthand.isdisjoint(_inheritance_tokens())


def test_inheritance_tokens_are_canonical_modules():
    text = Path("04_Registry/module-version-map.md").read_text(encoding="utf-8")
    canonical = set()
    for line in text.splitlines():
        if not line.startswith("|") or line.startswith("|---") or "| Module |" in line:
            continue
        columns = [part.strip() for part in line.strip("|").split("|")]
        if len(columns) == 2:
            canonical.add(columns[0])
    assert set(_inheritance_tokens()).issubset(canonical)
