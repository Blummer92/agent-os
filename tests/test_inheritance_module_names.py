from pathlib import Path


def test_no_shorthand_in_inheritance_registry():
    text = Path("04_Registry/agent-inheritance-registry.md").read_text(encoding="utf-8")
    shorthand = [
        "Global,",
        "Source-of-Truth,",
        "Testing/Release",
        ", Python,",
        ", Workspace,",
        ", Notion",
        "QA/Test |",
        "Instructional Design |",
        ", Navigation Registry",
    ]
    assert all(value not in text for value in shorthand)


def test_canonical_names_are_present():
    text = Path("04_Registry/agent-inheritance-registry.md").read_text(encoding="utf-8")
    expected = [
        "Global Engineering",
        "Source-of-Truth Checks",
        "Read-Only Default",
        "Python Standards",
        "Google Workspace Standards",
        "Notion Standards",
        "QA/Test Standards",
        "Dashboard Governance",
        "Instructional Design Standards",
    ]
    assert all(value in text for value in expected)
