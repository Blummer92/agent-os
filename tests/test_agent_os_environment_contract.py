"""Contract tests for the `agent-os-codespaces-v1` profile (#891/#2299)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEVCONTAINER_DIR = ROOT / ".devcontainer"
RUNBOOK = ROOT / "docs" / "AGENT_OS_CODESPACES_RUNBOOK.md"


def test_devcontainer_json_is_valid_and_bounded_to_two_cores() -> None:
    payload = json.loads((DEVCONTAINER_DIR / "devcontainer.json").read_text(encoding="utf-8"))
    assert payload["hostRequirements"]["cpus"] == 2
    assert payload["build"]["dockerfile"] == "Dockerfile"
    assert payload["postCreateCommand"] == "bash .devcontainer/post-create.sh"
    assert payload["remoteEnv"]["AGENT_OS_NETWORK_MODE"] == "local-only"


def test_codespaces_profile_uses_only_official_bounded_features() -> None:
    payload = json.loads((DEVCONTAINER_DIR / "devcontainer.json").read_text(encoding="utf-8"))
    assert payload["features"] == {
        "ghcr.io/devcontainers/features/github-cli:1": {},
        "ghcr.io/devcontainers/features/sshd:1": {},
    }


def test_codespaces_dockerfile_is_minimal_yarn_source_repair() -> None:
    text = (DEVCONTAINER_DIR / "Dockerfile").read_text(encoding="utf-8")
    assert text.startswith("FROM mcr.microsoft.com/devcontainers/python:1-3.11-bookworm\n")
    assert "rm -f /etc/apt/sources.list.d/yarn.list" in text
    for forbidden in ("apt-get install", "curl ", "wget ", "gpg ", "apt-key", "COPY ", "ADD "):
        assert forbidden not in text


def test_codespaces_configuration_contains_no_credentials() -> None:
    text = "\n".join(
        (DEVCONTAINER_DIR / name).read_text(encoding="utf-8").lower()
        for name in ("devcontainer.json", "Dockerfile", "post-create.sh")
    )
    for forbidden in ("password=", "token=", "gh auth login", "git push"):
        assert forbidden not in text


def test_post_create_remains_fail_closed_and_reuses_environment_health() -> None:
    text = (DEVCONTAINER_DIR / "post-create.sh").read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in text
    assert "requirements-dev.txt" in text
    assert "scripts/agent-os-environment-health.py" in text


def test_runbook_stays_bounded_and_documents_split_runner_role() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    assert text.count("\n") < 100
    for phrase in (
        "agent-os-codespaces-v1",
        "2-core",
        "local-only",
        "github-connected",
        "gh codespace ssh",
        "developer-loop",
        "#759",
        "GCE",
        "focused validation",
        "exact-head",
        "stop/start",
        "Non-authorization",
    ):
        assert phrase in text


def test_existing_worktree_and_repository_state_owners_are_reused() -> None:
    runbook = RUNBOOK.read_text(encoding="utf-8")
    assert "prepare-issue-worktree.sh" in runbook
    assert "verify-repo-state.sh" in runbook
    assert "#918" in runbook
    assert "#1237" in runbook
