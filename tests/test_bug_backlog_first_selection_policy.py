"""Regression guards for #1827 backlog-first selection and #1957 batch progression."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "AGENTS.md"
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_bug_work_reconciles_existing_backlog_before_fresh_discovery() -> None:
    workflow = normalized(AGENTS)
    assert "reconcile the existing discovered/open bug backlog before fresh defect discovery" in workflow
    assert "use eligible existing bugs first" in workflow
    assert "discover new bugs only when the reconciled backlog cannot satisfy the requested count" in workflow


def test_bug_work_filters_ineligible_existing_candidates() -> None:
    workflow = normalized(AGENTS)
    for state in (
        "stale",
        "duplicate",
        "already-fixed",
        "active-implementation",
        "non-repository",
        "blocked",
        "unauthorized",
    ):
        assert state in workflow


def test_bug_work_does_not_pad_requested_count_with_new_issues() -> None:
    workflow = normalized(AGENTS)
    assert "Do not create issues merely to pad a requested count." in workflow


def test_backlog_first_rule_reuses_existing_orchestrator_mission_routing() -> None:
    routing = normalized(ORCHESTRATOR)
    assert "explicitly bounded finite multi-item mission" in routing
    assert "maintain a mission cursor" in routing
    assert "Do not silently substitute, omit, or duplicate requested identities." in routing


def test_bug_batch_item_local_dispositions_advance_existing_cursor() -> None:
    workflow = normalized(AGENTS)
    assert "Bind each candidate disposition to the existing finite-mission cursor" in workflow
    for disposition in (
        "already-fixed/completed",
        "duplicate",
        "blocked-item-local",
        "separately-gated",
        "external-owner/non-repository",
    ):
        assert disposition in workflow
    assert "non-terminal for the parent batch" in workflow
    assert "immediately advance to the next independent candidate without another user prompt" in workflow
    assert "rebuilding the batch investigation" in workflow


def test_bug_batch_stops_later_candidates_only_for_shared_blocker() -> None:
    workflow = normalized(AGENTS)
    for blocker in (
        "shared authorization",
        "source-of-truth",
        "bounded-scope",
        "excluded-surface",
        "capability",
        "material-decision",
    ):
        assert blocker in workflow
    assert "continue until the requested count is worked or the reconciled pool is exhausted" in workflow
    assert "report the honest shortfall" in workflow


def test_backlog_first_selection_does_not_expand_authority() -> None:
    workflow = normalized(AGENTS)
    routing = normalized(ORCHESTRATOR)
    assert "stop if authorization or source of truth is unclear" in workflow
    assert "Mission continuation never widens authority" in routing
    assert "cannot infer merge, issue closure" in routing
