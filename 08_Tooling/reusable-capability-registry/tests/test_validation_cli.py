"""Process-contract tests for the JSON-only validation CLI (#494 / #254)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from reusable_capability_registry import validation_cli

CLEAN = Path(__file__).parent / "fixtures" / "validation" / "repositories" / "clean"

_INHERIT = "| Agent | Inherits | Overlay |\n|---|---|---|\n| Integration Manager | X | integration-manager |\n"


def _mini_repo(root: Path, *, owner="Integration Manager", mod="def run(v):\n    return v + 1\n") -> Path:
    cap = {
        "capability_id": "widget", "name": "W", "summary": "s", "status": "active",
        "canonical_paths": ["src/pkg/mod.py"], "public_interfaces": ["src.pkg.mod:run"],
        "owner_agent": owner, "known_consumers": ["src/pkg/consumer.py"], "tests": ["test_pkg.py"],
        "keywords": ["w"], "reuse_guidance": "reuse", "side_effects": ["none"],
    }
    files = {
        "04_Registry/reusable-capabilities.yml": yaml.safe_dump({"registry_version": "0.1.0", "capabilities": [cap]}, sort_keys=False),
        "04_Registry/agent-inheritance-registry.md": _INHERIT,
        "02_Agent_Overlays/integration-manager.md": "o\n",
        "src/pkg/mod.py": mod,
        "src/pkg/consumer.py": "from src.pkg.mod import run\n\n\ndef c():\n    return run(1)\n",
        "test_pkg.py": "from src.pkg.mod import run\n\n\ndef test_a():\n    assert run(1) == 2\n",
    }
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


def test_help_states_report_only(capsys):
    with pytest.raises(SystemExit) as exc:
        validation_cli.main(["--help"])
    assert exc.value.code == 0
    assert "report-only" in capsys.readouterr().out


def test_pass_report_exit_zero_json_stdout(capsys):
    code = validation_cli.main(["--repository-root", str(CLEAN)])
    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["summary"]["severity"] == "pass"
    assert captured.out.endswith("\n") and captured.out.count("\n") == 1


def test_fail_report_exit_one(tmp_path, capsys):
    _mini_repo(tmp_path, owner="Nonexistent Agent")
    code = validation_cli.main(["--repository-root", str(tmp_path)])
    captured = capsys.readouterr()
    assert code == 1
    assert json.loads(captured.out)["summary"]["severity"] == "fail"
    assert captured.err == ""


def test_manual_review_report_exit_two_with_json(tmp_path, capsys):
    _mini_repo(tmp_path, mod="from other import *\n")  # star import -> interface.dynamic-export (manual-review)
    code = validation_cli.main(["--repository-root", str(tmp_path)])
    captured = capsys.readouterr()
    assert code == 2
    assert json.loads(captured.out)["summary"]["severity"] == "manual-review"
    assert captured.err == ""


def test_argparse_misuse_exit_two_stderr_only(capsys):
    with pytest.raises(SystemExit) as exc:
        validation_cli.main(["--format", "xml"])
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "usage" in captured.err.lower()


def test_unexpected_execution_error_exit_three(tmp_path, capsys):
    missing = tmp_path / "does-not-exist"
    code = validation_cli.main(["--repository-root", str(missing)])
    captured = capsys.readouterr()
    assert code == 3
    assert captured.out == ""
    assert captured.err.strip() == "execution error: validation could not complete"


def test_malformed_registry_reports_fail_not_execution_error(tmp_path, capsys):
    _mini_repo(tmp_path)
    (tmp_path / "04_Registry" / "reusable-capabilities.yml").write_text("capabilities: [oops\n", encoding="utf-8")
    code = validation_cli.main(["--repository-root", str(tmp_path)])
    captured = capsys.readouterr()
    assert code == 1  # deterministic fail report, not exit 3
    payload = json.loads(captured.out)
    assert payload["summary"]["severity"] == "fail"
    assert payload["provenance"] is None
