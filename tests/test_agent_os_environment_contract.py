"""Focused contract tests for the `agent-os-codespaces-v1` profile."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEVCONTAINER = ROOT / ".devcontainer" / "devcontainer.json"
RUNBOOK = ROOT / "docs" / "AGENT_OS_CODESPACES_RUNBOOK.md"


def _profile() -> dict:
    return json.loads(DEVCONTAINER.read_text(encoding="utf-8"))


def test_profile_preserves_existing_runtime_contract() -> None:
    payload = _profile()
    assert payload["name"] == "agent-os-codespaces-v1"
    assert payload["hostRequirements"]["cpus"] == 2
    assert payload["image"] == "mcr.microsoft.com/devcontainers/python:1-3.11-bookworm"
    assert payload["workspaceFolder"] == "/workspaces/agent-os"
    assert payload["postCreateCommand"] == "bash .devcontainer/post-create.sh"
    assert payload["remoteEnv"]["AGENT_OS_NETWORK_MODE"] == "local-only"


def test_2307_activates_official_ssh_without_replacing_github_cli() -> None:
    features = _profile()["features"]
    assert "ghcr.io/devcontainers/features/github-cli:1" in features
    assert "ghcr.io/devcontainers/features/sshd:1" in features
    assert features["ghcr.io/devcontainers/features/sshd:1"] == {}


def test_profile_contains_no_credentials_or_secrets() -> None:
    text = DEVCONTAINER.read_text(encoding="utf-8").lower()
    for forbidden in ("password", "token=", "credential"):
        assert forbidden not in text


def test_2307_does_not_speculatively_restore_historical_dockerfile_workaround() -> None:
    assert not (ROOT / ".devcontainer" / "Dockerfile").exists()


def test_runbook_documents_bounded_ssh_and_gce_boundary() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    for phrase in (
        "gh codespace ssh",
        "scripts/agent-os-environment-health.py",
        "Closed PR #1215",
        "not part of #2307 unless",
        "#759 containment",
        "GCE",
        "Non-authorization",
        "rollback",
    ):
        assert phrase in text


def test_runbook_stays_bounded() -> None:
    assert RUNBOOK.read_text(encoding="utf-8").count("\n") < 120
