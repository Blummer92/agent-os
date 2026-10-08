"""Regression proof for the #907 -> #918 executor-route retirement.

#907 (``scripts/agent_os_issue_acceptance/executor_route.py``, the deterministic
executor-route selector) was retired in favor of #918 (the canonical router in
``08_Tooling/agent-os-execution-service/src/agent_os_execution_service/
executor_routing.py``), per owner decision via closed #3323 / ADR-8.

These tests lock in the retirement: they fail if the retired module is
reintroduced, if a second ``select_executor_route`` appears anywhere in the
tree, if the canonical route vocabulary drifts, if the ported #907 resume
invariant (``_prior_route_available``) disappears, or if a competing
route-name vocabulary shows up in live code.
"""

from __future__ import annotations

import ast
from pathlib import Path

from agent_os_execution_service.executor_routing import (
    ExecutorRoute,
    ExecutorRouteReason,
)

# tests -> agent-os-execution-service -> 08_Tooling -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]

RETIRED_MODULE_REL = Path("scripts/agent_os_issue_acceptance/executor_route.py")

CANONICAL_ROUTE_NAMES = frozenset(
    {
        "chatgpt-connector-native",
        "chatgpt-governed-runner",
        "external-coding-agent-fallback",
        "human-decision-required",
    }
)

# Bare identifiers from the retired #907 route vocabulary. These must not
# appear as standalone route identifiers in live code. Attribute/field names
# that merely extend them (e.g. ``external_fallback_capabilities``) are
# current #918 vocabulary and are handled by exact-match AST checks, not
# substring matching.
RETIRED_BARE_NAMES = frozenset(
    {"chatgpt_connector", "governed_runner", "external_fallback"}
)


def _python_files(exclude_tests: bool = False):
    for path in REPO_ROOT.rglob("*.py"):
        # Stay inside the repo and skip hidden/vendor trees.
        if any(part.startswith(".") for part in path.parts):
            continue
        if exclude_tests and "tests" in path.parts:
            continue
        yield path


def _parse_or_none(path: Path):
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None


def test_retired_module_does_not_exist():
    """The #907 module must stay deleted."""
    retired = REPO_ROOT / RETIRED_MODULE_REL
    assert not retired.exists(), (
        f"retired #907 module reintroduced: {retired.relative_to(REPO_ROOT)}"
    )


def test_exactly_one_select_executor_route_definition():
    """Exactly one ``select_executor_route`` may exist in the tree."""
    definitions = []
    for path in _python_files():
        tree = _parse_or_none(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                node.name == "select_executor_route"
            ):
                definitions.append(str(path.relative_to(REPO_ROOT)))
    assert len(definitions) == 1, (
        f"expected exactly 1 select_executor_route definition, found "
        f"{len(definitions)}: {sorted(definitions)}"
    )


def test_canonical_route_vocabulary_is_exactly_four():
    """The #918 route vocabulary is closed: exactly the four canonical names."""
    names = frozenset(route.value for route in ExecutorRoute)
    assert names == CANONICAL_ROUTE_NAMES, (
        f"route vocabulary drift: extra={sorted(names - CANONICAL_ROUTE_NAMES)}, "
        f"missing={sorted(CANONICAL_ROUTE_NAMES - names)}"
    )


def test_prior_route_resume_invariant_survives():
    """The #907 resume invariant was ported; it must remain present."""
    import agent_os_execution_service.executor_routing as routing

    assert callable(routing._prior_route_available), (  # noqa: SLF001
        "_prior_route_available is not callable"
    )
    reason_values = frozenset(reason.value for reason in ExecutorRouteReason)
    assert "prior-route-preserved" in reason_values
    assert "prior-route-not-available" in reason_values


def test_no_competing_bare_route_names_in_live_code():
    """No live module may define or use the retired #907 bare route names."""
    offenders = []
    for path in _python_files(exclude_tests=True):
        tree = _parse_or_none(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value.strip()
                if value in RETIRED_BARE_NAMES:
                    offenders.append(
                        f"{path.relative_to(REPO_ROOT)}: string literal {value!r}"
                    )
            elif isinstance(node, ast.Name) and node.id in RETIRED_BARE_NAMES:
                offenders.append(
                    f"{path.relative_to(REPO_ROOT)}: name {node.id!r}"
                )
    assert not offenders, (
        "competing retired-#907 route vocabulary in live code:\n"
        + "\n".join(sorted(offenders))
    )
