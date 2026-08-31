"""Bounded property-based pilot for the remote-validation selector (#1554).

Hypothesis is a qualification-only dependency
(`08_Tooling/workflow-scheduler/docs/DEPENDENCY_READINESS.md`), not a permanent
entry in `requirements-dev.txt`, so it is absent on the governed
remote-validation host. This module must therefore never make its absence a
collection error for the governed aggregate suite: a collection error exits 2
and stops every other test in the run. The `importorskip` guard below precedes
every Hypothesis import, matching
`tests/agent_os_issue_acceptance/test_parse_pr_hypothesis.py` (#1477) and
`08_Tooling/agent-os-execution-service/tests/test_hypothesis_qualification.py`
(#1138).

Generation stays offline and deterministic per the #1554 constraints:
`derandomize=True` fixes the seed and `database=None` suppresses the
`.hypothesis` example database, so a run adds no workspace side effect and no
non-reproducible failure.
"""
from __future__ import annotations

import copy
from importlib.metadata import version

import pytest

pytest.importorskip(
    "hypothesis",
    reason="Hypothesis is qualification-only and is not a permanent repository dependency",
)

from hypothesis import given, settings, strategies as st

from scripts.agent_os_remote_validation import (
    SelectionInput,
    load_rule_map,
    select_validation_plan,
    validate_validation_plan,
)

QUALIFIED_HYPOTHESIS_VERSION = "6.165.9"

BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
RULES = load_rule_map()


def _input(paths: tuple[str, ...]) -> SelectionInput:
    return SelectionInput(
        repository="Blummer92/agent-os",
        pull_request=1554,
        base_sha=BASE_SHA,
        head_sha=HEAD_SHA,
        changed_files=paths,
    )


def _owned_paths() -> tuple[str, ...]:
    paths: list[str] = []
    for rule in RULES["focused_rules"]:
        paths.extend(rule.get("exact_paths", []))
        for prefix in rule.get("prefixes", []):
            paths.append(prefix + "property_probe.py" if prefix.endswith("/") else prefix)
    paths.extend(RULES["aggregate_paths"])
    for prefix in RULES["aggregate_prefixes"]:
        paths.append(prefix + "property_probe.py" if prefix.endswith("/") else prefix)
    for prefix in RULES["documentation_prefixes"]:
        paths.append(prefix + "property-probe.md" if prefix.endswith("/") else prefix)
    return tuple(dict.fromkeys(paths))


OWNED_PATHS = _owned_paths()


def test_hypothesis_uses_exact_qualified_version() -> None:
    """Qualification-only pins are exact; a range would drift the qualified run."""
    assert version("hypothesis") == QUALIFIED_HYPOTHESIS_VERSION


@settings(max_examples=250, deadline=None, database=None, derandomize=True)
@given(st.lists(st.sampled_from(OWNED_PATHS), min_size=1, max_size=8, unique=True))
def test_changed_file_permutation_preserves_plan(paths: list[str]) -> None:
    """Selection identity must depend on the changed-file set, never its order."""
    forward = select_validation_plan(_input(tuple(paths)), RULES)
    reverse = select_validation_plan(_input(tuple(reversed(paths))), RULES)
    assert reverse == forward
    assert validate_validation_plan(forward) == ()


@settings(max_examples=200, deadline=None, database=None, derandomize=True)
@given(st.lists(st.sampled_from(OWNED_PATHS), min_size=1, max_size=8, unique=True))
def test_focused_rule_permutation_preserves_plan(paths: list[str]) -> None:
    """Rule declaration order must not change canonical selection identity."""
    baseline = select_validation_plan(_input(tuple(paths)), RULES)
    reversed_rules = copy.deepcopy(RULES)
    reversed_rules["focused_rules"] = list(reversed(reversed_rules["focused_rules"]))
    candidate = select_validation_plan(_input(tuple(paths)), reversed_rules)
    assert candidate == baseline
    assert validate_validation_plan(candidate) == ()


@settings(max_examples=150, deadline=None, database=None, derandomize=True)
@given(st.sampled_from(OWNED_PATHS))
def test_duplicate_changed_paths_do_not_change_semantic_plan(path: str) -> None:
    """Repeated evidence for the same changed path must not create new commands."""
    single = select_validation_plan(_input((path,)), RULES)
    duplicate = select_validation_plan(_input((path, path)), RULES)
    assert duplicate == single
    assert validate_validation_plan(duplicate) == ()


def test_property_domain_contains_multiple_selector_classes() -> None:
    """Guard the pilot generator itself from collapsing to one trivial profile."""
    profiles = {
        select_validation_plan(_input((path,)), RULES).profile for path in OWNED_PATHS
    }
    assert {"static", "focused", "aggregate"}.issubset(profiles)
