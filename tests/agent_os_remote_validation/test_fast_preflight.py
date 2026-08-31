from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).parents[2] / "scripts" / "agent-os-fast-preflight.py"
SPEC = importlib.util.spec_from_file_location("agent_os_fast_preflight", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
run_fast_preflight = MODULE.run_fast_preflight


def test_valid_mechanical_inputs_pass_and_aggregate_remains_required(tmp_path: Path) -> None:
    (tmp_path / "good.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "good.json").write_text('{"ok": true}\n', encoding="utf-8")
    (tmp_path / "good.yaml").write_text("ok: true\n", encoding="utf-8")

    result = run_fast_preflight(
        repo_root=tmp_path,
        changed_files=("good.yaml", "good.py", "good.json"),
    )

    assert result.passed is True
    assert [check.kind for check in result.checks] == [
        "json-parse",
        "python-compile",
        "yaml-parse",
    ]
    assert result.aggregate_required is True
    assert result.validation_authorized is False
    assert result.merge_authorized is False
    assert result.closure_authorized is False
    assert result.production_authorized is False
    assert result.external_write_authorized is False


def test_malformed_python_json_and_yaml_fail_with_actionable_kind(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text("if True print('bad')\n", encoding="utf-8")
    (tmp_path / "bad.json").write_text('{"broken": }\n', encoding="utf-8")
    (tmp_path / "bad.yaml").write_text("key: [unterminated\n", encoding="utf-8")

    result = run_fast_preflight(
        repo_root=tmp_path,
        changed_files=("bad.py", "bad.json", "bad.yaml"),
    )

    assert result.passed is False
    assert {check.kind for check in result.checks} == {
        "python-compile",
        "json-parse",
        "yaml-parse",
    }
    assert all(check.status == "failed" for check in result.checks)
    assert result.aggregate_required is True


def test_irrelevant_files_are_skipped_without_triggering_pytest_or_other_work(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# docs\n", encoding="utf-8")

    result = run_fast_preflight(repo_root=tmp_path, changed_files=("README.md",))

    assert result.passed is True
    assert len(result.checks) == 1
    assert result.checks[0].kind is None
    assert result.checks[0].status == "skipped"
    assert result.checks[0].reason == "no-admitted-cheap-check"


def test_input_order_and_duplicates_do_not_change_result_identity(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("a = 1\n", encoding="utf-8")
    (tmp_path / "b.json").write_text('{"b": 2}\n', encoding="utf-8")

    first = run_fast_preflight(
        repo_root=tmp_path,
        changed_files=("b.json", "a.py", "b.json"),
    )
    second = run_fast_preflight(
        repo_root=tmp_path,
        changed_files=("a.py", "b.json"),
    )

    assert first.to_dict() == second.to_dict()


def test_missing_admitted_file_fails_closed(tmp_path: Path) -> None:
    result = run_fast_preflight(repo_root=tmp_path, changed_files=("missing.py",))

    assert result.passed is False
    assert result.checks[0].kind == "python-compile"
    assert result.checks[0].reason == "changed-file-missing"


def test_repository_escape_is_rejected_before_file_access(tmp_path: Path) -> None:
    try:
        run_fast_preflight(repo_root=tmp_path, changed_files=("../outside.py",))
    except ValueError as exc:
        assert "inside the repository" in str(exc)
    else:
        raise AssertionError("repository escape must fail closed")
