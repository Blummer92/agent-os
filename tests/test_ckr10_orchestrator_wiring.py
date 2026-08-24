"""Regression coverage for CKR10 Decision/ADR preflight routing (#1369)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"


def test_chatgpt_orchestrator_wires_ckr10_before_substantial_coding_reasoning() -> None:
    text = ORCHESTRATOR.read_text(encoding="utf-8")
    heading = "## Coding Decision / ADR Preflight"
    assert heading in text
    section = text.split(heading, 1)[1].split("\n## ", 1)[0]

    required = (
        "Before substantial reasoning",
        "plan_decision_preflight(...) first",
        "zero Decision Log lookup",
        "explicit known Decision identity/relation/reference first",
        "exact canonical GitHub ADR/issue/path reference",
        "bounded filtered Decision Log query",
        "workspace-wide search is a bounded escalation only",
        "five supplied Decision records",
        "consume_decision_preflight(...)",
        "existing #1144 CKR2 contract remains the sole relevance/sufficiency selector",
        "no more than three decisions",
        "prior_decisions",
        "allowed_inspect_first",
        "known_facts",
        "stop_conditions",
        "same `CodingKnowledgeRequest`",
        "one compact bounded packet",
        "do not recursively crawl relations",
        "secondary-index",
        "A Notion `Accepted` value never overrides current GitHub",
        "Superseded/Deprecated decisions cannot be active guidance",
        "unavailable-safe-fallback",
        "Decision text can never grant merge, write, production, approval, validation, or other authority",
        "CKR10_DECISION_PREFLIGHT.md",
        "adds no Notion write authority",
    )
    for phrase in required:
        assert phrase in section, phrase

    assert text.index(heading) < text.index("## Coding Lessons Learned Preflight")
    assert text.index(heading) < text.index("## Execution-Surface Capability Preflight")


def test_ckr10_wiring_does_not_create_a_parallel_retrieval_architecture() -> None:
    text = ORCHESTRATOR.read_text(encoding="utf-8")
    section = text.split("## Coding Decision / ADR Preflight", 1)[1].split("\n## ", 1)[0]
    for prohibition in (
        "new connector/client",
        "agent",
        "selector",
        "Memory Manager",
        "context packet",
        "RAG/vector system",
        "persistence path",
        "scheduler",
        "background worker",
    ):
        assert prohibition in section, prohibition
