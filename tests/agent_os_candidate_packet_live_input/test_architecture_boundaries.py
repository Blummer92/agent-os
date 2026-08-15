"""AOS-AUTO1H architecture-boundary tests for the #1155 live-input package.

Proves, statically, that this package does not acquire execution authority:
no subprocess, no direct network client construction, no credential/IAM
module, and no Scheduler/lease/worktree execution import anywhere in
``scripts/agent_os_candidate_packet_live_input``. All live GitHub access is
required to flow through the caller-injected ``SingleIssueTransport``
Protocol, and the only Git-adjacent input is a caller-supplied
``verify-repo-state.sh`` stdout string this package only parses.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_PACKAGE_DIR = (
    Path(__file__).resolve().parents[2] / "scripts" / "agent_os_candidate_packet_live_input"
)
_MODULES = ("__init__.py", "issue_reader.py", "repository_reader.py", "repository_observation.py")

_FORBIDDEN_MODULE_PREFIXES = (
    "subprocess",
    "socket",
    "urllib",
    "http.client",
    "requests",
    "git",
    "github",
    "google",
    "googleapiclient",
    "notion_client",
    "gcloud",
    "google.cloud",
    "workflow_scheduler.execution.executor",
    "workflow_scheduler.execution.lease",
    "workflow_scheduler.execution.worktree",
)


def _imported_module_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize("filename", _MODULES)
def test_module_imports_no_forbidden_capability(filename: str) -> None:
    imported = _imported_module_names(_PACKAGE_DIR / filename)
    for name in imported:
        for forbidden in _FORBIDDEN_MODULE_PREFIXES:
            assert not name.startswith(forbidden), f"{filename} imports forbidden module {name!r}"


@pytest.mark.parametrize("filename", _MODULES)
def test_module_contains_no_subprocess_or_network_calls(filename: str) -> None:
    source = (_PACKAGE_DIR / filename).read_text(encoding="utf-8")
    for banned in (
        "subprocess.",
        "os.system(",
        "os.popen(",
        "socket.socket",
        "urlopen(",
        "shutil.rmtree",
    ):
        assert banned not in source, f"{filename} contains banned call {banned!r}"


@pytest.mark.parametrize("filename", _MODULES)
def test_module_contains_no_credential_or_execution_authority_literal(filename: str) -> None:
    source = (_PACKAGE_DIR / filename).read_text(encoding="utf-8")
    for banned in ("execution_authorized: bool = True", "execution_authorized=True"):
        assert banned not in source, f"{filename} contains a true execution-authority literal"


def test_package_import_performs_no_io() -> None:
    for filename in _MODULES:
        source = (_PACKAGE_DIR / filename).read_text(encoding="utf-8")
        tree = ast.parse(source)
        module_level_calls = [
            node
            for node in tree.body
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
        ]
        assert module_level_calls == [], f"{filename} executes a call at module scope"


def test_reader_and_evidence_reader_authority_fields_default_false() -> None:
    from scripts.agent_os_candidate_packet_live_input.issue_reader import (
        LiveIssueReader,
        SingleIssueTransportOutcome,
        SingleIssueTransportResult,
    )
    from scripts.agent_os_candidate_packet_live_input.repository_reader import (
        LiveRepositoryEvidenceReader,
    )

    class _Transport:
        def get_issue(self, repository: str, issue_number: int) -> SingleIssueTransportResult:
            return SingleIssueTransportResult(outcome=SingleIssueTransportOutcome.NOT_FOUND)

    assert LiveIssueReader(transport=_Transport()).execution_authorized is False
    assert LiveRepositoryEvidenceReader().execution_authorized is False
