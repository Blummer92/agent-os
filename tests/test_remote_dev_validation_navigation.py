from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
REGISTRY = ROOT / "04_Registry/navigation-alias-registry.md"
AGENTS = ROOT / "AGENTS.md"


def _alias_section() -> str:
    text = REGISTRY.read_text(encoding="utf-8")
    match = re.search(
        r"^### @remote-dev-validation\n(?P<section>.*?)(?=^### |^## Version)",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None
    return match.group("section")


def test_remote_dev_validation_alias_references_existing_contracts() -> None:
    section = _alias_section()
    expected_paths = (
        "01_Shared_Standards/github/safe-implementation-lane.md",
        "docs/2299-codespaces-developer-runner.md",
        "08_Tooling/workflow-scheduler/src/workflow_scheduler/governance/dev_validation.py",
        "08_Tooling/workflow-scheduler/src/workflow_scheduler/governance/github_issue_comment_ingress.py",
        "08_Tooling/workflow-scheduler/src/workflow_scheduler/governance/dev_validation_gce.py",
    )
    for path in expected_paths:
        assert f"`{path}`" in section
        assert (ROOT / path).is_file()


def test_remote_dev_validation_alias_covers_discovery_phrases_and_distinctions() -> None:
    section = _alias_section()
    for phrase in (
        "GitHub SSH",
        "SSH execution",
        "remote validation",
        "developer validation",
        "Codespaces runner",
        "Codespaces SSH",
        "validation VM",
        "GCE executor",
        "IAP SSH",
        "dev validate",
        "SSH execution handoff",
        "GitHub-SSH execution host",
        "A — LIGHTWEIGHT LANE",
    ):
        assert phrase in section

    for distinct_route in (
        "ssh git@github.com",
        "GitHub API/connector",
        "Cloud Build",
        "Scheduler/GCE",
        "Codespaces SSH",
    ):
        assert distinct_route in section


def test_remote_dev_validation_alias_preserves_bounded_non_authorizing_route() -> None:
    section = _alias_section()
    assert "current/capable Codespaces is preferred" in section
    assert "#759 containment" in section
    assert "unattended Scheduler" in section
    assert "fixed-service-identity" in section
    assert "fall back through the existing governed GCE route under #1237" in section
    assert "does not prove governed developer-loop execution is unavailable" in section
    assert "fixed validation identity" in section
    assert "grants no new authority" in section
    assert "do not invent arbitrary argv" in section
    assert "generic SSH shell" in section


def test_agent_entrypoint_resolves_named_capability_before_unavailable() -> None:
    text = AGENTS.read_text(encoding="utf-8")

    assert "`GitHub SSH`" in text
    assert "resolve that path through the Navigation Alias Registry" in text
    assert "before declaring the capability unavailable" in text
    assert "literal active tool/action list" in text
    assert "Absence of a same-named local tool or command is surface evidence only" in text
    assert "not proof that the registered Agent OS capability is unavailable" in text
    assert "#1237 continuation/currentness rules" in text
