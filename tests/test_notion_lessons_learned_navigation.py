from pathlib import Path

ROOT = Path(__file__).parents[1]
REGISTRY = ROOT / "04_Registry/navigation-alias-registry.md"
AGENTS = ROOT / "AGENTS.md"
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"


def _alias_section() -> str:
    text = REGISTRY.read_text(encoding="utf-8")
    start = text.index("### @notion-lessons-learned")
    end = text.index("\n### ", start + 4)
    return text[start:end]


def test_notion_lessons_learned_alias_resolves_existing_contracts() -> None:
    section = _alias_section()
    for path in (
        "AGENTS.md",
        "02_Agent_Overlays/chatgpt-orchestrator.md",
        "08_Tooling/agent-memory-context-manager/CKR6_LESSON_PREFLIGHT.md",
        "01_Shared_Standards/notion/notion-learning-databases.md",
        "docs/2283-github-notion-read-path.md",
    ):
        assert path in section
        assert (ROOT / path).exists()


def test_native_notion_plugin_absence_is_not_terminal_capability_evidence() -> None:
    section = _alias_section().lower()
    assert "direct plugin is one possible transport surface, not capability truth" in section
    assert "does not prove the governed agent os notion capability is unavailable" in section
    assert "resolve this alias and inspect the current github-controlled route" in section


def test_route_discovery_must_continue_parent_mission() -> None:
    section = _alias_section().lower()
    assert "successful route discovery is intermediate evidence" in section
    assert "continue the parent mission" in section
    assert "do not stop merely because the direct plugin is unavailable" in section


def test_global_orchestrator_contract_supports_alias_and_continuation_semantics() -> None:
    agents = AGENTS.read_text(encoding="utf-8")
    orchestrator = ORCHESTRATOR.read_text(encoding="utf-8")
    assert "before declaring the capability unavailable" in agents
    assert "Successful tool/schema/capability discovery" in orchestrator
    assert "intermediate evidence" in orchestrator
