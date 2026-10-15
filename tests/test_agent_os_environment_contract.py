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


# --- #3333 Gate 4: execution-service runtime declaration -----------------------

EXECUTION_SERVICE_DIR = "08_Tooling/agent-os-execution-service"
EXECUTION_SERVICE_INSTALL = f'python -m pip install -e "./{EXECUTION_SERVICE_DIR}"'
HOST_PATH_ENV_VARS = (
    "AGENT_OS_CHECKPOINT_STORE_ROOT",
    "AGENT_OS_REPOSITORY_ROOT",
    "AGENT_OS_WORKSPACE_PARENT",
    "AGENT_OS_LEASE_DIRECTORY",
)


def _post_create_commands() -> list[str]:
    lines = (DEVCONTAINER_DIR / "post-create.sh").read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]


def test_post_create_installs_the_existing_execution_service_distribution_once() -> None:
    commands = _post_create_commands()
    assert commands.count(EXECUTION_SERVICE_INSTALL) == 1
    pyproject = ROOT / EXECUTION_SERVICE_DIR / "pyproject.toml"
    assert 'name = "agent-os-execution-service"' in pyproject.read_text(encoding="utf-8")


def test_execution_service_installs_after_its_local_dependencies_are_supplied() -> None:
    # workflow-scheduler, agent-memory-context-manager and
    # instructional-workflow-contracts are not on an index; requirements-dev.txt
    # supplies them from the checkout, so it must run first.
    commands = _post_create_commands()
    requirements = commands.index("python -m pip install -r requirements-dev.txt")
    assert requirements < commands.index(EXECUTION_SERVICE_INSTALL)
    text = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    for local in ("./src", "./08_Tooling/agent-memory-context-manager", "./08_Tooling/workflow-scheduler"):
        assert f"-e {local}" in text


def test_execution_service_is_not_installed_through_a_second_bootstrap_path() -> None:
    requirements = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    assert "agent-os-execution-service" not in requirements
    assert "agent_os_execution_service" not in requirements


def test_profile_binds_no_host_path_value_or_placeholder() -> None:
    # Choosing real locations is a separately authorized host-qualification step.
    # An unset variable keeps host bootstrap failing closed; a placeholder would
    # make an unqualified Codespace look configured.
    payload = json.loads((DEVCONTAINER_DIR / "devcontainer.json").read_text(encoding="utf-8"))
    declared = set(payload.get("remoteEnv", {})) | set(payload.get("containerEnv", {}))
    post_create = (DEVCONTAINER_DIR / "post-create.sh").read_text(encoding="utf-8")
    dockerfile = (DEVCONTAINER_DIR / "Dockerfile").read_text(encoding="utf-8")
    for name in HOST_PATH_ENV_VARS:
        assert name not in declared
        assert name not in post_create
        assert name not in dockerfile


def test_contract_doc_names_the_four_host_paths_and_the_unqualified_boundary() -> None:
    doc = (ROOT / "docs" / "3333-fixed-codespace-implementation-ingress.md").read_text(encoding="utf-8")
    section = doc.split("## Codespaces runtime installation and host bindings (Gate 4)", 1)[1]
    for name in HOST_PATH_ENV_VARS:
        assert name in section
    assert "sets none of them" in section
    assert "does not qualify the Codespace as a" in " ".join(section.split())
