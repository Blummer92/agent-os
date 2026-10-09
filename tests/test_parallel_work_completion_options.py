"""Regression contract for bounded parallel-work completion options (#3503)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STANDARD = ROOT / "01_Shared_Standards/global-engineering/agent-interaction-output-standard.md"
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"
ORCHESTRATOR_TESTS = ROOT / "07_Agent_Tests/chatgpt-orchestrator.tests.md"
VERSION_MAP = ROOT / "04_Registry/module-version-map.md"
FIXTURE = ROOT / "tests/fixtures/chatgpt_orchestrator/parallel_work_options.json"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def section(path: Path, heading: str) -> str:
    text = read(path)
    marker = f"## {heading}\n"
    assert marker in text
    return text.split(marker, 1)[1].split("\n## ", 1)[0]


def test_output_standard_defines_bounded_parallel_work_choices() -> None:
    text = section(STANDARD, "Bounded Parallel Work Options")
    for phrase in (
        "work on 5 other eligible issues",
        "work on 10 other eligible issues",
        "continue only the current lineage",
        "or stop",
        "Do not begin unrelated work before the owner selects",
        "freeze the original finite population",
        "do not silently expand",
        "one issue -> one scoped PR",
        "One item-local blocker never stops independent later items",
        "create no merge, issue-closure",
        "#3485 continuation/terminal-stop semantics",
    ):
        assert phrase in text


def test_candidate_fixture_has_ten_independently_eligible_issues() -> None:
    fixture = json.loads(read(FIXTURE))
    eligible = [item for item in fixture["candidates"] if item["disposition"] == "eligible"]
    assert fixture["requested_parallel_count"] == 10
    assert len(eligible) == 10
    assert len({item["issue"] for item in eligible}) == 10
    assert all(item["state"] == "open" for item in eligible)
    assert all(item["status"] == "ready" for item in eligible)
    assert all(item["boundary"] == "no-external-write" for item in eligible)
    assert all(not item["active_lineage"] for item in eligible)
    assert len({item["scope"] for item in eligible}) == 10


def test_fixture_contains_fail_closed_exclusions() -> None:
    fixture = json.loads(read(FIXTURE))
    exclusions = {item["disposition"] for item in fixture["candidates"] if item["disposition"] != "eligible"}
    assert exclusions == {
        "exclude-blocked",
        "exclude-active-lineage",
        "exclude-conflicting-scope",
        "exclude-duplicate-owner",
        "exclude-stale",
    }


def test_orchestrator_consumes_canonical_parallel_option_contract() -> None:
    response = section(ORCHESTRATOR, "Response Ordering Rule")
    assert "Bounded Parallel Work Options" in response
    assert "5 other eligible issues" in response
    assert "10 other eligible issues" in response
    assert "Do not start unrelated work until that option is selected" in response
    assert "existing open-backlog eligibility" in response
    assert "rather than creating a queue or scheduler" in response


def test_regression_fixtures_cover_selection_and_item_local_continuation() -> None:
    text = read(ORCHESTRATOR_TESTS)
    for heading in (
        "Test 79 - Terminal Completion Offers Bounded Parallel Work (#3503)",
        "Test 80 - Selected Parallel Batch Is Finite And Conflict-Safe (#3503)",
        "Test 81 - Parallel Batch Continues Past Item-Local Blocker (#3503)",
    ):
        assert f"## {heading}\n" in text
    assert "freeze exactly 10 eligible independent identities" in text
    assert "continue C/D/E without another owner prompt" in text
    assert "no untouched identity" in text


def test_versions_are_synchronized() -> None:
    assert section(STANDARD, "Version").strip() == "0.2.2"
    assert section(ORCHESTRATOR, "Version").splitlines()[0].strip() == "0.3.19"
    version_map = read(VERSION_MAP)
    assert "| Agent Interaction Output Standard | 0.2.2 |" in version_map
    assert "| ChatGPT Orchestrator | 0.3.19 |" in version_map
