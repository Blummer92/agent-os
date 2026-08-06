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
        frozenset(
            {
                "approval_records",
                "approved_execution_projection",
                "issue_operational_state",
                "lifecycle_mutation_guard",
                "merge_authorization",
            }
        ),
        (),
    ),
    (
        "mode",
        frozenset({"executor_route", "operating_mode"}),
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
                "documentation_metrics",
                "sprint_dashboard",
                "sprint_evidence_ingestion",
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
# Mode sits downstream of approval: it consumes canonical approval-domain contracts
# (the IssueOperationalState projection) and must not import reporting, and no domain
# upstream of it may import mode.
FORBIDDEN_DOMAIN_IMPORTS = {
    "scanner": frozenset({"planning", "handoff", "approval", "mode", "reporting"}),
    "retrieval": frozenset({"planning", "handoff", "approval", "mode", "reporting"}),
    "acceptance": frozenset({"planning", "handoff", "approval", "mode", "reporting"}),
    "planning": frozenset({"handoff", "approval", "mode", "reporting"}),
    "handoff": frozenset({"approval", "mode", "reporting"}),
    "current_state": frozenset({"approval", "mode", "reporting"}),
    "approval": frozenset({"mode", "reporting"}),
    "mode": frozenset({"reporting"}),
    "reporting": frozenset(),
}

EXPECTED_PUBLIC_FACADE = (
    "APPROVAL_INVALIDATION_REASON_CODES",
    "APPROVAL_RECORD_SCHEMA_VERSION",
    "APPROVED_EXECUTION_PROJECTION_SCHEMA_VERSION",
    "MERGE_AUTHORIZATION_REASON_CODES",
    "MERGE_AUTHORIZATION_SCHEMA_VERSION",
    "MERGE_EXECUTION_OBSERVATION_SCHEMA_VERSION",
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
    "GitHubIssuePageReader",
    "GitHubIssueRecord",
    "GitHubIssueSource",
    "IssueDependency",
    "IssueMetadata",
    "IssuePlan",
    "IssuePlanCandidate",
    "IssuePlanCandidateIdentity",
    "IssuePlanConflict",
    "IssuePlanDiagnostic",
    "IssuePlanDocument",
    "IssuePlanField",
    "IssuePlanIdentity",
    "IssuePlanParseResult",
    "IssuePlanSource",
    "IssuePlanStatus",
    "IssueRecord",
    "IssueScanError",
    "IssueScanResult",
    "IssueScanner",
    "IssueStateFilter",
    "MergeAuthorizationApplicabilityResult",
    "MergeAuthorizationBinding",
    "MergeAuthorizationEvidence",
    "MergeAuthorizationRecord",
    "MergeAuthorizationState",
    "MergeExecutionObservation",
    "ParsedPr",
    "PlannerCheckpoint",
    "PrIdentity",
    "ReadinessCheck",
    "ReadinessOutcome",
    "ReadinessResult",
    "RepositoryRef",
    "SchedulerHandoff",
    "SchedulerTask",
    "SourceLocation",
    "StateTransition",
    "TaskDependency",
    "TaskExecutionClass",
    "ValidationResult",
    "build_approval_record",
    "build_batch_plan",
    "build_issue_plan_document",
    "build_merge_authorization_record",
    "build_scheduler_handoff",
    "evaluate_approval_applicability",
    "evaluate_merge_authorization_applicability",
    "parse_issue_metadata",
    "parse_issue_plan_candidates",
    "parse_issue_plan_document",
    "parse_issue_plan_source",
    "parse_pr",
    "project_approved_execution",
    "scan_connected_issues",
    "scan_connected_open_issues",
    "scan_issues",
    "scan_open_issues",
    "validate_batch_plan",
    "validate_issue_plan",
    "validate_scheduler_handoff",
)


def _module_name(path: Path) -> str:
    return path.stem


def _domain_for(module: str) -> str:
    matches = []
    for domain, exact_modules, prefixes in DOMAIN_RULES:
        if module in exact_modules or any(module.startswith(prefix) for prefix in prefixes):
            matches.append(domain)
    assert len(matches) == 1, f"{module} belongs to domains {matches}"
    return matches[0]


def _package_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level == 1 and node.module:
                imports.add(node.module.split(".", 1)[0])
            elif node.level == 0 and node.module:
                prefix = "scripts.agent_os_issue_acceptance."
                if node.module.startswith(prefix):
                    imports.add(node.module[len(prefix) :].split(".", 1)[0])
        elif isinstance(node, ast.Import):
            prefix = "scripts.agent_os_issue_acceptance."
            for alias in node.names:
                if alias.name.startswith(prefix):
                    imports.add(alias.name[len(prefix) :].split(".", 1)[0])
    return imports


def _production_modules() -> dict[str, Path]:
    return {
        path.stem: path
        for path in PACKAGE_ROOT.glob("*.py")
        if path.name != "__main__.py"
    }


def test_every_production_module_has_exactly_one_domain() -> None:
    modules = _production_modules()
    for module in sorted(modules):
        _domain_for(module)


def test_domain_dependency_direction_is_enforced() -> None:
    modules = _production_modules()
    for source_module, path in sorted(modules.items()):
        source_domain = _domain_for(source_module)
        forbidden = FORBIDDEN_DOMAIN_IMPORTS[source_domain]
        for imported_module in _package_imports(path):
            if imported_module not in modules:
                continue
            imported_domain = _domain_for(imported_module)
            assert imported_domain not in forbidden, (
                f"{source_module} ({source_domain}) imports {imported_module} "
                f"({imported_domain})"
            )


def test_public_facade_stays_intentional() -> None:
    facade = PACKAGE_ROOT / "__init__.py"
    tree = ast.parse(facade.read_text(encoding="utf-8"), filename=str(facade))
    exported: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                exported.add(alias.asname or alias.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    assert isinstance(node.value, (ast.Tuple, ast.List))
                    exported.update(
                        element.value
                        for element in node.value.elts
                        if isinstance(element, ast.Constant)
                        and isinstance(element.value, str)
                    )
    assert tuple(sorted(exported)) == tuple(sorted(EXPECTED_PUBLIC_FACADE))


def test_facade_does_not_export_private_or_speculative_interfaces() -> None:
    facade = (PACKAGE_ROOT / "__init__.py").read_text(encoding="utf-8")
    prohibited_tokens = (
        "IssueOperationalState",
        "AgentOperatingModeDecision",
        "ExecutorRouteDecision",
        "ExecutorRouteEvidence",
        "evaluate_executor_route",
        "format_executor_handoff",
    )
    for token in prohibited_tokens:
        assert token not in facade


def test_mode_domain_consumes_only_upstream_contracts() -> None:
    modules = _production_modules()
    for module in ("operating_mode", "executor_route"):
        imports = _package_imports(modules[module])
        assert "report" not in imports
        assert "sprint_dashboard" not in imports
        assert "scheduler_handoff" not in imports


def test_no_upstream_domain_imports_mode() -> None:
    modules = _production_modules()
    upstream_domains = {
        "scanner",
        "acceptance",
        "retrieval",
        "planning",
        "handoff",
        "current_state",
        "approval",
    }
    for source_module, path in sorted(modules.items()):
        if _domain_for(source_module) not in upstream_domains:
            continue
        imported_domains = {
            _domain_for(imported)
            for imported in _package_imports(path)
            if imported in modules
        }
        assert "mode" not in imported_domains, source_module


def test_reporting_may_consume_mode_but_not_reverse() -> None:
    modules = _production_modules()
    for source_module, path in sorted(modules.items()):
        if _domain_for(source_module) != "mode":
            continue
        imported_domains = {
            _domain_for(imported)
            for imported in _package_imports(path)
            if imported in modules
        }
        assert "reporting" not in imported_domains, source_module


def test_direct_import_policy_keeps_new_interfaces_out_of_facade() -> None:
    facade = (PACKAGE_ROOT / "__init__.py").read_text(encoding="utf-8")
    for module in ("issue_operational_state", "operating_mode", "executor_route"):
        assert f"from .{module} import" not in facade
        assert f"from scripts.agent_os_issue_acceptance.{module} import" not in facade
