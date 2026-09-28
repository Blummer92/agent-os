"""Regression guards for #3014 native GitHub Actions-variable integration handoff."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HANDOFF = ROOT / "01_Shared_Standards/github/tool-discovery-native-integration-handoff.md"


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_3014_actions_variable_operation_family_is_explicit() -> None:
    contract = normalized(HANDOFF)

    for phrase in (
        "#3014 finite repository Actions-variable integration",
        "read_repository_actions_variable(repository, name)",
        "set_repository_actions_variable(repository, name, value, authorization_binding, expected_prestate_sha256)",
        "delete_repository_actions_variable(repository, name, authorization_binding, expected_current_sha256)",
        "Blummer92/agent-os / AGENT_OS_LESSONS_LEARNED_DATA_SOURCE_ID",
    ):
        assert phrase in contract


def test_3014_requires_prestate_binding_and_readback() -> None:
    contract = normalized(HANDOFF)

    for phrase in (
        "return bounded current pre-state",
        "deterministic pre-state digest",
        "refuse a stale or mismatched digest",
        "immediately read the exact same variable back and prove convergence",
        "mutation without immediate canonical readback",
    ):
        assert phrase in contract


def test_3014_preserves_finite_authorization_boundary() -> None:
    contract = normalized(HANDOFF)

    for phrase in (
        "generic REST passthrough",
        "generic repository-settings API",
        "GitHub Actions secrets",
        "rulesets or branch protection",
        "repository permissions",
        "GitHub App/OAuth/PAT/credential administration",
        "IAM/WIF",
        "does not itself authorize a protected-setting mutation",
    ):
        assert phrase in contract


def test_3014_live_acceptance_keeps_repository_conformance_nonterminal() -> None:
    contract = normalized(HANDOFF)

    assert "Repository conformance is not live capability proof" in contract
    assert "#3014 remains externally incomplete" in contract
    assert "the #2854 canary completes without leaving the connected-agent path" in contract
