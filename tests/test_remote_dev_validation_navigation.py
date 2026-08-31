from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
REGISTRY = ROOT / "04_Registry/navigation-alias-registry.md"


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
    assert "does not prove this governed GCE/IAP lane is unavailable" in section
    assert "fixed validation identity" in section
    assert "grants no new authority" in section
    assert "do not invent arbitrary argv" in section
    assert "generic SSH shell" in section
    assert "#1237" in section
