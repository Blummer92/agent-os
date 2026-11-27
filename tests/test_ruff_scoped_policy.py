"""Contract for scoped Ruff lint under the existing aggregate command."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCOPE = Path("src/navigation_registry")


def test_ruff_policy_expands_lint_only_inside_the_pilot(tmp_path: Path) -> None:
    pin = f"ruff=={version('ruff')}"
    assert pin in (ROOT / "requirements-dev.txt").read_text().splitlines()

    (tmp_path / SCOPE).mkdir(parents=True)
    shutil.copyfile(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    shutil.copyfile(ROOT / SCOPE / "ruff.toml", tmp_path / SCOPE / "ruff.toml")
    outside = tmp_path / "outside.py"
    inside = tmp_path / SCOPE / "inside.py"
    outside.write_text("import os\n", encoding="utf-8")
    inside.write_text("import os\n", encoding="utf-8")
    command = [sys.executable, "-I", "-m", "ruff", "check", "--no-cache", "--output-format", "json", "."]

    failing = subprocess.run(command, cwd=tmp_path, capture_output=True, check=False)
    assert failing.returncode == 1
    diagnostics = json.loads(failing.stdout)
    assert [(item["code"], Path(item["filename"])) for item in diagnostics] == [
        ("F401", inside),
    ]
    assert inside.read_text(encoding="utf-8") == "import os\n"

    inside.write_text("VALUE = 1\n", encoding="utf-8")
    outside.write_text("VALUE = missing_name\n", encoding="utf-8")
    required = subprocess.run(command, cwd=tmp_path, capture_output=True, check=False)
    assert required.returncode == 1
    assert [(item["code"], Path(item["filename"])) for item in json.loads(required.stdout)] == [
        ("F821", outside),
    ]

    outside.write_text("import os\n", encoding="utf-8")
    passing = subprocess.run(command, cwd=tmp_path, capture_output=True, check=False)
    assert passing.returncode == 0
    assert json.loads(passing.stdout) == []
