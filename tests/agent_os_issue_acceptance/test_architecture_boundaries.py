from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "scripts" / "agent_os_issue_acceptance"

DOMAIN_RULES: tuple[tuple[str, frozenset[str], tuple[str, ...]], ...] = (
    (
        "scanner",
        frozenset({"issueplan_scanner", "parse_issue"}),
        (),
    ),
    (
        "acceptance",
        frozenset(
            {
                "legacy_preflight",
                "linked_issue",
                "metadata_validation",
                "models",
                "parse_pr",
                "path_contract",
                "policy",
                "readiness",
                "report",
                "reuse_readiness",
            }
        ),
        (),
    ),
    (
        "retrieval",
        frozenset({"github_issue_source", "issue_scanner"}),
        (),
    ),
    (
        "planning",
        frozenset(),
        ("batch_",),
    ),
    (
        "handoff",
        frozenset({"scheduler_handoff"}),
        (),
    ),
    (
        "current_state",
        frozenset({"issueplan_current_state"}),
        (),
    ),
    (
        "approval",
        frozenset({"approval_records", "approved_execution_projection"}),
        (),
    ),
    (
        "reporting",
        frozenset(
            {
                "acceptance_report_transport",
                "cli",
                "documentation_advisory",
                "documentation_gap_report",
                "sprint_dashboard",
            }
        ),
        (),
    ),
    (
        "facade",
        frozenset({"__init__"}),
        (),
    ),
)

# The direction follows the merged #464 contract. Reporting is an output domain and
# may consume supplied immutable upstream evidence; upstream domains may not import it.
FORBIDDEN_DOMAIN_IMPORTS = {
    "scanner": frozenset({"planning", "handoff", "approval", "reporting"}),
    "retrieval": frozenset({"planning", "handoff", "approval", "reporting"}),
    "acceptance": frozenset({"planning", "handoff", "approval", "reporting"}),
    "planning": frozenset({"handoff", "approval", "reporting"}),
    "handoff": frozenset({"approval", "reporting"}),
    "current_state": frozenset({"approval", "reporting"}),
    "approval": frozenset({"reporting"}),
    "reporting": frozenset(),
}

EXPECTED_PUBLIC_FACADE = (
    "APPROVAL_INVALIDATION_REASON_CODES",
    "APPROVAL_RECORD_SCHEMA_VERSION",
    "APPROVED_EXECUTION_PROJECTION_SCHEMA_VERSION",
    "ApprovalApplicabilityResult",
    "ApprovalBinding",
    "ApprovalKind",
    "ApprovalRecord",
    "ApprovalState",
    "ApprovedExecutionProjection",
    "ApprovedExecutionProjectionResult",
    "BatchConflictRun",
    "BatchPlanningResult",
    "Compatibility",
    "DecisionEvidence",
    "FinalHandoff",
    "ForbiddenPathCrossing",
    "GraphCheck",
    "GraphCheckResult",
    "GraphCheckRun",
    "HandoffCohort",
    "HandoffValidationOutcome",
    "HandoffValidationResult",
    "ISSUEPLAN_CURRENT_STATE_SCHEMA_VERSION",
    "IssueBatchGraph",
    "IssueBatchNode",
    "IssuePlanCurrentStateComparison",
    "IssuePlanCurrentStateEvidence",
    "IssuePlanCurrentStateOutcome",
    "IssuePlanSourceSnapshot",
    "PROVISIONAL_SCHEMA_VERSION",
    "PlanningClassification",
    "PlanningCohort",
    "ReadinessOutcome",
    "ReadinessResult",
    "RecommendationAction",
    "RecommendationEvidence",
    "RiskCategory",
    "RiskEvidence",
    "RiskSeverity",
    "RiskStatus",
    "SCHEMA_VERSION",
    "SUPPORTED_CONTRACT_VERSIONS",
    "SUPPORTED_PLANNING_RESULT_VERSIONS",
    "SchedulerPlanningHandoff",
    "SourceEvidence",
    "SprintLaneEvidence",
    "SprintMode",
    "SuppliedSprintEvidence",
    "ValidationEvidence",
    "build_approval_candidate",
    "build_approved_execution_projection",
    "build_issue_batch_graph",
    "build_issueplan_current_state_evidence",
    "canonical_sprint_payload",
    "compare_issueplan_current_state",
    "compute_graph_digest",
    "compute_handoff_digest",
    "compute_issueplan_current_state_fingerprint",
    "compute_planning_result_digest",
    "entity_id_collision_check",
    "evaluate_acceptance",
    "evaluate_approval_applicability",
    "evaluate_base_batch_conflict_run",
    "evaluate_base_batch_conflicts",
    "evaluate_batch_plan",
    "evaluate_input_scope_coverage",
    "evaluate_issue_readiness",
    "evaluate_issue_readiness_with_labels",
    "load_issue_batch_fixture",
    "parse_issue_metadata",
    "project_issue_metadata",
    "record_approval_decision",
    "recommended_merge_order",
    "render_execution_prompt",
    "render_report",
    "render_risk_review_prompt",
    "render_sprint_dashboard",
    "render_sprint_governance_report",
    "risk_delta",
    "run_graph_checks",
    "scan_issue_metadata",
    "scanner_manual_review_items",
    "serialize_approved_execution_projection",
    "serialize_scheduler_planning_handoff",
    "serialize_sprint_evidence",
    "unresolved_dependency_check",
    "validate_scheduler_planning_handoff",
)


def _production_modules() -> dict[str, Path]:
    return {path.stem: path for path in sorted(PACKAGE_ROOT.glob("*.py"))}


def _domain_matches(module_name: str) -> list[str]:
    return [
        domain
        for domain, exact_names, prefixes in DOMAIN_RULES
        if module_name in exact_names
        or any(module_name.startswith(prefix) for prefix in prefixes)
    ]


def _domain_for(module_name: str) -> str:
    matches = _domain_matches(module_name)
    assert len(matches) == 1, (
        f"{module_name}.py must have exactly one architecture-domain classification; "
        f"found {matches or 'none'}"
    )
    return matches[0]


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _local_imports(tree: ast.AST) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level:
            if node.module:
                imports.add(node.module.split(".", 1)[0])
            else:
                imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                prefix = "scripts.agent_os_issue_acceptance."
                if alias.name.startswith(prefix):
                    imports.add(alias.name[len(prefix) :].split(".", 1)[0])
    return imports


def _external_imports(tree: ast.AST) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.add(node.module)
    return imports


def _yaml_load_calls(tree: ast.AST) -> list[ast.Call]:
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if isinstance(function, ast.Attribute):
            if (
                isinstance(function.value, ast.Name)
                and function.value.id in {"yaml", "pyyaml"}
                and function.attr in {"load", "safe_load"}
            ):
                calls.append(node)
        elif isinstance(function, ast.Name) and function.id in {"safe_load", "yaml_load"}:
            calls.append(node)
    return calls


def _assigned_string_sequence(tree: ast.Module, name: str) -> tuple[str, ...]:
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            continue
        assert isinstance(node.value, (ast.List, ast.Tuple)), (
            f"{name} must be a literal sequence"
        )
        values: list[str] = []
        for element in node.value.elts:
            assert isinstance(element, ast.Constant) and isinstance(element.value, str), (
                f"{name} must contain only string literals"
            )
            values.append(element.value)
        return tuple(values)
    raise AssertionError(f"{name} assignment not found")


def test_every_production_module_has_one_domain_classification() -> None:
    modules = _production_modules()
    assert modules, "issue-automation production modules were not found"

    for module_name in modules:
        _domain_for(module_name)


def test_dependency_direction_and_scheduler_runtime_boundary() -> None:
    modules = _production_modules()
    violations: list[str] = []

    for module_name, path in modules.items():
        source_domain = _domain_for(module_name)
        tree = _parse(path)

        if source_domain != "facade":
            for imported_module in sorted(_local_imports(tree)):
                if imported_module not in modules:
                    continue
                target_domain = _domain_for(imported_module)
                if target_domain in FORBIDDEN_DOMAIN_IMPORTS.get(
                    source_domain, frozenset()
                ):
                    violations.append(
                        f"{module_name}.py ({source_domain}) imports "
                        f"{imported_module}.py ({target_domain})"
                    )

        for imported_name in sorted(_external_imports(tree)):
            normalized = imported_name.replace("-", "_").lower()
            if "workflow_scheduler" in normalized:
                violations.append(
                    f"{module_name}.py imports Workflow Scheduler runtime module "
                    f"{imported_name!r}"
                )

    assert not violations, "Architecture dependency violations:\n- " + "\n- ".join(
        violations
    )


def test_issueplan_scanner_is_the_only_yaml_parser() -> None:
    parser_owners = {
        module_name
        for module_name, path in _production_modules().items()
        if _yaml_load_calls(_parse(path))
    }
    assert parser_owners == {"issueplan_scanner"}, (
        "The canonical IssuePlan scanner must remain the sole YAML parser; "
        f"found {sorted(parser_owners)}"
    )

    compatibility_tree = _parse(PACKAGE_ROOT / "parse_issue.py")
    assert not _yaml_load_calls(compatibility_tree), (
        "parse_issue.py is a compatibility facade and must not contain a second parser"
    )


def test_public_facade_matches_reviewed_baseline() -> None:
    facade = _assigned_string_sequence(_parse(PACKAGE_ROOT / "__init__.py"), "__all__")
    assert facade == EXPECTED_PUBLIC_FACADE, (
        "Package facade changed without explicit compatibility evidence. "
        "Update the governed baseline only through a separately authorized facade "
        "decision."
    )


def test_supported_evaluate_acceptance_facade_remains_exported() -> None:
    facade = _assigned_string_sequence(_parse(PACKAGE_ROOT / "__init__.py"), "__all__")
    assert "evaluate_acceptance" in facade
