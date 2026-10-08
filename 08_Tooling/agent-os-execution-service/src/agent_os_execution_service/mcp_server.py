"""MCP protocol binding for the bounded Agent OS ChatGPT facade (#1966 / #1988 / #2363 / #2487 / #2331 / #2523 / #2528 / #2607 / #2612)."""

from __future__ import annotations

from dataclasses import asdict

from mcp.server import MCPServer

from instructional_workflow_contracts import ValidationStatus, validate_request_interpretation
from instructional_workflow_contracts.request_interpretation import (
    RequestInterpretation,
    bind_current_image_reference,
)

from scripts.agent_os_execution_interface.continuation_driver import completion_continuation_payload
from scripts.agent_os_execution_interface.investigation_completion_admission import evaluate_investigation_completion_admission
from scripts.agent_os_issue_acceptance.primary_pr_creation_admission import (
    ActivePrimaryPr,
    BatchIssuePrimaryPrEvidence,
    evaluate_batch_primary_pr_packaging,
    evaluate_primary_pr_creation_admission,
)
from scripts.agent_os_issue_acceptance.lifecycle_mutation_guard import (
    IssueClosureAdmission,
    LifecycleMutationAuthorization,
    LifecycleStateSnapshot,
    evaluate_lifecycle_mutation,
)
from scripts.agent_os_issue_labels.ready_for_review_admission import (
    evaluate_ready_for_review_admission,
)
from scripts.agent_os_github_target_guard import (
    GitHubTargetEvidence,
    GitHubTargetKind,
    check_operation_compatibility,
)

from .bulk_repair_facade import classify_bulk_repair_continuation
from .connected_issue_creation_facade import plan_connected_issue_creation_for_host
from .governed_mutation_seams_facade import (
    evaluate_issue_comment_mutation_boundary_for_host,
    project_lane_post_pr_issue_reconciliation_for_host,
)
from scripts.agent_os_issue_labels.connected_issue_creation import DuplicateCandidateEvidence
from .issue_batch_completion import classify_issue_batch_completion
from .issue_start_lesson_preflight import activate_issue_start_lesson_preflight
from .lesson_reader_composition import resolve_lesson_read_route
from .mcp_facade import (
    activate_agent_os_failed_repair,
    admit_agent_os_failed_repair,
    classify_agent_os_continuation,
    classify_agent_os_mission_completion,
    plan_agent_os_continuation,
)
from scripts.agent_os_issue_acceptance.zero_job_validation_recovery import ZeroJobAdmissionEvidence
from agent_os_execution_service.failed_repair_admission import DiagnosticSurfaceEvidence
from scripts.agent_os_issue_acceptance.validation_failure_classifier import ValidationFailureEvidence
from agent_os_execution_service.validation_supersession import ValidationSupersessionEvidence
from workflow_scheduler.execution.recovery_progress import RecoverySemanticEvidence

mcp = MCPServer("Agent OS")


class GitHubTargetRefused(ValueError):
    """Fail-closed signal from the GitHub target-identity entry guard.

    Raised before any other tool logic when an issue_number/pr_number path
    cannot construct canonical target evidence: ambiguous or missing target,
    a non-positive or non-integer number, a malformed repository, or a target
    kind incompatible with the requested operation (e.g. an issue target
    routed into a pull-request operation). Carries a stable reason_code; never
    grants authority and never manufactures target state.
    """

    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(f"{reason_code}: {detail}")
        self.reason_code = reason_code
        self.detail = detail


# Operation -> permitted target kinds, mirroring
# scripts.agent_os_github_target_guard._OPERATION_KINDS for the
# repository-agnostic tool paths that cannot bind a canonical URL.
# Parity is pinned by tests/test_mcp_github_target_guard.py.
_GITHUB_TARGET_OPERATION_KINDS: dict[str, tuple[GitHubTargetKind, ...]] = {
    "read-issue": (GitHubTargetKind.ISSUE,),
    "update-issue": (GitHubTargetKind.ISSUE,),
    "read-pull-request": (GitHubTargetKind.PULL_REQUEST,),
    "review-pull-request": (GitHubTargetKind.PULL_REQUEST,),
    "merge-pull-request": (GitHubTargetKind.PULL_REQUEST,),
}


def _github_target_entry_guard(
    *,
    repository: str | None,
    issue_number: int | None = None,
    pr_number: int | None = None,
    operation: str,
) -> GitHubTargetEvidence | None:
    """Construct canonical GitHub target evidence at the MCP boundary.

    Every MCP tool path taking issue_number or pr_number invokes this guard
    before any other logic. The declared kind comes from the parameter name
    (issue_number -> issue, pr_number -> pull-request); a kind incompatible
    with the requested operation fails closed instead of being coerced.

    Returns the constructed GitHubTargetEvidence when a repository is
    supplied; repository-agnostic tools still get the number/kind/operation
    checks and receive None. Raises GitHubTargetRefused (fail-closed) on any
    mismatch. Performs no I/O and grants no authority.
    """
    if (issue_number is None) == (pr_number is None):
        raise GitHubTargetRefused(
            "github-target-ambiguous-or-missing",
            "exactly one of issue_number or pr_number is required",
        )
    kind = (
        GitHubTargetKind.ISSUE if issue_number is not None else GitHubTargetKind.PULL_REQUEST
    )
    number = issue_number if issue_number is not None else pr_number
    if type(number) is not int or number < 1:
        raise GitHubTargetRefused(
            "github-target-number-invalid",
            "issue_number/pr_number must be a positive built-in integer",
        )
    if repository is None:
        allowed = _GITHUB_TARGET_OPERATION_KINDS.get(operation)
        if allowed is None or kind not in allowed:
            raise GitHubTargetRefused(
                "github-target-kind-incompatible",
                f"target kind {kind.value} is not compatible with operation {operation}",
            )
        return None
    try:
        target = GitHubTargetEvidence(
            repository=repository,
            number=number,
            kind=kind,
            canonical_url=(
                "https://github.com/"
                f"{repository}/"
                f"{'pull' if kind is GitHubTargetKind.PULL_REQUEST else 'issues'}/"
                f"{number}"
            ),
        )
    except (TypeError, ValueError) as exc:
        raise GitHubTargetRefused("github-target-identity-invalid", str(exc)) from exc
    compatibility = check_operation_compatibility(target, operation)
    if not compatibility.compatible:
        raise GitHubTargetRefused(
            "github-target-kind-incompatible", compatibility.reason
        )
    return target


def _lesson_route(lesson_rows: list[dict[str, object]] | None):
    if lesson_rows is not None:
        return (lambda _query: {"results": lesson_rows}, "diagnostic-override", "diagnostic-lesson-rows", False)
    route = resolve_lesson_read_route()
    return (route.execute_read, route.status.value, route.reason_code, route.canonical_source_unavailable)


def _with_lesson_route(result: dict[str, object], route_status: str, reason_code: str, canonical_source_unavailable: bool) -> dict[str, object]:
    return {**result, "lesson_read_route_status": route_status, "lesson_read_route_reason_code": reason_code, "canonical_lessons_source_unavailable": canonical_source_unavailable}


def _deferred_lesson_read():
    """Resolve the provider route only when CKR6 actually performs a read."""
    state: dict[str, object] = {
        "resolved": False,
        "execute_read": None,
        "status": "not-needed",
        "reason_code": "lesson-retrieval-not-required",
        "canonical_source_unavailable": False,
    }

    def execute_read(query):
        if not state["resolved"]:
            reader, status, reason_code, source_unavailable = _lesson_route(None)
            state.update(
                resolved=True,
                execute_read=reader,
                status=status,
                reason_code=reason_code,
                canonical_source_unavailable=source_unavailable,
            )
        reader = state["execute_read"]
        if reader is None:
            raise RuntimeError("lesson read route unavailable on current execution surface")
        return reader(query)

    return execute_read, state


@mcp.tool()
def bind_agent_os_request_interpretation_tool(request: dict[str, object]) -> dict[str, object]:
    """Bind an event/intake request and current image reference before dispatch."""
    result = validate_request_interpretation(request)
    record = result.record
    image_reference_admitted = True
    image_reference_details: tuple[str, ...] = ()
    if record is not None:
        try:
            image_binding = bind_current_image_reference(
                RequestInterpretation(record=record)
            )
            image_reference_admitted = (
                not image_binding.required or image_binding.bound
            )
            image_reference_details = image_binding.reason_codes
        except (TypeError, ValueError):
            image_reference_admitted = False
            image_reference_details = ("image-reference.missing",)
    return {
        "status": result.status.value,
        "record_id": record.record_id if record is not None else None,
        "record_fingerprint": record.fingerprint if record is not None else None,
        "raw_input_digest": record.to_dict()["raw_input_digest"] if record is not None else None,
        "reason_codes": list(result.reason_codes),
        "details": [*result.details, *image_reference_details],
        "dispatch_admitted": (
            result.status is ValidationStatus.VALID and image_reference_admitted
        ),
        "execution_authorized": False,
        "github_writes_authorized": False,
        "merge_authorized": False,
        "closure_authorized": False,
        "side_effects_performed": False,
    }

@mcp.tool()
def plan_connected_issue_creation_tool(
    repository: str,
    issue_body: str,
    duplicate_review_disposition: str | None = None,
    canonical_issue_number: int | None = None,
    distinct_repair_seam: bool = False,
    candidate_evidence: list[dict[str, object]] | None = None,
    candidate_enumeration_complete: bool = False,
) -> dict[str, object]:
    """Project canonical connected-issue admission evidence without performing writes."""
    if canonical_issue_number is not None:
        _github_target_entry_guard(
            repository=repository,
            issue_number=canonical_issue_number,
            operation="read-issue",
        )
    for _candidate_item in candidate_evidence or ():
        _github_target_entry_guard(
            repository=repository,
            issue_number=_candidate_item["issue_number"],
            operation="read-issue",
        )
    inspected = tuple(
        DuplicateCandidateEvidence(
            issue_number=item["issue_number"],
            state=item["state"],
            objective_evidence=item["objective_evidence"],
            causal_seam_evidence=item["causal_seam_evidence"],
            acceptance_evidence=item["acceptance_evidence"],
            boundary_evidence=item["boundary_evidence"],
        )
        for item in (candidate_evidence or [])
    )
    return plan_connected_issue_creation_for_host(
        repository=repository,
        issue_body=issue_body,
        duplicate_review_disposition=duplicate_review_disposition,
        canonical_issue_number=canonical_issue_number,
        distinct_repair_seam=distinct_repair_seam,
        candidate_evidence=inspected,
        candidate_enumeration_complete=candidate_enumeration_complete,
    )

@mcp.tool()
def plan_agent_os_continuation_tool(repository: str, issue_number: int, canonical_handoff_id: str | None = None) -> dict[str, object]:
    _github_target_entry_guard(
        repository=repository, issue_number=issue_number, operation="read-issue"
    )
    return dict(plan_agent_os_continuation(repository=repository, issue_number=issue_number, canonical_handoff_id=canonical_handoff_id))


@mcp.tool()
def admit_agent_os_primary_pr_creation_tool(issue_number: int, issue_open: bool, evidence_current: bool, active_primary_prs: list[dict[str, object]], changed_files: int, in_scope_changed_files: int, branch_exists: bool = False, canonical_no_diff_permitted: bool = False) -> dict[str, object]:
    """Classify create/reuse/conflict immediately before Draft PR materialization."""
    _github_target_entry_guard(
        repository=None, issue_number=issue_number, operation="read-issue"
    )
    claims = tuple(
        ActivePrimaryPr(
            pull_request_number=item["pull_request_number"],
            branch=item["branch"],
            head_sha=item["head_sha"],
        )
        for item in active_primary_prs
    )
    result = evaluate_primary_pr_creation_admission(
        issue_number=issue_number,
        issue_open=issue_open,
        evidence_current=evidence_current,
        active_primary_prs=claims,
        changed_files=changed_files,
        in_scope_changed_files=in_scope_changed_files,
        branch_exists=branch_exists,
        canonical_no_diff_permitted=canonical_no_diff_permitted,
    )
    return {
        "action": result.action.value,
        "creation_admitted": result.creation_admitted,
        "existing_pull_request_number": result.existing_pull_request_number,
        "reason_codes": list(result.reason_codes),
        "github_writes_authorized": result.github_writes_authorized,
    }


@mcp.tool()
def admit_agent_os_batch_pr_packaging_tool(issue_evidence: list[dict[str, object]], evidence_current: bool) -> dict[str, object]:
    """Preserve independent primary-PR lineage across one batch (#2447)."""
    for _batch_item in issue_evidence:
        _github_target_entry_guard(
            repository=None,
            issue_number=_batch_item["issue_number"],
            operation="read-issue",
        )
    evidence = tuple(
        BatchIssuePrimaryPrEvidence(
            issue_number=item["issue_number"],
            issue_open=item["issue_open"],
            objective_ref=item["objective_ref"],
            changed_files=item["changed_files"],
            in_scope_changed_files=item["in_scope_changed_files"],
            branch_exists=item.get("branch_exists", False),
            canonical_no_diff_permitted=item.get("canonical_no_diff_permitted", False),
            active_primary_prs=tuple(
                ActivePrimaryPr(
                    pull_request_number=claim["pull_request_number"],
                    branch=claim["branch"],
                    head_sha=claim["head_sha"],
                )
                for claim in item.get("active_primary_prs", ())
            ),
        )
        for item in issue_evidence
    )
    result = evaluate_batch_primary_pr_packaging(issue_evidence=evidence, evidence_current=evidence_current)
    return {
        "packaging_admitted": result.packaging_admitted,
        "issue_numbers": list(result.issue_numbers),
        "per_issue": [
            {
                "issue_number": number,
                "action": admission.action.value,
                "creation_admitted": admission.creation_admitted,
                "existing_pull_request_number": admission.existing_pull_request_number,
                "reason_codes": list(admission.reason_codes),
            }
            for number, admission in result.per_issue_admissions
        ],
        "reason_codes": list(result.reason_codes),
        "github_writes_authorized": result.github_writes_authorized,
    }


@mcp.tool()
def activate_agent_os_issue_start_lessons_tool(repository: str, issue_number: int, task_reference: str, ecosystem_hints: tuple[str, ...] = (), language_hints: tuple[str, ...] = (), library_hints: tuple[str, ...] = (), capability_keywords: tuple[str, ...] = (), target_path_hints: tuple[str, ...] = (), canonical_rule_refs: tuple[str, ...] = (), known_knowledge_refs: tuple[str, ...] = (), specialized_knowledge_required: bool | None = None, lesson_rows: list[dict[str, object]] | None = None) -> dict[str, object]:
    _github_target_entry_guard(
        repository=repository, issue_number=issue_number, operation="read-issue"
    )
    if lesson_rows is not None:
        execute_read, route_status, reason_code, source_unavailable = _lesson_route(lesson_rows)
        result = activate_issue_start_lesson_preflight(repository=repository, issue_number=issue_number, task_reference=task_reference, ecosystem_hints=ecosystem_hints, language_hints=language_hints, library_hints=library_hints, capability_keywords=capability_keywords, target_path_hints=target_path_hints, canonical_rule_refs=canonical_rule_refs, known_knowledge_refs=known_knowledge_refs, specialized_knowledge_required=specialized_knowledge_required, execute_read=execute_read)
        return _with_lesson_route(result, route_status, reason_code, source_unavailable)

    execute_read, route_state = _deferred_lesson_read()
    result = activate_issue_start_lesson_preflight(repository=repository, issue_number=issue_number, task_reference=task_reference, ecosystem_hints=ecosystem_hints, language_hints=language_hints, library_hints=library_hints, capability_keywords=capability_keywords, target_path_hints=target_path_hints, canonical_rule_refs=canonical_rule_refs, known_knowledge_refs=known_knowledge_refs, specialized_knowledge_required=specialized_knowledge_required, execute_read=execute_read)
    return _with_lesson_route(
        result,
        str(route_state["status"]),
        str(route_state["reason_code"]),
        bool(route_state["canonical_source_unavailable"]),
    )


@mcp.tool()
def activate_agent_os_failed_repair_tool(repository: str, issue_number: int, attempt_id: str, failed_hypothesis: str, result_summary: str, task_reference: str, ecosystem_hints: tuple[str, ...] = (), language_hints: tuple[str, ...] = (), library_hints: tuple[str, ...] = (), capability_keywords: tuple[str, ...] = (), target_path_hints: tuple[str, ...] = (), canonical_rule_refs: tuple[str, ...] = (), known_knowledge_refs: tuple[str, ...] = (), specialized_knowledge_required: bool | None = None, lesson_rows: list[dict[str, object]] | None = None, repair_context: str = "failed-pr-repair") -> dict[str, object]:
    _github_target_entry_guard(
        repository=repository, issue_number=issue_number, operation="read-issue"
    )
    execute_read, route_status, reason_code, source_unavailable = _lesson_route(lesson_rows)
    result = activate_agent_os_failed_repair(repository=repository, issue_number=issue_number, attempt_id=attempt_id, failed_hypothesis=failed_hypothesis, result_summary=result_summary, task_reference=task_reference, ecosystem_hints=ecosystem_hints, language_hints=language_hints, library_hints=library_hints, capability_keywords=capability_keywords, target_path_hints=target_path_hints, canonical_rule_refs=canonical_rule_refs, known_knowledge_refs=known_knowledge_refs, specialized_knowledge_required=specialized_knowledge_required, execute_read=execute_read, repair_context=repair_context)
    return _with_lesson_route(result, route_status, reason_code, source_unavailable)


@mcp.tool()
def admit_agent_os_failed_repair_tool(activation_result: dict[str, object], check_state: str, required_check_configuration_state: str, review_state: str, branch_freshness: str, mergeability: str, *, current: RecoverySemanticEvidence | None = None, prior: RecoverySemanticEvidence | None = None, prior_transition_fingerprint: str | None = None, zero_job: ZeroJobAdmissionEvidence | None = None, diagnostics: DiagnosticSurfaceEvidence | None = None, validation_head: ValidationSupersessionEvidence | None = None, validation_failure: ValidationFailureEvidence | None = None) -> dict[str, object]:
    return admit_agent_os_failed_repair(activation_result=activation_result, check_state=check_state, required_check_configuration_state=required_check_configuration_state, review_state=review_state, branch_freshness=branch_freshness, mergeability=mergeability, current=current, prior=prior, prior_transition_fingerprint=prior_transition_fingerprint, zero_job=zero_job, diagnostics=diagnostics, validation_head=validation_head, validation_failure=validation_failure)


def _ready_review_closure_admissions(
    items: list[dict[str, object]] | None,
) -> tuple[IssueClosureAdmission, ...]:
    """Project canonical close-issue authorization evidence (#3157) for the Ready pre-step.

    Each evidence item carries the canonical authorization identity
    (repository, issue, authorizer, decision, observed revision). The admitted
    `IssueClosureAdmission` structs are derived through
    `evaluate_lifecycle_mutation`, so detected closing targets are compared
    against digest-bound authorization evidence, never caller-supplied target
    strings. Malformed or unverifiable items raise: the Ready pre-step fails
    closed instead of treating them as absent.
    """
    admissions: list[IssueClosureAdmission] = []
    for item in items or ():
        authorization = LifecycleMutationAuthorization(
            schema_version="1.0",
            repository=item["repository"],
            issue_number=item["issue_number"],
            pull_request_number=None,
            authorized_mutations=("close-issue",),
            expected_source_head=None,
            expected_base_head=None,
            expected_pr_state="none",
            expected_merged=False,
            expected_issue_state="open",
            expected_review_state="unknown",
            expected_unresolved_threads=0,
            expected_lifecycle_labels=(),
            observed_at_revision=item["observed_at_revision"],
            state="authorized",
            authorizer_id=item["authorizer_id"],
            decision_id=item["decision_id"],
        )
        snapshot = LifecycleStateSnapshot(
            repository=item["repository"],
            issue_number=item["issue_number"],
            pull_request_number=None,
            source_head=None,
            base_head=None,
            pr_state="none",
            merged=False,
            issue_state="open",
            review_state="unknown",
            unresolved_threads=0,
            lifecycle_labels=(),
            observed_revision=item["observed_at_revision"],
        )
        admission = evaluate_lifecycle_mutation(authorization, snapshot, "close-issue")
        if not admission.admitted:
            raise ValueError("closure authorization evidence did not verify as admitted")
        admissions.append(
            IssueClosureAdmission(authorization=authorization, admission=admission)
        )
    return tuple(admissions)


def _refused_ready_review_projection(
    *,
    repository: str,
    pr_number: int,
    expected_head_sha: str,
    observed_head_sha: str,
    validation_head_sha: str,
    expected_body_revision: str | None,
    observed_body_revision: str | None,
    reason_codes: tuple[str, ...],
    next_action: str,
) -> dict[str, object]:
    """Fail-closed Ready projection when pre-evaluation bindings refuse the transition."""
    return {
        "repository": repository,
        "pr_number": pr_number,
        "expected_head_sha": expected_head_sha,
        "observed_head_sha": observed_head_sha,
        "validation_head_sha": validation_head_sha,
        "expected_body_revision": expected_body_revision,
        "observed_body_revision": observed_body_revision,
        "transition_admissible": False,
        "provisional_ready": False,
        "rollback_to_draft_required": False,
        "reason_codes": list(reason_codes),
        "next_action": next_action,
        "authorized_closing_targets": [],
        "ready_for_review_authorized": False,
        "merge_authorized": False,
        "issue_closure_authorized": False,
        "workflow_authorized": False,
        "protected_setting_authorized": False,
        "production_authorized": False,
        "external_system_write_authorized": False,
    }


@mcp.tool()
def admit_agent_os_ready_for_review_tool(repository: str, pr_number: int, pr_lifecycle_state: str, expected_head_sha: str, observed_head_sha: str, validation_head_sha: str, validation_admission_mode: str, aggregate_status: str, focused_status: str, requested_changes: bool, blocking_unresolved: int, ready_for_review_authority_supplied: bool, pr_title: str, pr_body: str, closure_admissions: list[dict[str, object]] | None = None, expected_body_revision: str | None = None, observed_body_revision: str | None = None) -> dict[str, object]:
    """Project Draft -> Ready admission before the Ready transition (#3279).

    Binds the exact head SHA and the PR body revision: stale bindings are
    refused with named reason codes. GitHub-effective closing references in
    the PR title/body are detected with the single canonical parser consumed
    by `evaluate_ready_for_review_admission`; targets without canonical
    close-issue authorization refuse the transition
    (`unauthorized-closing-reference`).

    `validation_admission_mode` names the validation story the caller ran and
    belongs to the closed vocabulary exported by `ready_for_review_admission`
    (`FINAL_CANDIDATE_MODE` / `DRAFT_FOCUSED_MODE`); it is passed through
    verbatim. The server derives the effective mode from the authoritative
    aggregate evidence, so a successful exact-head authoritative aggregate
    proves final-candidate mode regardless of the label supplied (#3350), and
    an uninterpretable mode with any other aggregate state fails closed with
    `unknown-validation-admission-mode`. This projects admissibility only; it
    grants no merge, closure, workflow, protected-setting, production, or
    external-write authority.
    """
    _github_target_entry_guard(
        repository=repository, pr_number=pr_number, operation="review-pull-request"
    )
    if expected_body_revision is not None and observed_body_revision != expected_body_revision:
        return _refused_ready_review_projection(
            repository=repository,
            pr_number=pr_number,
            expected_head_sha=expected_head_sha,
            observed_head_sha=observed_head_sha,
            validation_head_sha=validation_head_sha,
            expected_body_revision=expected_body_revision,
            observed_body_revision=observed_body_revision,
            reason_codes=("stale-body-revision",),
            next_action="reacquire-pr-body-revision",
        )
    try:
        admissions = _ready_review_closure_admissions(closure_admissions)
    except (KeyError, TypeError, ValueError):
        return _refused_ready_review_projection(
            repository=repository,
            pr_number=pr_number,
            expected_head_sha=expected_head_sha,
            observed_head_sha=observed_head_sha,
            validation_head_sha=validation_head_sha,
            expected_body_revision=expected_body_revision,
            observed_body_revision=observed_body_revision,
            reason_codes=("closure-authorization-evidence-invalid",),
            next_action="supply-canonical-closure-authorization-evidence",
        )
    result = evaluate_ready_for_review_admission(
        repository=repository,
        pr_number=pr_number,
        pr_lifecycle_state=pr_lifecycle_state,
        expected_head_sha=expected_head_sha,
        observed_head_sha=observed_head_sha,
        validation_head_sha=validation_head_sha,
        validation_admission_mode=validation_admission_mode,
        aggregate_status=aggregate_status,
        focused_status=focused_status,
        requested_changes=requested_changes,
        blocking_unresolved=blocking_unresolved,
        ready_for_review_authority_supplied=ready_for_review_authority_supplied,
        pr_title=pr_title,
        pr_body=pr_body,
        closure_admissions=admissions,
    )
    return {
        "repository": result.repository,
        "pr_number": result.pr_number,
        "expected_head_sha": result.expected_head_sha,
        "observed_head_sha": result.observed_head_sha,
        "validation_head_sha": result.validation_head_sha,
        "expected_body_revision": expected_body_revision,
        "observed_body_revision": observed_body_revision,
        "transition_admissible": result.transition_admissible,
        "provisional_ready": result.provisional_ready,
        "rollback_to_draft_required": result.rollback_to_draft_required,
        "reason_codes": list(result.reason_codes),
        "next_action": result.next_action,
        "authorized_closing_targets": [
            admission.target
            for admission in admissions
            if admission.authorization.repository.lower() == repository.lower()
        ],
        "ready_for_review_authorized": result.ready_for_review_authorized,
        "merge_authorized": result.merge_authorized,
        "issue_closure_authorized": result.issue_closure_authorized,
        "workflow_authorized": result.workflow_authorized,
        "protected_setting_authorized": result.protected_setting_authorized,
        "production_authorized": result.production_authorized,
        "external_system_write_authorized": result.external_system_write_authorized,
    }


@mcp.tool()
def classify_agent_os_mission_completion_tool(repository: str, issue_number: int, branch_exists: bool, implementation_commit_count: int, draft_pr_exists: bool, canonical_pr_readback_verified: bool, capable_route_available: bool, subordinate_writes_only: bool, implementation_pr_required: bool = False, live_consumer_required: bool = False, live_consumer_requirement_source: str | None = None, live_consumer_reachability_proven: bool = False, live_consumer_identity: str | None = None, live_consumer_evidence_source: str | None = None, live_consumer_evidence_current: bool = False, live_consumer_evidence_kind: str | None = None, successor_issue_number: int | None = None, successor_current: bool = False, successor_owns_residual_live_acceptance: bool = False, canonical_pr_readback_binding: str | None = None, live_consumer_observation_binding: str | None = None) -> dict[str, object]:
    _github_target_entry_guard(
        repository=repository, issue_number=issue_number, operation="read-issue"
    )
    return classify_agent_os_mission_completion(repository=repository, issue_number=issue_number, branch_exists=branch_exists, implementation_commit_count=implementation_commit_count, draft_pr_exists=draft_pr_exists, canonical_pr_readback_verified=canonical_pr_readback_verified, capable_route_available=capable_route_available, subordinate_writes_only=subordinate_writes_only, implementation_pr_required=implementation_pr_required, live_consumer_required=live_consumer_required, live_consumer_requirement_source=live_consumer_requirement_source, live_consumer_reachability_proven=live_consumer_reachability_proven, live_consumer_identity=live_consumer_identity, live_consumer_evidence_source=live_consumer_evidence_source, live_consumer_evidence_current=live_consumer_evidence_current, live_consumer_evidence_kind=live_consumer_evidence_kind, successor_issue_number=successor_issue_number, successor_current=successor_current, successor_owns_residual_live_acceptance=successor_owns_residual_live_acceptance, canonical_pr_readback_binding=canonical_pr_readback_binding, live_consumer_observation_binding=live_consumer_observation_binding)


@mcp.tool()
def classify_agent_os_issue_batch_completion_tool(repository: str, issue_number: int, lane_evidence: list[dict[str, object]]) -> dict[str, object]:
    """Require PR-or-explicit-no-PR terminal proof for every selected issue lane."""
    _github_target_entry_guard(
        repository=repository, issue_number=issue_number, operation="read-issue"
    )
    for _lane_item in lane_evidence:
        _github_target_entry_guard(
            repository=repository,
            issue_number=_lane_item.get("issue_number"),
            operation="read-issue",
        )
    return classify_issue_batch_completion(repository=repository, issue_number=issue_number, lane_evidence=lane_evidence)


@mcp.tool()
def classify_agent_os_investigation_completion_tool(repository: str, issue_number: int, material_branch_states: tuple[str, ...], executable_next_action_available: bool, subordinate_write_performed: bool) -> dict[str, object]:
    _github_target_entry_guard(
        repository=repository, issue_number=issue_number, operation="read-issue"
    )
    decision = evaluate_investigation_completion_admission(repository=repository, issue_number=issue_number, material_branch_states=material_branch_states, executable_next_action_available=executable_next_action_available, subordinate_write_performed=subordinate_write_performed)
    payload = asdict(decision); payload["reason_codes"] = list(decision.reason_codes); payload["agent_os_continuation"] = completion_continuation_payload(terminal=decision.completion_admissible, blocked=(not decision.completion_admissible and not decision.executable_next_action_available), next_action=decision.next_action, reason_codes=decision.reason_codes); return payload


@mcp.tool()
def classify_agent_os_continuation_tool(repository: str, issue_number: int, operation_id: str, surface_outcome: str, approved_alternative_capability: str | None = None, branch: str | None = None, pull_request: int | None = None, checkpoint_id: str | None = None, lease_id: str | None = None, prior_effect: str = "none-proven", target_identity_reacquired: bool = False, requires_exact_blob_identity: bool = False, exact_blob_identity_reacquired: bool = False, runtime_surface_transition: bool = False, evidence_compatibility_confirmed: bool = False, active_foreign_lease: bool = False, equivalent_transition_repeated: bool = False, material_decision_required: bool = False, alternative_widens_authority: bool = False, non_absorbed_domain: str | None = None) -> dict[str, object]:
    _github_target_entry_guard(
        repository=repository, issue_number=issue_number, operation="read-issue"
    )
    if pull_request is not None:
        _github_target_entry_guard(
            repository=repository, pr_number=pull_request, operation="read-pull-request"
        )
    return classify_agent_os_continuation(repository=repository, issue_number=issue_number, operation_id=operation_id, surface_outcome=surface_outcome, approved_alternative_capability=approved_alternative_capability, branch=branch, pull_request=pull_request, checkpoint_id=checkpoint_id, lease_id=lease_id, prior_effect=prior_effect, target_identity_reacquired=target_identity_reacquired, requires_exact_blob_identity=requires_exact_blob_identity, exact_blob_identity_reacquired=exact_blob_identity_reacquired, runtime_surface_transition=runtime_surface_transition, evidence_compatibility_confirmed=evidence_compatibility_confirmed, active_foreign_lease=active_foreign_lease, equivalent_transition_repeated=equivalent_transition_repeated, material_decision_required=material_decision_required, alternative_widens_authority=alternative_widens_authority, non_absorbed_domain=non_absorbed_domain)


@mcp.tool()
def classify_agent_os_bulk_repair_continuation_tool(repository: str, issue_number: int, requested_pull_requests: list[int], candidate_evidence: list[dict[str, object]]) -> dict[str, object]:
    _github_target_entry_guard(
        repository=repository, issue_number=issue_number, operation="read-issue"
    )
    for _requested_pr in requested_pull_requests:
        _github_target_entry_guard(
            repository=repository, pr_number=_requested_pr, operation="read-pull-request"
        )
    for _repair_candidate in candidate_evidence:
        if _repair_candidate.get("pull_request_number") is not None:
            _github_target_entry_guard(
                repository=repository,
                pr_number=_repair_candidate.get("pull_request_number"),
                operation="read-pull-request",
            )
    return classify_bulk_repair_continuation(repository=repository, issue_number=issue_number, requested_pull_requests=requested_pull_requests, candidate_evidence=candidate_evidence)


@mcp.tool()
def admit_agent_os_issue_comment_mutation_tool(
    phase: str,
    issue_number: int,
    evidence_kind: str = "defect",
    target_open: bool = False,
    state_current: bool = False,
    open_owner_issue_number: int | None = None,
    historical_lineage_issue_number: int | None = None,
    intended_body: str | None = None,
    provider_reported_success: bool | None = None,
    readback_complete: bool = False,
    comments: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Run the issue-comment write boundary: pre-write verify-open guard (#2741) or post-write canonical readback (#2785). Never performs the write."""
    _github_target_entry_guard(
        repository=None, issue_number=issue_number, operation="update-issue"
    )
    if open_owner_issue_number is not None:
        _github_target_entry_guard(
            repository=None, issue_number=open_owner_issue_number, operation="read-issue"
        )
    if historical_lineage_issue_number is not None:
        _github_target_entry_guard(
            repository=None,
            issue_number=historical_lineage_issue_number,
            operation="read-issue",
        )
    return evaluate_issue_comment_mutation_boundary_for_host(
        phase=phase,
        issue_number=issue_number,
        evidence_kind=evidence_kind,
        target_open=target_open,
        state_current=state_current,
        open_owner_issue_number=open_owner_issue_number,
        historical_lineage_issue_number=historical_lineage_issue_number,
        intended_body=intended_body,
        provider_reported_success=provider_reported_success,
        readback_complete=readback_complete,
        comments=tuple(comments or ()),
    )


@mcp.tool()
def project_agent_os_lane_post_pr_issue_reconciliation_tool(
    phase: str,
    issue_number: int,
    issue_open: bool = False,
    lifecycle_labels: tuple[str, ...] = (),
    linked_pull_request_number: int = 0,
    pr_state: str = "draft",
    pr_head_sha: str = "",
    pr_readback_current: bool = False,
    closure_authorized: bool = False,
    evidence_current: bool = False,
    plan: dict[str, object] | None = None,
) -> dict[str, object]:
    """Project the Safe Implementation Lane post-PR issue disposition (#2791) or prove it from the canonical post-mutation readback. Never grants merge/Ready authority."""
    _github_target_entry_guard(
        repository=None, issue_number=issue_number, operation="read-issue"
    )
    if linked_pull_request_number:
        _github_target_entry_guard(
            repository=None,
            pr_number=linked_pull_request_number,
            operation="read-pull-request",
        )
    return project_lane_post_pr_issue_reconciliation_for_host(
        phase=phase,
        issue_number=issue_number,
        issue_open=issue_open,
        lifecycle_labels=tuple(lifecycle_labels),
        linked_pull_request_number=linked_pull_request_number,
        pr_state=pr_state,
        pr_head_sha=pr_head_sha,
        pr_readback_current=pr_readback_current,
        closure_authorized=closure_authorized,
        evidence_current=evidence_current,
        plan=plan,
    )


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
