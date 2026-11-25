"""Ledger-backed regression oracles for Agent OS CI trust boundaries.

This file consumes a reviewed, versioned snapshot of GitHub incident evidence.
It intentionally makes *no* network calls and has no GitHub/Notion writes.
Historical hosted evidence identifies the regression; these tests verify the
current pure-code behavior. Passing here is not hosted acceptance.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from scripts.agent_os_aggregate_gate import (
    decide_terminal_status,
    evaluate_aggregate_gate,
    resolve_terminal_authority,
)
from scripts.agent_os_ci_junit_diff import junit_outcomes, skipped_node_ids
from scripts.agent_os_ci_validation import _junit_counts, _pytest_evidence_error
from scripts.agent_os_remote_validation import (
    SelectionInput,
    load_rule_map,
    select_validation_plan,
)

ROOT = Path(__file__).resolve().parents[2]
LEDGER_FILE = (
    ROOT
    / "tests/agent_os_remote_validation/fixtures/ci_negative_control_ledger.json"
)
LEDGER = json.loads(LEDGER_FILE.read_text(encoding="utf-8"))
CASES = LEDGER["cases"]
SUPPORTED = frozenset({
    "selection", "authority", "gate", "terminal", "junit", "focused-junit"
})


def test_ledger_provenance_and_case_identity_are_explicit() -> None:
    assert LEDGER["schema"] == "agent-os-ci-negative-ledger/1"
    assert LEDGER["repository"] == "Blummer92/agent-os"
    assert len(CASES) >= 30
    ids = [case["id"] for case in CASES]
    assert len(ids) == len(set(ids))
    assert all(case["kind"] in SUPPORTED for case in CASES)
    assert all(
        case["source"].startswith("https://github.com/Blummer92/agent-os/")
        and "/issues/" in case["source"]
        for case in CASES
    )
    assert all(isinstance(case["expected"], dict) for case in CASES)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_ledger_negative_and_recovery_oracles(case: dict, tmp_path: Path) -> None:
    """Each historical incident has deterministic reject/recovery expectations."""
    kind = case["kind"]
    inputs = case["input"]
    expected = case["expected"]

    if kind == "selection":
        plan = select_validation_plan(
            SelectionInput(
                repository=LEDGER["repository"],
                pull_request=4108,
                base_sha="a" * 40,
                head_sha="b" * 40,
                changed_files=tuple(inputs["paths"]),
            ),
            load_rule_map(),
        )
        assert plan.profile == expected["profile"]
        assert tuple(plan.commands) == tuple(expected["commands"])
        return

    if kind == "authority":
        authorized, head = resolve_terminal_authority(**inputs)
        assert authorized is expected["authorized"]
        assert head == expected["head"]
        return

    if kind == "gate":
        open_gate, _reason = evaluate_aggregate_gate(**inputs)
        assert open_gate is expected["open"]
        return

    if kind == "terminal":
        verdict = decide_terminal_status(**inputs)
        assert (None if verdict is None else verdict.state) == expected["state"]
        return

    if kind == "junit":
        report = inputs["xml"].encode("utf-8")
        if expected.get("error") == "ValueError":
            with pytest.raises(ValueError):
                junit_outcomes(report)
            return
        if inputs["operation"] == "skipped":
            assert sorted(skipped_node_ids(report)) == expected["nodes"]
        else:
            outcomes = junit_outcomes(report)
            for metric in ("failures", "errors"):
                if metric in expected:
                    assert outcomes[metric] == expected[metric]
        return

    if kind == "focused-junit":
        report = tmp_path / "focused.xml"
        if inputs["xml"] is not None:
            report.write_text(inputs["xml"], encoding="utf-8")
        counts = _junit_counts(report, check_cases=True)
        detected = _pytest_evidence_error(counts)
        assert (detected is not None) is expected["reject"]
        return

    pytest.fail(f"Unknown ledger oracle: {kind}")


def test_legacy_negative_controls_remain_executable_and_ledger_linked() -> None:
    """Don't silently replace independent, real-run controls with mock tests.

    Registry entries point at already-existing regression functions; parse
    source rather than importing other pytest modules or running network calls.
    The ledger snapshot is the reviewable identity/provenance anchor.
    """
    controls = LEDGER["existing_controls"]
    assert {entry["id"] for entry in controls} >= {
        "NC07", "NC08", "NC09", "NC19", "D07", "NC-SELECT"
    }
    for entry in controls:
        assert entry["source"] == (
            f"https://github.com/{LEDGER['repository']}/issues/{entry['issue']}"
        )
        for role in ("negative", "positive"):
            path, separator, test_name = entry[role].partition("::")
            assert separator and test_name.startswith("test_")
            file_path = ROOT / path
            assert file_path.is_relative_to(ROOT / "tests")
            assert file_path.is_file(), f"Missing {entry['id']} {role} test file"
            tree = ast.parse(file_path.read_text(encoding="utf-8"))
            names = {
                node.name
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            assert test_name in names, (
                f"Lost {entry['id']} {role} regression: {entry[role]}"
            )
