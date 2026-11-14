"""Bounded #3485/#2425 CKR6 GitHub-ingress host instruction-oracle tests.

Adapted from the independently QA-proven P7 polarity oracle. These tests
validate repository text and executable predicate parity, NOT native ChatGPT
host dispatch, wait, or future-turn re-entry.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from agent_os_execution_service import ckr6_github_bridge as bridge

ROOT = Path(os.environ.get("AOS_ROOT", Path(__file__).resolve().parents[3]))
OVERLAY = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"


def _bullet(marker: str, following: str) -> str:
    text = " ".join(OVERLAY.read_text(encoding="utf-8").split())
    start = text.index(marker)
    end = text.index(following, start)
    return text[start:end]


def _admitted(flag: bool) -> bool:
    result = {
        "operation": "issue-start",
        "status": "sufficient" if flag else "insufficient",
        "selected_lesson_ids": ["LL-1"] if flag else [],
        "substantial_hypothesis_admissible": flag,
    }
    return bridge.ckr6_result_admits_boundary(result)


def test_github_ingress_stop_literal_matches_executable_admission_polarity() -> None:
    ingress = _bullet("When the host cannot run the in-process bridge", "- GitHub-ingress admitted-result continuation.")
    matches = re.findall(r"honor `(true|false)` as a hard stop", ingress)
    assert len(matches) == 1, "exactly one hard-stop admission literal must remain"
    stop_literal = matches[0] == "true"
    assert _admitted(stop_literal) is False, "host would STOP on a value the consumer ADMITS"
    assert _admitted(not stop_literal) is True, "host would admit a consumer-blocked result"


def test_admitted_result_explicitly_returns_parent_without_granting_authority() -> None:
    clause = _bullet("- GitHub-ingress admitted-result continuation.", "- GitHub-ingress result wait and STOP.")
    requirements = (
        "trusted result comment",
        "exact pending request",
        "`substantial_hypothesis_admissible=true`",
        "subordinate intermediate evidence",
        "original parent mission cursor",
        "next still-authorized operation",
        "same active turn",
        "literal `false` authority flags",
        "grant no new execution",
        "do not revoke",
        "HARD STOP",
    )
    missing = [item for item in requirements if item not in clause]
    assert not missing, f"CKR6 admitted-result continuation clause missing: {missing}"


def test_ingress_route_and_wait_stop_rule_are_separate_non_optional_bullets() -> None:
    text = OVERLAY.read_text(encoding="utf-8")
    ingress = [line for line in text.splitlines() if line.startswith("- When the host cannot run the in-process bridge")]
    continue_clause = [line for line in text.splitlines() if line.startswith("- GitHub-ingress admitted-result continuation.")]
    wait = [line for line in text.splitlines() if line.startswith("- GitHub-ingress result wait and STOP.")]
    assert len(ingress) == len(continue_clause) == len(wait) == 1
    assert text.index(ingress[0]) < text.index(continue_clause[0]) < text.index(wait[0])
    assert "HARD STOP" in wait[0]
