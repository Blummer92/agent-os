"""Contract tests for the `agent-os-codespaces-v1` profile (#891).

Checks the shape and safety boundaries of the allowlisted files rather than
re-deriving worktree, scheduler, or repository-state behavior.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEVCONTAINER_DIR = ROOT / ".devcontainer"
RUNBOOK = ROOT / "docs" / "AGENT_OS_CODESPACES_RUNBOOK.md"


def test_devcontainer_json_is_valid_and_bounded_to_two_cores() -> None:
    payload = json.loads((DEVCONTAINER_DIR / "devcontainer.json").read_text(encoding="utf-8"))
    assert payload["name"] == "agent-os-codespaces-v1"
    assert payload["hostRequirements"]["cpus"] == 2
    assert payload["build"] == {"dockerfile": "Dockerfile"}
    assert "image" not in payload
    assert payload["workspaceFolder"] == "/workspaces/agent-os"
    assert payload["postCreateCommand"] == "bash .devcontainer/post-create.sh"
    assert payload["remoteEnv"]["AGENT_OS_NETWORK_MODE"] == "local-only"


def test_2307_activates_official_ssh_without_replacing_github_cli() -> None:
    payload = json.loads((DEVCONTAINER_DIR / "devcontainer.json").read_text(encoding="utf-8"))
    features = payload["features"]
    assert "ghcr.io/devcontainers/features/github-cli:1" in features
    assert "ghcr.io/devcontainers/features/sshd:1" in features
    assert features["ghcr.io/devcontainers/features/sshd:1"] == {}


def test_devcontainer_json_contains_no_credentials_or_secrets() -> None:
    text = (DEVCONTAINER_DIR / "devcontainer.json").read_text(encoding="utf-8").lower()
    for forbidden in ("password", "token=", "credential"):
        assert forbidden not in text


def test_2307_reproduced_yarn_failure_has_one_bounded_pre_feature_repair() -> None:
    lines = (DEVCONTAINER_DIR / "Dockerfile").read_text(encoding="utf-8").splitlines()
    instructions = [line for line in lines if line and not line.startswith("#")]
    assert instructions == [
        "FROM mcr.microsoft.com/devcontainers/python:1-3.11-bookworm",
        "RUN rm -f /etc/apt/sources.list.d/yarn.list",
    ]


def test_runbook_documents_bounded_ssh_and_gce_boundary() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    for phrase in (
        "gh codespace ssh",
        "scripts/agent-os-environment-health.py",
        "Closed PR #1215",
        "2026-09-25 creation log",
        "#759 containment",
        "GCE",
        "Non-authorization",
        "rollback",
    ):
        assert phrase in text


def test_runbook_stays_bounded() -> None:
    assert RUNBOOK.exists()
    assert RUNBOOK.read_text(encoding="utf-8").count("\n") < 120
