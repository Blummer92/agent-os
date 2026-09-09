"""Regression fixture for #2064's existing-bug batch cutoff.

The backlog-reconciliation and cursor-advance pins that this file used to carry
are now owned, in their current canonical wording and with strictly stronger
assertions, by ``tests/test_bug_backlog_first_selection_policy.py`` (#1827 /
#1957 / #2026 / #2184). Duplicating those exact governance substrings here only
guaranteed that every legitimate rewording of the AGENTS.md step broke this file
too -- which is what #2184 did. Only the pin unique to #2064 remains here.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "AGENTS.md"
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_existing_primary_lineages_are_reused_and_batch_cursor_stays_live() -> None:
    routing = normalized(ORCHESTRATOR)
    assert "maintain a mission cursor until every requested item has a terminal mission state" in routing
    assert "An item-local blocker does not stop independently actionable later items." in routing
    assert "Do not silently substitute, omit, or duplicate requested identities." in routing
