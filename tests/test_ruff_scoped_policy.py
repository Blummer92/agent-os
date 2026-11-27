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
    outside.write_text("import os\nVALUE = missing_name\n", encoding="utf-8")
    inside.write_text("import os\n", encoding="utf-8")
    command = [sys.executable, "-I", "-m", "ruff", "check", "--no-cache", "--output-format", "json", "."]

    failing = subprocess.run(command, cwd=tmp_path, capture_output=True, check=False)
    assert failing.returncode == 1
    diagnostics = json.loads(failing.stdout)
    assert sorted((item["code"], Path(item["filename"])) for item in diagnostics) == [
        ("F401", inside),
        ("F821", outside),
    ]
    assert inside.read_text(encoding="utf-8") == "import os\n"

    rule_fixture = (
        "import sys\n"
        "import os\n"
        "from typing import List\n"
        "\n"
        "USED = (sys.version, os.name)\n"
        "names: List[str] = []\n"
        "empty = None\n"
        "is_empty = empty == None\n"
        "\n"
        "def mutable_default(values=[]):\n"
        "    return values\n"
        "\n"
        "def boolean_return(value):\n"
        "    if value:\n"
        "        return True\n"
        "    return False\n"
    )
    inside.write_text(rule_fixture, encoding="utf-8")
    outside.write_text(rule_fixture, encoding="utf-8")
    expanded = subprocess.run(command, cwd=tmp_path, capture_output=True, check=False)
    assert expanded.returncode == 1
    found = json.loads(expanded.stdout)
    assert {Path(item["filename"]) for item in found} == {inside}
    assert sorted(item["code"] for item in found) == [
        "B006", "E711", "I001", "SIM103", "UP006", "UP035",
    ]

    outside.write_text("import os\n", encoding="utf-8")
    inside.write_text('MESSAGE = "' + "meaningful words " * 12 + '"\n', encoding="utf-8")
    connector = tmp_path / SCOPE / "connectors" / "base.py"
    connector.parent.mkdir()
    connector.write_text(
        'from enum import Enum\n\n\nclass Code(str, Enum):\n    READY = "ready"\n',
        encoding="utf-8",
    )
    passing = subprocess.run(command, cwd=tmp_path, capture_output=True, check=False)
    assert passing.returncode == 0
    assert json.loads(passing.stdout) == []
