"""#2826 boundary: every required continuation classifier stays invoked.

Phase 1 gate: prove the continuation classifiers are invoked at their mandated
seams on the general path. This AST walk fails if a future refactor silently
unwires one -- a classifier with no production call site is either wired or
retired under the wire-or-retire discipline, never left as a dead boundary.

Mirrors the A1 boundary-test pattern in
tests/agent_os_issue_acceptance/test_architecture_boundaries.py.
"""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

PRODUCTION_ROOTS = ("scripts", "08_Tooling", "src")

# classifier -> defining module filename (basename). These seven are the
# required continuation classifiers after the #2826 wire-or-retire pass:
# decide_validated_workspace_continuation and
# classify_preferred_surface_limitation were retired (zero production call
# sites; invariants owned in prose by the Safe Implementation Lane standard
# and the chatgpt-orchestrator overlay respectively).
REQUIRED_CLASSIFIERS = {
    "drive_governed_continuation": "continuation_driver.py",
    "classify_post_selection_continuation": "post_selection_continuation.py",
    "continuation_payload": "continuation_driver.py",
    "completion_continuation_payload": "continuation_driver.py",
    "evaluate_investigation_completion_admission": (
        "investigation_completion_admission.py"
    ),
    "resolve_governed_route_preflight": "governed_route_preflight.py",
    "evaluate_finite_batch_admission": "finite_batch_admission.py",
}

# Retired under #2826 wire-or-retire: zero production call sites on
# 9e6fcad5, invariants owned elsewhere in prose. Must not reappear as
# unwired production code.
RETIRED_CLASSIFIERS = (
    "decide_validated_workspace_continuation",
    "classify_preferred_surface_limitation",
)


def _production_files():
    for root in PRODUCTION_ROOTS:
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            parts = path.parts
            if "build" in parts:
                continue  # untracked packaging output, not production source
            if any(part == "tests" or part.startswith("test_") for part in parts):
                continue
            yield path


def _collect():
    definitions: dict[str, list[str]] = {}
    calls: dict[str, list[str]] = {}
    for path in _production_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        rel = str(path.relative_to(REPO_ROOT))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                definitions.setdefault(node.name, []).append(rel)
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    calls.setdefault(func.id, []).append(rel)
                elif isinstance(func, ast.Attribute):
                    calls.setdefault(func.attr, []).append(rel)
    return definitions, calls


_DEFINITIONS, _CALLS = _collect()


def test_every_required_classifier_is_defined_in_its_canonical_module():
    for name, module in REQUIRED_CLASSIFIERS.items():
        definers = _DEFINITIONS.get(name, [])
        assert any(
            d.endswith(module) for d in definers
        ), f"{name} is not defined in {module}; definers: {definers}"


def test_every_required_classifier_retains_a_production_call_site():
    for name, module in REQUIRED_CLASSIFIERS.items():
        definers = {d for d in _DEFINITIONS.get(name, []) if d.endswith(module)}
        call_sites = [
            site for site in _CALLS.get(name, []) if site not in definers
        ]
        assert call_sites, (
            f"{name} has no production call site outside {module}: "
            "wire it at its mandated seam or retire it under the "
            "wire-or-retire discipline"
        )


def test_retired_classifiers_have_no_production_definition_or_call_site():
    for name in RETIRED_CLASSIFIERS:
        assert name not in _DEFINITIONS, (
            f"{name} was retired under #2826 but is defined in production: "
            f"{_DEFINITIONS[name]}"
        )
        assert name not in _CALLS, (
            f"{name} was retired under #2826 but is called in production: "
            f"{_CALLS[name]}"
        )
