import pytest

from scripts.agent_os_issue_acceptance.path_contract import (
    DeclaredPathError,
    declared_path_matches,
    normalize_declared_path,
    normalize_declared_pattern,
)


@pytest.mark.parametrize(
    "value",
    [
        ".github/workflows/agent-os-validation.yml",
        "scripts/agent_os_issue_acceptance/path_contract.py",
        "Docs/Case-Is-Preserved.md",
        "directory/file with spaces.md",
        "single-file.txt",
    ],
)
def test_valid_declared_paths_are_preserved_exactly(value):
    assert normalize_declared_path(value) == value


@pytest.mark.parametrize(
    ("value", "code"),
    [
        ("", "empty"),
        (None, "empty"),
        ("/etc/passwd", "absolute-posix"),
        ("//server/share", "absolute-posix"),
        ("C:/repo/file.txt", "absolute-windows-drive"),
        ("c:\\repo\\file.txt", "absolute-windows-drive"),
        ("\\\\server\\share\\file.txt", "absolute-unc"),
        ("folder\\file.txt", "backslash"),
        ("../production/file.txt", "traversal"),
        ("safe/../production/file.txt", "traversal"),
        ("folder/..", "traversal"),
        ("folder/\x00file.txt", "control-character"),
        ("folder/\x1ffile.txt", "control-character"),
        ("folder/\x7ffile.txt", "control-character"),
        ("./folder/file.txt", "noncanonical-dot-prefix"),
        ("folder//file.txt", "noncanonical-separator"),
        ("folder/./file.txt", "noncanonical-separator"),
        ("folder/", "noncanonical-separator"),
        (".", "noncanonical-separator"),
    ],
)
def test_invalid_declared_paths_raise_stable_codes(value, code):
    with pytest.raises(DeclaredPathError) as caught:
        normalize_declared_path(value)  # type: ignore[arg-type]

    assert caught.value.code == code
    assert caught.value.value == value
    assert str(caught.value) == f"{code}: invalid declared path"


def test_traversal_is_rejected_instead_of_normalized():
    with pytest.raises(DeclaredPathError) as caught:
        normalize_declared_path("docs/../production/config.yml")

    assert caught.value.code == "traversal"


def test_validation_is_deterministic_and_has_no_normalizing_side_effects():
    value = ".github/workflows/check.yml"
    assert normalize_declared_path(value) == normalize_declared_path(value)


@pytest.mark.parametrize(
    "pattern",
    ["production", "src/*.py", ".github/workflows/*.yml"],
)
def test_valid_declared_patterns_are_preserved(pattern):
    assert normalize_declared_pattern(pattern) == pattern


@pytest.mark.parametrize(
    ("pattern", "code"),
    [
        ("src/**/test.py", "unsupported-double-star"),
        ("src/file?.py", "unsupported-question-mark"),
        ("src/[ab].py", "unsupported-bracket-class"),
        ("../src/*.py", "traversal"),
        ("C:/src/*.py", "absolute-windows-drive"),
    ],
)
def test_unsupported_pattern_syntax_has_stable_codes(pattern, code):
    with pytest.raises(DeclaredPathError) as caught:
        normalize_declared_pattern(pattern)

    assert caught.value.code == code


@pytest.mark.parametrize(
    ("path", "pattern", "expected"),
    [
        ("production", "production", True),
        ("production/config/app.yml", "production", True),
        ("production-old/config.yml", "production", False),
        ("src/main.py", "src/*.py", True),
        ("src/main.js", "src/*.py", False),
        ("src/nested/main.py", "src/*.py", False),
        (".github/workflows/check.yml", ".github/workflows/*.yml", True),
    ],
)
def test_declared_path_matching_is_bounded(path, pattern, expected):
    assert declared_path_matches(path, pattern) is expected


def test_declared_path_matching_is_deterministic():
    arguments = ("src/example.py", "src/*.py")
    assert declared_path_matches(*arguments) == declared_path_matches(*arguments)
