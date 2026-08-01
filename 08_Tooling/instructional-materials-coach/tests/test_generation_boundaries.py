"""Governance invariants from ADR-0004.

Dependency-free on purpose: these run whether or not the `genai` extra is
installed, so the governance guarantees are never skipped in CI.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SRC = PACKAGE_ROOT / "src" / "instructional_materials_coach"

# Only the generation layer. The pre-existing coach modules (drive_client,
# lesson_record, cli) legitimately write files and predate this work.
GENERATION_MODULES = (
    SRC / "genai_client.py",
    SRC / "content_schema.py",
    SRC / "notion_ingest.py",
    SRC / "tools.py",
    SRC / "colab" / "bootstrap.py",
    SRC / "colab" / "run_lesson_build.py",
)

# Fields that carry governance meaning. A draft schema must not contain them,
# because a model must never be able to propose a value for one.
GOVERNED_FIELD_TOKENS = (
    "readiness",
    "approval",
    "approved",
    "ownership",
    "owner",
    "source_of_truth",
    "sign_off",
    "acceptance",
)


def _schema_field_names() -> list[str]:
    """Field names declared in content_schema.py, parsed without pydantic."""
    tree = ast.parse((SRC / "content_schema.py").read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            names.extend(
                stmt.target.id
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
            )
    return names


def test_draft_exposes_no_readiness_or_approval_field():
    """Model output cannot propose a readiness or approval value."""
    for field in _schema_field_names():
        lowered = field.lower()
        for token in GOVERNED_FIELD_TOKENS:
            assert token not in lowered, (
                f"draft schema field {field!r} looks governed ({token!r}); a model must not "
                "be able to propose readiness, approval, or ownership values"
            )


def test_generation_package_writes_only_through_the_draft_writer():
    """Repository scope only.

    Proves the only filesystem write in the package is `write_draft`, which
    takes a caller-supplied path. It does NOT prove runtime non-mutation of
    external systems -- that guarantee comes from declaration-only tools and
    the read-only registry, tested in test_tool_authorization.py.

    Citations of governed paths in docstrings are expected and allowed; what
    matters is that nothing writes to them.
    """
    write_calls: list[str] = []
    for path in GENERATION_MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if name in {"write_text", "write_bytes", "mkdir"}:
                write_calls.append(f"{path.name}:{name}")
            elif name == "open":
                mode = next(
                    (a.value for a in node.args[1:2] if isinstance(a, ast.Constant)), "r"
                )
                if "w" in str(mode) or "a" in str(mode):
                    write_calls.append(f"{path.name}:open({mode})")

    unexpected = [c for c in write_calls if not c.startswith("run_lesson_build.py")]
    assert not unexpected, f"unexpected filesystem writes in the generation package: {unexpected}"


def test_draft_output_is_marked_draft_and_not_evidence():
    """Written drafts carry a banner; nothing claims validation evidence."""
    runner = (SRC / "colab" / "run_lesson_build.py").read_text(encoding="utf-8")
    assert "DRAFT" in runner
    assert "requires human review" in runner
    for banned in ("acceptance evidence", "validation evidence", "approved artifact"):
        assert f'"{banned}"' not in runner


def test_adr_0004_states_the_draft_only_boundary():
    adr = (
        PACKAGE_ROOT.parents[1]
        / "00_Governance"
        / "architecture-decisions"
        / "adr-0004-model-invocation-boundary.md"
    ).read_text(encoding="utf-8")
    assert "always draft content" in adr
    assert "cannot be used as validation evidence" in adr
    assert "grants no additional write authority" in adr


def test_offline_suites_import_without_genai_extra():
    """Every dependency-free module imports with the extra unavailable.

    Runs in a subprocess with google.genai and pydantic blocked, proving the
    offline validation lane cannot be broken by the optional dependency.
    """
    script = """
import sys

class Blocker:
    def find_module(self, name, path=None):
        if name.split('.')[0] in {'google', 'pydantic'}:
            return self
        return None
    def load_module(self, name):
        raise ImportError(f'blocked: {name}')

sys.meta_path.insert(0, Blocker())
import instructional_materials_coach.content_spec  # noqa: F401
import instructional_materials_coach.notion_ingest  # noqa: F401
print('OK')
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PACKAGE_ROOT,
        env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_notion_ingest_needs_no_network_dependency():
    """HTTP is injected, so ingest adds no network dependency to the package."""
    source = (SRC / "notion_ingest.py").read_text(encoding="utf-8")
    for banned in ("import requests", "import httpx", "urllib.request", "http.client"):
        assert banned not in source
