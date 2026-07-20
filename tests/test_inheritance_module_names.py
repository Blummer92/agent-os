from pathlib import Path


def _inheritance_tokens() -> list[str]:
    text = Path("04_Registry/agent-inheritance-registry.md").read_text(encoding="utf-8")
    tokens: list[str] = []
    for line in text.splitlines():
        if not line.startswith("|") or line.startswith("|---") or "| Agent |" in line:
            continue
        columns = [column.strip() for column in line.strip("|").split("|")]
        if len(columns) != 3:
            continue
        tokens.extend(token.strip() for token in columns[1].split(","))
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
    module_map = Path("04_Registry/module-version-map.md").read_text(encoding="utf-8")
    canonical = {
        columns[0].strip()
        for line in module_map.splitlines()
        if line.startswith("|")
        for columns in [[column.strip() for column in line.strip("|").split("|")]]
        if len(columns) == 2 and columns[0] not in {"Module", "---"}
    }
    assert set(_inheritance_tokens()).issubset(canonical)
