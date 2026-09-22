from pathlib import Path

from scripts.check_duplicate_python_declarations import (
    find_duplicate_top_level_declarations,
    scan_authored_python,
)


def _write(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "sample.py"
    path.write_text(source, encoding="utf-8")
    return path


def test_duplicate_top_level_function_reports_symbol_and_lines(tmp_path):
    path = _write(tmp_path, "def duplicate():\n    pass\n\ndef duplicate():\n    pass\n")
    assert find_duplicate_top_level_declarations(path)[0].symbol == "duplicate"
    assert find_duplicate_top_level_declarations(path)[0].lines == (1, 4)


def test_duplicate_top_level_class_is_rejected(tmp_path):
    path = _write(tmp_path, "class Duplicate:\n    pass\n\nclass Duplicate:\n    pass\n")
    assert find_duplicate_top_level_declarations(path)[0].symbol == "Duplicate"


def test_same_method_name_in_different_classes_is_not_top_level_duplicate(tmp_path):
    path = _write(
        tmp_path,
        "class First:\n    def run(self):\n        pass\n\n"
        "class Second:\n    def run(self):\n        pass\n",
    )
    assert find_duplicate_top_level_declarations(path) == ()


def test_typing_overload_group_is_allowed(tmp_path):
    path = _write(
        tmp_path,
        "from typing import overload\n\n"
        "@overload\ndef parse(value: str) -> str: ...\n"
        "@overload\ndef parse(value: int) -> int: ...\n"
        "def parse(value):\n    return value\n",
    )
    assert find_duplicate_top_level_declarations(path) == ()


def test_conditional_declarations_are_not_misclassified_as_top_level_duplicates(tmp_path):
    path = _write(
        tmp_path,
        "if True:\n    def platform_value():\n        return 1\n"
        "else:\n    def platform_value():\n        return 2\n",
    )
    assert find_duplicate_top_level_declarations(path) == ()


def test_repository_has_no_shadowing_top_level_declarations():
    duplicates = scan_authored_python(Path("."))
    assert duplicates == (), duplicates
