from __future__ import annotations

import ast
from pathlib import Path

import pytest

from scripts.agent_os_github_issue_provider.auth import build_token_client


ROOT = Path(__file__).resolve().parents[2]


def test_token_client_fails_closed_without_existing_token_convention():
    for environment in ({}, {"GITHUB_TOKEN": "  "}, {"GH_TOKEN": ""}):
        with pytest.raises(RuntimeError, match="GITHUB_TOKEN or GH_TOKEN"):
            build_token_client(environment)


def test_token_client_prefers_github_token_and_does_not_expose_token_in_repr():
    token = "ghp_example_secret_value"
    client = build_token_client(
        {"GITHUB_TOKEN": token, "GH_TOKEN": "ignored"},
        user_agent="agent-os-test/1",
    )
    assert token not in repr(client)
    assert hasattr(client, "requester")


def test_selected_token_backed_callers_have_one_client_construction_owner():
    callers = (
        ROOT / "scripts/agent_os_github_git_objects/cli.py",
        ROOT / "scripts/agent_os_issue_labels/pr_branch_refresh_operator.py",
        ROOT
        / "08_Tooling/agent-os-execution-service/src/agent_os_execution_service/host_github_read_transport.py",
    )
    for path in callers:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert "build_token_client" in imported, path
        assert "Auth" not in imported, path
        assert "Github" not in imported, path
