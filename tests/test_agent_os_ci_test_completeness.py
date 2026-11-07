"""Test-selection completeness: the #3816 false-green repair.

PR #3816 proved the authoritative aggregate could go green while the
regression tests for a real defect never ran, because ``pytest.ini``
carried ``--deselect=tests/agent_os_issue_acceptance/test_report.py``.
These tests pin the repair: a per-suite comparison of the candidate's
own collection against an unfiltered reference collected from the same
tree.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.agent_os_ci_test_completeness import (
    check_suite,
    filter_selection_options,
    find_pytest_config,
    main,
    parse_collection_output,
    read_addopts,
    read_discovery_options,
    reference_discovery_overrides,
)

HELPER = Path(__file__).parents[1] / "scripts" / "agent_os_ci_test_completeness.py"


def _write_suite(root: Path, *, ini: str | None = None) -> Path:
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "tests" / "test_report.py").write_text(
        "def test_first():\n    assert True\n\n\n"
        "def test_second():\n    assert True\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_other.py").write_text(
        "def test_other():\n    assert True\n",
        encoding="utf-8",
    )
    if ini is not None:
        (root / "pytest.ini").write_text(ini, encoding="utf-8")
    return root


def _check(root: Path) -> dict:
    return check_suite(sys.executable, root, "root", timeout=120)


# --- selection-option filtering -------------------------------------------


@pytest.mark.parametrize(
    ("addopts", "expected"),
    [
        ("--deselect=tests/test_report.py", ""),
        ("--deselect tests/test_report.py -v", "-v"),
        ("-k 'not test_slow' --tb=short", "--tb=short"),
        ("-kfoo -v", "-v"),
        ("-m 'not slow' -v", "-v"),
        ("--ignore=tests/test_report.py", ""),
        ("--ignore tests/test_report.py -v", "-v"),
        ("--ignore-glob=tests/test_*.py", ""),
        ("-o python_files=test_*.py -v", "-v"),
        ("--override-ini=python_files=test_*.py", ""),
        ("-v --strict-markers --tb=short -ra --continue-on-collection-errors", "-v --strict-markers --tb=short -ra --continue-on-collection-errors"),
        ("--deselect a --deselect b -k c -m d --ignore e --ignore-glob f", ""),
        # Bundled short-option clusters: a selection flag consumes the
        # rest of its cluster as its argument.
        ("-qk 'not test_a' -v", "-q -v"),
        ("-vkfoo -v", "-v -v"),
        ("-qm 'not slow' -v", "-q -v"),
        ("-vo 'addopts=-k foo' -v", "-v -v"),
        # Kept flags keep their argument, attached or separate.
        ("-vp no:cacheprovider -v", "-vp no:cacheprovider -v"),
        ("-ra -v", "-ra -v"),
        ("-W error -v", "-W error -v"),
    ],
)
def test_filter_selection_options_removes_only_selection(addopts: str, expected: str) -> None:
    assert filter_selection_options(addopts) == expected


@pytest.mark.parametrize(
    "option",
    [
        "--collect-only", "--co", "--setup-only", "--setup-plan",
        "--fixtures", "--fixtures-per-test", "--help", "--version",
        "--markers", "-h", "-V", "-qV", "-qh",
    ],
)
def test_filter_rejects_execution_suppressing_addopts(option: str) -> None:
    with pytest.raises(ValueError, match="execution-suppressing"):
        filter_selection_options(f"-q {option}")


def test_filter_selection_options_rejects_unparseable_addopts() -> None:
    with pytest.raises(ValueError, match="addopts cannot be parsed"):
        filter_selection_options("--deselect 'unterminated")


# --- config discovery ------------------------------------------------------


def test_find_config_walks_up_to_parent_ini(tmp_path: Path) -> None:
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = -v\n", encoding="utf-8")
    suite = tmp_path / "pkg" / "tests"
    suite.mkdir(parents=True)
    assert find_pytest_config(tmp_path / "pkg") == tmp_path / "pytest.ini"


def test_find_config_prefers_nearest_ini(tmp_path: Path) -> None:
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = -v\n", encoding="utf-8")
    (tmp_path / "pkg" / "pytest.ini").parent.mkdir(parents=True)
    (tmp_path / "pkg" / "pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
    assert find_pytest_config(tmp_path / "pkg") == tmp_path / "pkg" / "pytest.ini"


def test_find_config_returns_none_without_any_ini(tmp_path: Path) -> None:
    assert find_pytest_config(tmp_path) is None


@pytest.mark.parametrize(
    ("filename", "content", "expected"),
    [
        ("pytest.ini", "[pytest]\naddopts = -v --tb=short\n", "-v --tb=short"),
        ("tox.ini", "[pytest]\naddopts = -v\n", "-v"),
        ("setup.cfg", "[tool:pytest]\naddopts = -v\n", "-v"),
        (
            "pyproject.toml",
            "[tool.pytest.ini_options]\naddopts = \"-v --tb=short\"\n",
            "-v --tb=short",
        ),
        (
            "pyproject.toml",
            "[tool.pytest.ini_options]\naddopts = [\"-v\", \"--tb=short\"]\n",
            "-v --tb=short",
        ),
        ("pytest.ini", "[pytest]\ntestpaths = tests\n", ""),
    ],
)
def test_read_addopts_from_each_config_kind(
    tmp_path: Path, filename: str, content: str, expected: str
) -> None:
    path = tmp_path / filename
    path.write_text(content, encoding="utf-8")
    assert read_addopts(path) == expected


def test_read_addopts_multiline_ini_value(tmp_path: Path) -> None:
    path = tmp_path / "pytest.ini"
    path.write_text(
        "[pytest]\naddopts =\n    -v\n    --deselect=tests/test_report.py\n",
        encoding="utf-8",
    )
    assert filter_selection_options(read_addopts(path)) == "-v"


# --- collection-output parsing --------------------------------------------


def test_parse_nodeid_lines() -> None:
    parsed = parse_collection_output(
        "tests/test_a.py::test_one\n"
        "tests/test_a.py::TestClass::test_two[param]\n"
        "2 tests collected in 0.10s\n"
    )
    assert parsed["nodes"] == {
        "tests/test_a.py::test_one",
        "tests/test_a.py::TestClass::test_two[param]",
    }
    assert parsed["collected"] == 2
    assert parsed["format"] == "nodeids"


def test_parse_tree_format() -> None:
    parsed = parse_collection_output(
        "<Dir suite>\n"
        "  <Package tests>\n"
        "    <Module test_a.py>\n"
        "      <Class TestClass>\n"
        "        <Function test_one>\n"
        "      <Function test_two>\n"
        "2 tests collected in 0.10s\n",
        root_name="suite",
    )
    assert parsed["nodes"] == {
        "tests/test_a.py::TestClass::test_one",
        "tests/test_a.py::test_two",
    }


def test_parse_counts_format() -> None:
    parsed = parse_collection_output("tests/test_a.py: 2\ntests/test_b.py: 1\n\n")
    assert parsed["file_counts"] == {"tests/test_a.py": 2, "tests/test_b.py": 1}
    assert parsed["format"] == "counts"


def test_parse_records_collection_errors() -> None:
    parsed = parse_collection_output(
        "tests/test_a.py::test_one\n"
        "ERROR tests/test_broken.py\n"
        "1 tests collected, 1 errors in 0.10s\n"
    )
    assert parsed["error_files"] == ["tests/test_broken.py"]
    assert parsed["collected"] == 1


def test_parse_empty_collection_reports_zero() -> None:
    """A suite that collects nothing prints "collected 0 items" and a
    "no tests collected" banner, neither of which the old summary
    regex matched -- so an empty suite read as a failed collection
    instead of an empty (complete) one."""
    text = (
        "collecting ... collected 0 items\n"
        "\n"
        "========================= no tests collected in 0.02s ==========================\n"
    )
    inventory = parse_collection_output(text)
    assert inventory["collected"] == 0
    assert inventory["nodes"] == set()
    assert inventory["format"] == "unknown"


# --- end-to-end suite checks (real pytest, tiny synthetic suites) ---------


def test_clean_suite_is_complete(tmp_path: Path) -> None:
    root = _write_suite(tmp_path / "clean", ini="[pytest]\naddopts = -v\n")
    result = _check(root)
    assert result["verdict"] == "COMPLETE", result
    assert result["actual_count"] == result["reference_count"] == 3


def test_3816_deselect_is_incomplete_and_names_the_file(tmp_path: Path) -> None:
    root = _write_suite(
        tmp_path / "deselect",
        ini="[pytest]\naddopts =\n    --continue-on-collection-errors\n"
        "    --deselect=tests/test_report.py\n",
    )
    result = _check(root)
    assert result["verdict"] == "INCOMPLETE", result
    # Collections run with -v, so the receipt names node ids.
    assert result["missing"] == [
        "tests/test_report.py::test_first",
        "tests/test_report.py::test_second",
    ]
    assert result["missing_count"] == 2


def test_keyword_selection_is_incomplete(tmp_path: Path) -> None:
    root = _write_suite(
        tmp_path / "keyword",
        ini="[pytest]\naddopts = -k 'not test_first'\n",
    )
    result = _check(root)
    assert result["verdict"] == "INCOMPLETE", result
    assert result["missing_count"] == 1


def test_ignore_selection_is_incomplete(tmp_path: Path) -> None:
    root = _write_suite(
        tmp_path / "ignored",
        ini="[pytest]\naddopts = --ignore=tests/test_report.py\n",
    )
    result = _check(root)
    assert result["verdict"] == "INCOMPLETE", result
    assert result["missing_count"] == 2


# --- ini-level discovery options (D1) ---------------------------------------


def test_ini_python_files_is_incomplete(tmp_path: Path) -> None:
    root = _write_suite(
        tmp_path / "pyfiles", ini="[pytest]\npython_files = test_other.py\n"
    )
    result = _check(root)
    assert result["verdict"] == "INCOMPLETE", result
    assert result["missing"] == [
        "tests/test_report.py::test_first",
        "tests/test_report.py::test_second",
    ]


def test_ini_python_functions_is_incomplete(tmp_path: Path) -> None:
    root = _write_suite(
        tmp_path / "pyfuncs", ini="[pytest]\npython_functions = check_*\n"
    )
    result = _check(root)
    assert result["verdict"] == "INCOMPLETE", result
    assert result["missing_count"] == 3


def test_ini_python_classes_is_incomplete(tmp_path: Path) -> None:
    root = tmp_path / "pyclasses"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_cls.py").write_text(
        "class TestThing:\n    def test_inside(self):\n        assert True\n\n\n"
        "def test_outside():\n    assert True\n",
        encoding="utf-8",
    )
    (root / "pytest.ini").write_text("[pytest]\npython_classes = NoMatch*\n", encoding="utf-8")
    result = _check(root)
    assert result["verdict"] == "INCOMPLETE", result
    assert result["missing"] == ["tests/test_cls.py::TestThing::test_inside"]


def test_ini_norecursedirs_is_incomplete(tmp_path: Path) -> None:
    root = _write_suite(
        tmp_path / "norecur", ini="[pytest]\nnorecursedirs = sub\n"
    )
    (root / "tests" / "sub").mkdir()
    (root / "tests" / "sub" / "test_sub.py").write_text(
        "def test_sub():\n    assert True\n", encoding="utf-8"
    )
    result = _check(root)
    assert result["verdict"] == "INCOMPLETE", result
    assert result["missing"] == ["tests/sub/test_sub.py::test_sub"]


def test_star_test_py_file_is_caught_by_default_reset(tmp_path: Path) -> None:
    """The reference resets ``python_files`` to pytest's default
    (``test_*.py *_test.py``), so a ``*_test.py`` file the candidate
    config silently excludes is detected as an omission."""
    root = _write_suite(
        tmp_path / "startest", ini="[pytest]\npython_files = test_*.py\n"
    )
    (root / "tests" / "helper_test.py").write_text(
        "def test_helper():\n    assert True\n", encoding="utf-8"
    )
    result = _check(root)
    assert result["verdict"] == "INCOMPLETE", result
    assert result["missing"] == ["tests/helper_test.py::test_helper"]


def test_testpaths_is_neutralized_by_positional_arg(tmp_path: Path) -> None:
    """``testpaths`` is reset in the reference, but the explicit
    ``tests`` positional already makes it inert in both runs, so a
    narrow ``testpaths`` stays COMPLETE -- and the receipt records the
    reset that was applied."""
    root = _write_suite(
        tmp_path / "tpaths", ini="[pytest]\ntestpaths = tests/test_report.py\n"
    )
    result = _check(root)
    assert result["verdict"] == "COMPLETE", result
    assert result["discovery"]["testpaths"]["candidate"] == ["tests/test_report.py"]
    assert result["discovery"]["testpaths"]["reference"] == []


def test_allowlisted_fixtures_exclusion_stays_complete(tmp_path: Path) -> None:
    """The reusable-capability-registry fixtures exclusion is
    allowlisted: the reference keeps ``fixtures`` out of its own
    collection, so the suite stays COMPLETE."""
    root = tmp_path / "registry"
    (root / "tests" / "fixtures" / "validation").mkdir(parents=True)
    (root / "tests" / "test_main.py").write_text(
        "def test_main():\n    assert True\n", encoding="utf-8"
    )
    (root / "tests" / "fixtures" / "validation" / "test_fixture.py").write_text(
        "def test_fixture():\n    assert True\n", encoding="utf-8"
    )
    (root / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\n"
        'norecursedirs = ["fixtures", ".*", "build", "dist", "*.egg", "__pycache__"]\n'
        'testpaths = ["tests"]\n',
        encoding="utf-8",
    )
    result = check_suite(
        sys.executable, root, "08_Tooling/reusable-capability-registry", timeout=120
    )
    assert result["verdict"] == "COMPLETE", result
    assert result["actual_count"] == result["reference_count"] == 1


def test_allowlist_is_per_suite_name(tmp_path: Path) -> None:
    """The same fixtures exclusion on a suite that is NOT allowlisted
    is detected as an omission: the reference (pytest default) collects
    the fixture test the candidate excludes, so the verdict is
    INCOMPLETE -- which is what proves the allowlist is load-bearing
    for the registry suite."""
    root = tmp_path / "registry-other"
    (root / "tests" / "fixtures" / "validation").mkdir(parents=True)
    (root / "tests" / "test_main.py").write_text(
        "def test_main():\n    assert True\n", encoding="utf-8"
    )
    (root / "tests" / "fixtures" / "validation" / "test_fixture.py").write_text(
        "def test_fixture():\n    assert True\n", encoding="utf-8"
    )
    (root / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\n"
        'norecursedirs = ["fixtures", ".*", "build", "dist", "*.egg", "__pycache__"]\n'
        'testpaths = ["tests"]\n',
        encoding="utf-8",
    )
    result = check_suite(sys.executable, root, "root", timeout=120)
    assert result["verdict"] == "INCOMPLETE", result
    assert result["missing"] == [
        "tests/fixtures/validation/test_fixture.py::test_fixture"
    ]


def test_reference_discovery_overrides_reset_to_defaults(tmp_path: Path) -> None:
    path = tmp_path / "pytest.ini"
    path.write_text(
        "[pytest]\npython_files = test_other.py\nnorecursedirs = sub\n", encoding="utf-8"
    )
    overrides, detail = reference_discovery_overrides(path, "root")
    assert "python_files=test_*.py *_test.py" in overrides
    assert "norecursedirs=.* build dist CVS _darcs {arch} *.egg" in overrides
    assert detail["python_files"]["candidate"] == ["test_other.py"]
    assert detail["python_files"]["reference"] == ["test_*.py", "*_test.py"]
    assert read_discovery_options(path) == {
        "python_files": ["test_other.py"],
        "norecursedirs": ["sub"],
    }


def test_legitimate_removal_and_rename_stay_complete(tmp_path: Path) -> None:
    root = _write_suite(tmp_path / "legit", ini="[pytest]\naddopts = -v\n")
    assert _check(root)["verdict"] == "COMPLETE"
    (root / "tests" / "test_other.py").unlink()
    (root / "tests" / "test_report.py").write_text(
        "def test_renamed():\n    assert True\n\n\n"
        "def test_second():\n    assert True\n",
        encoding="utf-8",
    )
    result = _check(root)
    assert result["verdict"] == "COMPLETE", result
    assert result["actual_count"] == result["reference_count"] == 2


def test_skipped_tests_stay_complete(tmp_path: Path) -> None:
    root = _write_suite(tmp_path / "skipped", ini="[pytest]\naddopts = -v\n")
    (root / "tests" / "test_other.py").write_text(
        "import pytest\n\n\n@pytest.mark.skip(reason='not applicable here')\n"
        "def test_other():\n    assert True\n",
        encoding="utf-8",
    )
    result = _check(root)
    assert result["verdict"] == "COMPLETE", result


def test_ignored_collection_error_module_is_incomplete(tmp_path: Path) -> None:
    root = _write_suite(
        tmp_path / "excluded-broken",
        ini="[pytest]\naddopts = --ignore=tests/test_broken.py\n",
    )
    (root / "tests" / "test_broken.py").write_text(
        "def broken(:\n", encoding="utf-8"
    )
    result = _check(root)
    assert result["verdict"] == "INCOMPLETE", result
    assert result["missing_error_files"] == ["tests/test_broken.py"]
    assert result["actual_error_files"] == []
    assert result["reference_error_files"] == ["tests/test_broken.py"]
    assert result["missing_count"] == 0  # the broken file never had a node


def test_norecursedirs_cannot_hide_collection_error(tmp_path: Path) -> None:
    root = _write_suite(
        tmp_path / "excluded-subdir", ini="[pytest]\nnorecursedirs = hidden\n"
    )
    hidden = root / "tests" / "hidden"
    hidden.mkdir()
    (hidden / "test_broken.py").write_text(
        "def broken(:\n", encoding="utf-8"
    )
    result = _check(root)
    assert result["verdict"] == "INCOMPLETE", result
    assert result["missing_error_files"] == ["tests/hidden/test_broken.py"]


def test_execution_suppressing_config_is_error(tmp_path: Path) -> None:
    root = _write_suite(
        tmp_path / "collect-only", ini="[pytest]\naddopts = --collect-only\n"
    )
    result = _check(root)
    assert result["verdict"] == "ERROR", result
    assert "execution-suppressing" in result["error"]


def test_collection_error_module_is_tolerated_identically(tmp_path: Path) -> None:
    root = _write_suite(tmp_path / "broken", ini="[pytest]\naddopts = -v\n")
    (root / "tests" / "test_broken.py").write_text("def broken(:\n", encoding="utf-8")
    result = _check(root)
    assert result["verdict"] == "COMPLETE", result
    assert result["actual_error_files"] == result["reference_error_files"] == [
        "tests/test_broken.py"
    ]


def test_regenerated_parameter_values_are_paired_not_missing(tmp_path: Path) -> None:
    """A test parametrized over an import-time random secret (the
    tests/teacher_os_web pattern) collects different node ids on every
    run; that regeneration must not read as an omission."""
    root = _write_suite(tmp_path / "random", ini="[pytest]\naddopts = -v\n")
    (root / "tests" / "test_random.py").write_text(
        "import secrets\n"
        "import pytest\n\n\n"
        "SECRET = secrets.token_urlsafe(8)\n\n\n"
        "@pytest.mark.parametrize('auth', [f'Basic {SECRET}', f'Bearer {SECRET}'])\n"
        "def test_auth(auth):\n    assert auth\n",
        encoding="utf-8",
    )
    result = _check(root)
    assert result["verdict"] == "COMPLETE", result
    assert result["regenerated_param_count"] == 2
    assert result["regenerated_param_bases"] == [
        "tests/test_random.py::test_auth"
    ]


def test_regenerated_params_paired_without_verbose_addopts(tmp_path: Path) -> None:
    """The same regeneration pairing must hold for suites whose
    ``addopts`` has no ``-v``: both collections run with ``-v``
    appended, so they print node ids (not per-file counts) and the
    pairing applies uniformly."""
    root = _write_suite(
        tmp_path / "randomq",
        ini="[pytest]\naddopts = --continue-on-collection-errors\n",
    )
    (root / "tests" / "test_random.py").write_text(
        "import secrets\n"
        "import pytest\n\n\n"
        "SECRET = secrets.token_urlsafe(8)\n\n\n"
        "@pytest.mark.parametrize('auth', [f'Basic {SECRET}', f'Bearer {SECRET}'])\n"
        "def test_auth(auth):\n    assert auth\n",
        encoding="utf-8",
    )
    result = _check(root)
    assert result["verdict"] == "COMPLETE", result
    assert result["actual_format"] in ("tree", "nodeids")
    assert result["reference_format"] in ("tree", "nodeids")
    assert result["regenerated_param_count"] == 2


def test_pair_regenerated_keeps_unpaired_omission() -> None:
    from scripts.agent_os_ci_test_completeness import _pair_regenerated

    unpaired_missing, unpaired_extra, bases = _pair_regenerated(
        ["tests/a.py::test_x[aaa]", "tests/a.py::test_y[bbb]"],
        ["tests/a.py::test_x[ccc]"],
    )
    assert unpaired_missing == ["tests/a.py::test_y[bbb]"]
    assert unpaired_extra == []
    assert bases == ["tests/a.py::test_x"]


def test_mixed_formats_compare_by_file_counts() -> None:
    """When the two runs print in different formats (different
    verbosity), the comparison normalizes node ids to per-file counts
    instead of mistaking an empty count map for an omission."""
    from scripts.agent_os_ci_test_completeness import _as_counts, _compare_counts, _receipt

    node_inv = {
        "nodes": {"tests/a.py::test_one", "tests/a.py::test_two", "tests/b.py::test_x"},
        "file_counts": {},
    }
    count_inv = {"nodes": set(), "file_counts": {"tests/a.py": 2, "tests/b.py": 1}}
    base = _receipt(suite_name="root", suite_dir=Path("."), verdict="COMPLETE", config_path=None)
    result = _compare_counts(base, _as_counts(node_inv), _as_counts(count_inv))
    assert result["verdict"] == "COMPLETE", result
    assert result["actual_count"] == result["reference_count"] == 3

    short_inv = {"nodes": {"tests/a.py::test_one"}, "file_counts": {}}
    base = _receipt(suite_name="root", suite_dir=Path("."), verdict="COMPLETE", config_path=None)
    result = _compare_counts(base, _as_counts(short_inv), _as_counts(count_inv))
    assert result["verdict"] == "INCOMPLETE", result
    assert result["missing_files"] == {
        "tests/a.py": {"reference": 2, "actual": 1},
        "tests/b.py": {"reference": 1, "actual": 0},
    }


def test_parse_tree_format_uses_config_root_name() -> None:
    """The tree format's top <Dir> is the pytest rootdir -- the
    governing config's directory -- so a suite governed by an ancestor
    config reconstructs node ids relative to that root, not to the
    suite directory."""
    text = (
        "<Dir agent-os-main>\n"
        "  <Dir 08_Tooling>\n"
        "    <Dir agent-os-execution-service>\n"
        "      <Dir tests>\n"
        "        <Module test_x.py>\n"
        "          <Function test_one>\n"
    )
    inventory = parse_collection_output(text, root_name="agent-os-main")
    assert inventory["nodes"] == {
        "08_Tooling/agent-os-execution-service/tests/test_x.py::test_one"
    }


def test_parse_tree_format_handles_testcase_and_lambda_params() -> None:
    """The tree parser must reconstruct the same node ids as the flat
    format for ``unittest`` cases (``<UnitTestCase>`` /
    ``<TestCaseFunction>``) and for parametrized names containing
    ``>`` (``test_x[<lambda>0]``). A ``[^>]+`` capture truncates the
    latter, and ignoring the former drops the class segment -- either
    way a deselected test of that kind would be invisible to the
    check. A parametrized name containing a ``.py::`` fragment must
    also not match as a flat node id (the raw ``<Function ...>`` line
    would otherwise be stored verbatim)."""
    text = (
        "<Dir suite>\n"
        "  <Dir tests>\n"
        "    <Module test_a.py>\n"
        "      <Function test_plain>\n"
        "      <Function test_param[<lambda>0]>\n"
        "      <Function test_param[<lambda>1]>\n"
        "      <Function test_m02[pytest tests/test_x.py::test_waived_case]>\n"
        "      <UnitTestCase ContractTests>\n"
        "        <TestCaseFunction test_contract_one>\n"
        "        <TestCaseFunction test_contract_two>\n"
        "      <Class TestThing>\n"
        "        <Function test_in_class>\n"
    )
    inventory = parse_collection_output(text, root_name="suite")
    assert inventory["nodes"] == {
        "tests/test_a.py::test_plain",
        "tests/test_a.py::test_param[<lambda>0]",
        "tests/test_a.py::test_param[<lambda>1]",
        "tests/test_a.py::test_m02[pytest tests/test_x.py::test_waived_case]",
        "tests/test_a.py::ContractTests::test_contract_one",
        "tests/test_a.py::ContractTests::test_contract_two",
        "tests/test_a.py::TestThing::test_in_class",
    }


def test_no_config_file_is_complete(tmp_path: Path) -> None:
    root = _write_suite(tmp_path / "noconfig")
    assert _check(root)["verdict"] == "COMPLETE"


# --- environment and malformed configs (C1, C2) ----------------------------


def test_pytest_addopts_env_is_scrubbed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``PYTEST_ADDOPTS`` applies to both collections identically, so
    without scrubbing it an env ``--deselect`` would be an invisible
    narrowing. The scrubbed run collects the deselected file, which
    the count proves."""
    root = _write_suite(tmp_path / "env", ini="[pytest]\naddopts = -v\n")
    monkeypatch.setenv("PYTEST_ADDOPTS", "--deselect=tests/test_report.py")
    result = _check(root)
    assert result["verdict"] == "COMPLETE", result
    assert result["actual_count"] == 3


def test_pyproject_non_table_pytest_is_error_not_a_crash(tmp_path: Path) -> None:
    """``[tool] pytest = "not-a-table"`` is valid TOML but no pytest
    config, and pytest itself crashes on it at startup -- so the
    helper must not crash with its own traceback either: it walks
    past the file (no config found) and fails closed as ERROR because
    neither collection could produce an inventory."""
    (tmp_path / "pyproject.toml").write_text(
        '[tool]\npytest = "not-a-table"\n', encoding="utf-8"
    )
    root = _write_suite(tmp_path / "badtool")
    result = _check(root)
    assert result["verdict"] == "ERROR", result
    assert result["config_path"] is None
    assert result["error"]


def test_malformed_toml_is_error_not_crash(tmp_path: Path) -> None:
    """A syntactically invalid ``pyproject.toml`` fails closed as
    ERROR (the reference cannot be established), not as a traceback
    misclassified as an omission."""
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options\naddopts = ", encoding="utf-8"
    )
    root = _write_suite(tmp_path / "badtoml")
    result = _check(root)
    assert result["verdict"] == "ERROR", result
    assert result["error"]


def test_malformed_ini_is_error_not_crash(tmp_path: Path) -> None:
    root = _write_suite(tmp_path / "badini")
    (root / "pytest.ini").write_text("this is not ini\n", encoding="utf-8")
    result = _check(root)
    assert result["verdict"] == "ERROR", result
    assert result["error"]


# --- CLI --------------------------------------------------------------------


def test_cli_exit_codes(tmp_path: Path) -> None:
    clean = _write_suite(tmp_path / "clean", ini="[pytest]\naddopts = -v\n")
    receipt = tmp_path / "receipt.json"
    proc = subprocess.run(
        [sys.executable, str(HELPER), "--suite-dir", str(clean), "--suite-name", "root",
         "--python-bin", sys.executable, "--receipt", str(receipt)],
        text=True, capture_output=True, check=False, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(receipt.read_text(encoding="utf-8"))["verdict"] == "COMPLETE"

    bad = _write_suite(
        tmp_path / "bad",
        ini="[pytest]\naddopts = --deselect=tests/test_report.py\n",
    )
    proc = subprocess.run(
        [sys.executable, str(HELPER), "--suite-dir", str(bad), "--suite-name", "root",
         "--python-bin", sys.executable],
        text=True, capture_output=True, check=False, timeout=120,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["verdict"] == "INCOMPLETE"


def test_main_rejects_missing_pytest(tmp_path: Path) -> None:
    root = _write_suite(tmp_path / "nopytest")
    assert main(["--suite-dir", str(root), "--suite-name", "root",
                 "--python-bin", "/nonexistent/python"]) == 2
