"""Pure-local validation coordination and review-thread resolution eligibility."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from scripts.agent_os_issue_acceptance.models import Status

from .models import (
    AUTHORITY_FIELDS,
    EvidenceValidationError,
    NormalizedPRSnapshot,
    NormalizedReviewThread,
    canonical_json,
    deterministic_id,
)
from .planning import FINDING_CLASSIFICATIONS, PlannedFinding, RemediationPlan, RemediationTask
from .preflight import PreflightResult

MAX_ITEMS = 5_000
MAX_FILES = 5_000
MAX_STRING_LENGTH = 10_000
MAX_REASON_CODES = 64

VALIDATION_STATES = frozenset(
    {
        "validation-planned",
        "validation-passed",
        "validation-failed",
        "validation-unavailable",
        "validation-incomplete",
        "validation-stale",
        "final-head-mismatch",
        "manual-review-required",
    }
)
SUGGESTED_ACTIONS = frozenset(
    {
        "eligible-to-resolve",
        "leave-open",
        "request-more-evidence",
        "route-out-of-scope",
        "manual-decision-required",
    }
)
VALIDATION_PROFILES = {"static", "focused", "aggregate", "manual-review"}
UPSTREAM_EXECUTION_STATUSES = {
    "planned",
    "static-pass",
    "focused-pass-aggregate-pending",
    "focused-fail",
    "aggregate-pass",
    "aggregate-fail",
    "manual-review",
    "cancelled",
    "infrastructure-failure",
    "unavailable",
}

_FIX_FIELDS = {"finding_id", "fixed", "head_sha", "evidence_id"}
_VALIDATION_FIELDS = {
    "category",
    "profile",
    "validation_plan_id",
    "command_plan_id",
    "execution_evidence_id",
    "expected_sha",
    "tested_sha",
    "execution_status",
    "aggregate_pending",
    "evidence_complete",
    "evidence_available",
    "reason_codes",
}

_STATE_PRIORITY = {
    "validation-passed": 0,
    "validation-planned": 1,
    "validation-incomplete": 2,
    "validation-unavailable": 3,
    "validation-failed": 4,
    "validation-stale": 5,
    "final-head-mismatch": 6,
    "manual-review-required": 7,
}


@dataclass(frozen=True)
class FindingFixEvidence:
    finding_id: str
    fixed: bool
    head_sha: str
    evidence_id: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ValidationEvidenceBinding:
    category: str
    profile: str
    validation_plan_id: str
    command_plan_id: str
    execution_evidence_id: str
    expected_sha: str
    tested_sha: str
    execution_status: str
    aggregate_pending: bool
    evidence_complete: bool
    evidence_available: bool
    reason_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def evidence_id(self) -> str:
        return deterministic_id(self.to_dict())


@dataclass(frozen=True)
class ValidationCategoryResult:
    category: str
    state: str
    profile: str | None
    validation_plan_id: str | None
    command_plan_id: str | None
    execution_evidence_id: str | None
    tested_sha: str | None
    reason_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ThreadResolutionEvidence:
    thread_id: str
    finding_ids: tuple[str, ...]
    remediation_task_ids: tuple[str, ...]
    required_validation_categories: tuple[str, ...]
    validation_results: tuple[ValidationCategoryResult, ...]
    validation_state: str
    resolution_eligible: bool
    ineligibility_reason_codes: tuple[str, ...]
    handoff_owner: str
    suggested_action: str
    thread_resolved: bool = False
    execution_authorized: bool = False
    external_write_authorized: bool = False
    merge_authorized: bool = False
    side_effects_performed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResolutionPlan:
    repository: str
    pr_number: int
    expected_head_sha: str
    current_head_sha: str
    tested_shas: tuple[str, ...]
    final_captured_head_sha: str
    changed_files: tuple[str, ...]
    remediation_task_ids: tuple[str, ...]
    finding_ids: tuple[str, ...]
    review_thread_ids: tuple[str, ...]
    validation_evidence_ids: tuple[str, ...]
    thread_results: tuple[ThreadResolutionEvidence, ...]
    resolution_plan_id: str
    thread_resolved: bool = False
    execution_authorized: bool = False
    external_write_authorized: bool = False
    merge_authorized: bool = False
    side_effects_performed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def canonical_serialization(self) -> str:
        return canonical_json(self.to_dict())


def _exact(value: Any, expected: type, field: str) -> None:
    if type(value) is not expected:
        raise EvidenceValidationError(f"{field} must be exactly {expected.__name__}")


def _text(value: Any, field: str) -> str:
    _exact(value, str, field)
    if not value or len(value) > MAX_STRING_LENGTH:
        raise EvidenceValidationError(f"{field} must be non-empty and within size limits")
    return value


def _sha40(value: Any, field: str) -> str:
    text = _text(value, field).lower()
    if len(text) != 40 or any(char not in "0123456789abcdef" for char in text):
        raise EvidenceValidationError(f"{field} must be a 40-character hexadecimal SHA")
    return text


def _string_sequence(value: Any, field: str, *, max_items: int = MAX_ITEMS) -> tuple[str, ...]:
    if type(value) not in {list, tuple}:
        raise EvidenceValidationError(f"{field} must be a list or tuple")
    if len(value) > max_items:
        raise EvidenceValidationError(f"{field} exceeds size limit")
    result = tuple(_text(item, f"{field}[{index}]") for index, item in enumerate(value))
    if len(set(result)) != len(result):
        raise EvidenceValidationError(f"{field} contains duplicates")
    return result


def _authority_false(value: Any, field: str) -> None:
    for authority_field in AUTHORITY_FIELDS:
        authority_value = getattr(value, authority_field, False)
        if type(authority_value) is not bool or authority_value:
            raise EvidenceValidationError(f"{field}.{authority_field} must remain false")


def _normalize_fix(payload: Any) -> FindingFixEvidence:
    _exact(payload, dict, "finding fix evidence")
    if any(type(key) is not str for key in payload):
        raise EvidenceValidationError("finding fix evidence keys must be strings")
    unknown = set(payload) - _FIX_FIELDS
    missing = _FIX_FIELDS - set(payload)
    if unknown or missing:
        raise EvidenceValidationError("finding fix evidence fields do not match the contract")
    fixed = payload["fixed"]
    _exact(fixed, bool, "fixed")
    return FindingFixEvidence(
        finding_id=_text(payload["finding_id"], "finding_id"),
        fixed=fixed,
        head_sha=_sha40(payload["head_sha"], "head_sha"),
        evidence_id=_text(payload["evidence_id"], "evidence_id"),
    )


def _normalize_validation(payload: Any) -> ValidationEvidenceBinding:
    _exact(payload, dict, "validation evidence")
    if any(type(key) is not str for key in payload):
        raise EvidenceValidationError("validation evidence keys must be strings")
    unknown = set(payload) - _VALIDATION_FIELDS
    missing = _VALIDATION_FIELDS - set(payload)
    if unknown or missing:
        raise EvidenceValidationError("validation evidence fields do not match the contract")

    profile = _text(payload["profile"], "profile")
    status = _text(payload["execution_status"], "execution_status")
    if profile not in VALIDATION_PROFILES:
        raise EvidenceValidationError("profile is unsupported")
    if status not in UPSTREAM_EXECUTION_STATUSES:
        raise EvidenceValidationError("execution_status is unsupported")
    if status.startswith("focused-") and profile != "focused":
        raise EvidenceValidationError("focused execution status requires focused profile")
    if status.startswith("aggregate-") and profile != "aggregate":
        raise EvidenceValidationError("aggregate execution status requires aggregate profile")
    if status == "static-pass" and profile != "static":
        raise EvidenceValidationError("static-pass requires static profile")

    aggregate_pending = payload["aggregate_pending"]
    complete = payload["evidence_complete"]
    available = payload["evidence_available"]
    _exact(aggregate_pending, bool, "aggregate_pending")
    _exact(complete, bool, "evidence_complete")
    _exact(available, bool, "evidence_available")
    reasons = tuple(sorted(_string_sequence(payload["reason_codes"], "reason_codes", max_items=MAX_REASON_CODES)))

    return ValidationEvidenceBinding(
        category=_text(payload["category"], "category"),
        profile=profile,
        validation_plan_id=_text(payload["validation_plan_id"], "validation_plan_id"),
        command_plan_id=_text(payload["command_plan_id"], "command_plan_id"),
        execution_evidence_id=_text(payload["execution_evidence_id"], "execution_evidence_id"),
        expected_sha=_sha40(payload["expected_sha"], "expected_sha"),
        tested_sha=_sha40(payload["tested_sha"], "tested_sha"),
        execution_status=status,
        aggregate_pending=aggregate_pending,
        evidence_complete=complete,
        evidence_available=available,
        reason_codes=reasons,
    )


def _validate_core_inputs(
    snapshot: NormalizedPRSnapshot,
    review_threads: tuple[NormalizedReviewThread, ...],
    preflight_result: PreflightResult,
    remediation_plan: RemediationPlan,
) -> None:
    if type(snapshot) is not NormalizedPRSnapshot:
        raise EvidenceValidationError("snapshot must be an exact NormalizedPRSnapshot")
    if type(review_threads) is not tuple or any(type(item) is not NormalizedReviewThread for item in review_threads):
        raise EvidenceValidationError("review_threads must be an exact tuple of NormalizedReviewThread")
    if len(review_threads) > MAX_ITEMS:
        raise EvidenceValidationError("review_threads exceeds size limit")
    if type(preflight_result) is not PreflightResult:
        raise EvidenceValidationError("preflight_result must be an exact PreflightResult")
    if type(remediation_plan) is not RemediationPlan:
        raise EvidenceValidationError("remediation_plan must be an exact RemediationPlan")

    _authority_false(snapshot, "snapshot")
    _authority_false(preflight_result, "preflight_result")
    _authority_false(remediation_plan, "remediation_plan")
    for thread in review_threads:
        _authority_false(thread, "review_thread")
    for finding in remediation_plan.findings:
        if type(finding) is not PlannedFinding:
            raise EvidenceValidationError("remediation_plan.findings contains an invalid item")
        _authority_false(finding, "finding")
        if finding.classification not in FINDING_CLASSIFICATIONS:
            raise EvidenceValidationError("finding classification is unsupported")
    for task in remediation_plan.tasks:
        if type(task) is not RemediationTask:
            raise EvidenceValidationError("remediation_plan.tasks contains an invalid item")
        _authority_false(task, "task")

    thread_ids = tuple(thread.thread_id for thread in review_threads)
    comment_ids = tuple(thread.top_level_comment_id for thread in review_threads)
    if len(set(thread_ids)) != len(thread_ids):
        raise EvidenceValidationError("review_threads contains duplicate thread IDs")
    if len(set(comment_ids)) != len(comment_ids):
        raise EvidenceValidationError("review_threads contains duplicate top-level comment IDs")
    if snapshot.repository != remediation_plan.repository or snapshot.pr_number != remediation_plan.pr_number:
        raise EvidenceValidationError("PRR1 and PRR2 repository or PR identity mismatch")
    if snapshot.head_sha != remediation_plan.head_sha:
        raise EvidenceValidationError("PRR1 and PRR2 expected head identity mismatch")
    if preflight_result.expected_head != snapshot.head_sha:
        raise EvidenceValidationError("preflight expected head does not match the PRR1 snapshot")
    actual_finding_ids = tuple(finding.finding_id for finding in remediation_plan.findings)
    actual_task_ids = tuple(task.task_id for task in remediation_plan.tasks)
    if remediation_plan.finding_ids != actual_finding_ids:
        raise EvidenceValidationError("remediation_plan finding identity list is inconsistent")
    if remediation_plan.task_ids != actual_task_ids:
        raise EvidenceValidationError("remediation_plan task identity list is inconsistent")
    if len(set(actual_finding_ids)) != len(actual_finding_ids):
        raise EvidenceValidationError("remediation_plan contains duplicate finding IDs")
    if len(set(actual_task_ids)) != len(actual_task_ids):
        raise EvidenceValidationError("remediation_plan contains duplicate task IDs")
    known_findings = set(actual_finding_ids)
    for task in remediation_plan.tasks:
        if not task.finding_ids or any(finding_id not in known_findings for finding_id in task.finding_ids):
            raise EvidenceValidationError("remediation task references an unknown finding")


def _binding_state(
    binding: ValidationEvidenceBinding,
    *,
    current_head_sha: str,
    final_head_sha: str,
) -> tuple[str, tuple[str, ...]]:
    reasons = list(binding.reason_codes)
    if final_head_sha != current_head_sha:
        reasons.append("final-head-does-not-match-current-head")
        return "final-head-mismatch", tuple(sorted(set(reasons)))
    if not binding.evidence_available:
        reasons.append("validation-evidence-unavailable")
        return "validation-unavailable", tuple(sorted(set(reasons)))
    if binding.expected_sha != current_head_sha or binding.tested_sha != current_head_sha:
        reasons.append("validation-evidence-does-not-bind-current-head")
        return "validation-stale", tuple(sorted(set(reasons)))
    if not binding.evidence_complete:
        reasons.append("validation-evidence-incomplete")
        return "validation-incomplete", tuple(sorted(set(reasons)))
    if binding.profile == "manual-review":
        return "manual-review-required", tuple(sorted(set(reasons)))
    if binding.execution_status == "planned":
        return "validation-planned", tuple(sorted(set(reasons)))
    if binding.execution_status == "focused-pass-aggregate-pending":
        return "validation-passed", tuple(sorted(set(reasons)))
    if binding.aggregate_pending:
        reasons.append("aggregate-validation-pending")
        return "validation-incomplete", tuple(sorted(set(reasons)))
    if binding.execution_status in {"focused-fail", "aggregate-fail"}:
        return "validation-failed", tuple(sorted(set(reasons)))
    if binding.execution_status in {"cancelled", "infrastructure-failure", "unavailable"}:
        reasons.append("validation-execution-unavailable")
        return "validation-unavailable", tuple(sorted(set(reasons)))
    if binding.execution_status == "manual-review":
        return "manual-review-required", tuple(sorted(set(reasons)))
    if binding.execution_status in {"static-pass", "aggregate-pass"}:
        return "validation-passed", tuple(sorted(set(reasons)))
    raise EvidenceValidationError("validation evidence produced an unsupported state")


def _validation_result(
    category: str,
    bindings: tuple[ValidationEvidenceBinding, ...],
    *,
    current_head_sha: str,
    final_head_sha: str,
) -> ValidationCategoryResult:
    matching = tuple(binding for binding in bindings if binding.category == category)
    if not matching:
        return ValidationCategoryResult(
            category=category,
            state="validation-unavailable",
            profile=None,
            validation_plan_id=None,
            command_plan_id=None,
            execution_evidence_id=None,
            tested_sha=None,
            reason_codes=("validation-category-evidence-missing",),
        )
    if len(matching) > 1:
        return ValidationCategoryResult(
            category=category,
            state="manual-review-required",
            profile=None,
            validation_plan_id=None,
            command_plan_id=None,
            execution_evidence_id=None,
            tested_sha=None,
            reason_codes=("validation-category-evidence-ambiguous",),
        )
    binding = matching[0]
    state, reasons = _binding_state(
        binding,
        current_head_sha=current_head_sha,
        final_head_sha=final_head_sha,
    )
    return ValidationCategoryResult(
        category=category,
        state=state,
        profile=binding.profile,
        validation_plan_id=binding.validation_plan_id,
        command_plan_id=binding.command_plan_id,
        execution_evidence_id=binding.execution_evidence_id,
        tested_sha=binding.tested_sha,
        reason_codes=reasons,
    )


def _fix_status(
    finding: PlannedFinding,
    *,
    findings_by_id: dict[str, PlannedFinding],
    fixes_by_id: dict[str, FindingFixEvidence],
    current_head_sha: str,
    expected_head_sha: str,
    seen: frozenset[str] = frozenset(),
) -> tuple[bool, tuple[str, ...]]:
    if finding.finding_id in seen:
        return False, ("duplicate-finding-cycle",)
    if finding.scope_state != "inside-scope" or finding.classification == "out-of-scope":
        return False, ("finding-out-of-scope",)
    if finding.classification == "outdated":
        return True, ()
    if finding.classification == "already-fixed":
        if expected_head_sha == current_head_sha:
            return True, ()
        fix = fixes_by_id.get(finding.finding_id)
        if fix is not None and fix.fixed and fix.head_sha == current_head_sha:
            return True, ()
        return False, ("already-fixed-evidence-stale",)
    if finding.classification == "duplicate":
        if not finding.duplicate_of or finding.duplicate_of not in findings_by_id:
            return False, ("duplicate-canonical-finding-missing",)
        return _fix_status(
            findings_by_id[finding.duplicate_of],
            findings_by_id=findings_by_id,
            fixes_by_id=fixes_by_id,
            current_head_sha=current_head_sha,
            expected_head_sha=expected_head_sha,
            seen=seen | {finding.finding_id},
        )
    if finding.classification == "conflicting":
        return False, ("conflicting-unresolved-finding",)
    if finding.classification == "manual-review-required":
        return False, ("finding-requires-manual-decision",)
    if finding.classification == "missing-evidence":
        return False, ("finding-evidence-missing",)

    fix = fixes_by_id.get(finding.finding_id)
    if fix is None:
        return False, ("finding-fix-evidence-missing",)
    if not fix.fixed:
        return False, ("finding-not-fixed",)
    if fix.head_sha != current_head_sha:
        return False, ("finding-fix-evidence-stale",)
    return True, ()


def _suggested_action(reasons: tuple[str, ...], validation_state: str, eligible: bool) -> str:
    if eligible:
        return "eligible-to-resolve"
    if any("out-of-scope" in reason for reason in reasons):
        return "route-out-of-scope"
    if any(
        marker in reason
        for reason in reasons
        for marker in ("manual-decision", "conflicting", "ambiguous", "cycle", "preflight-")
    ) or validation_state == "manual-review-required":
        return "manual-decision-required"
    if validation_state == "validation-failed" or "finding-not-fixed" in reasons or "thread-already-resolved" in reasons:
        return "leave-open"
    return "request-more-evidence"


def _plan_identity_payload(plan: ResolutionPlan) -> dict[str, Any]:
    payload = plan.to_dict()
    payload.pop("resolution_plan_id", None)
    return payload


def resolution_plan_id(plan: ResolutionPlan) -> str:
    if type(plan) is not ResolutionPlan:
        raise EvidenceValidationError("plan must be an exact ResolutionPlan")
    return "resolution-plan:" + deterministic_id(_plan_identity_payload(plan))


def serialize_resolution_plan(plan: ResolutionPlan) -> dict[str, Any]:
    if type(plan) is not ResolutionPlan:
        raise EvidenceValidationError("plan must be an exact ResolutionPlan")
    if plan.resolution_plan_id != resolution_plan_id(plan):
        raise EvidenceValidationError("resolution plan identity mismatch")
    if plan.thread_resolved or plan.execution_authorized or plan.external_write_authorized or plan.merge_authorized or plan.side_effects_performed:
        raise EvidenceValidationError("resolution plan authority fields must remain false")
    return plan.to_dict()


def coordinate_resolution(
    snapshot: NormalizedPRSnapshot,
    review_threads: tuple[NormalizedReviewThread, ...],
    preflight_result: PreflightResult,
    remediation_plan: RemediationPlan,
    changed_files: tuple[str, ...] | list[str],
    finding_fix_payloads: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    validation_evidence_payloads: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    *,
    current_head_sha: str,
    final_captured_head_sha: str,
) -> ResolutionPlan:
    """Coordinate supplied immutable evidence into a non-authorizing resolution plan."""

    _validate_core_inputs(snapshot, review_threads, preflight_result, remediation_plan)
    current_head = _sha40(current_head_sha, "current_head_sha")
    final_head = _sha40(final_captured_head_sha, "final_captured_head_sha")
    normalized_changed = tuple(sorted(_string_sequence(changed_files, "changed_files", max_items=MAX_FILES)))
    if type(finding_fix_payloads) not in {list, tuple}:
        raise EvidenceValidationError("finding_fix_payloads must be a list or tuple")
    if type(validation_evidence_payloads) not in {list, tuple}:
        raise EvidenceValidationError("validation_evidence_payloads must be a list or tuple")
    if len(finding_fix_payloads) > MAX_ITEMS or len(validation_evidence_payloads) > MAX_ITEMS:
        raise EvidenceValidationError("supplied coordination evidence exceeds size limit")

    fixes = tuple(_normalize_fix(payload) for payload in finding_fix_payloads)
    if len({fix.finding_id for fix in fixes}) != len(fixes):
        raise EvidenceValidationError("finding fix evidence contains duplicate finding IDs")
    bindings = tuple(_normalize_validation(payload) for payload in validation_evidence_payloads)

    findings_by_id = {finding.finding_id: finding for finding in remediation_plan.findings}
    if len(findings_by_id) != len(remediation_plan.findings):
        raise EvidenceValidationError("remediation plan contains duplicate finding IDs")
    if any(fix.finding_id not in findings_by_id for fix in fixes):
        raise EvidenceValidationError("finding fix evidence references an unknown finding")
    fixes_by_id = {fix.finding_id: fix for fix in fixes}
    allowed_files = set(preflight_result.allowed_files)
    outside_changed = tuple(path for path in normalized_changed if path not in allowed_files)

    tasks_by_finding: dict[str, list[RemediationTask]] = {}
    for task in remediation_plan.tasks:
        for finding_id in task.finding_ids:
            tasks_by_finding.setdefault(finding_id, []).append(task)

    thread_results: list[ThreadResolutionEvidence] = []
    for thread in sorted(review_threads, key=lambda item: item.thread_id):
        associated = tuple(
            sorted(
                (finding for finding in remediation_plan.findings if thread.thread_id in finding.source_thread_ids),
                key=lambda item: item.finding_id,
            )
        )
        finding_ids = tuple(finding.finding_id for finding in associated)
        tasks = {
            task.task_id: task
            for finding in associated
            for task in tasks_by_finding.get(finding.finding_id, [])
        }
        task_ids = tuple(sorted(tasks))
        required_categories = tuple(
            sorted(
                {
                    category
                    for finding in associated
                    for category in finding.proposed_validations
                }
                | {
                    category
                    for task in tasks.values()
                    for category in task.proposed_validations
                }
            )
        )
        validation_results = tuple(
            _validation_result(
                category,
                bindings,
                current_head_sha=current_head,
                final_head_sha=final_head,
            )
            for category in required_categories
        )
        validation_state = (
            max((result.state for result in validation_results), key=_STATE_PRIORITY.__getitem__)
            if validation_results
            else ("final-head-mismatch" if final_head != current_head else "validation-passed")
        )
        focused_pending = any(
            binding.category in required_categories
            and binding.execution_status == "focused-pass-aggregate-pending"
            for binding in bindings
        )
        aggregate_final_pass = any(
            binding.category in required_categories
            and binding.profile == "aggregate"
            and _binding_state(
                binding,
                current_head_sha=current_head,
                final_head_sha=final_head,
            )[0] == "validation-passed"
            for binding in bindings
        )
        if focused_pending and not aggregate_final_pass and _STATE_PRIORITY[validation_state] < _STATE_PRIORITY["validation-incomplete"]:
            validation_state = "validation-incomplete"

        reasons: set[str] = set()
        if not associated:
            reasons.add("thread-has-no-associated-finding")
        if thread.resolved:
            reasons.add("thread-already-resolved")
        if preflight_result.overall_status is not Status.PASS:
            reasons.add(f"preflight-{preflight_result.overall_status.value}")
        if outside_changed or preflight_result.outside_allowed_files:
            reasons.add("implementation-changed-files-out-of-scope")
        if preflight_result.manual_review_items:
            reasons.add("preflight-manual-review-remains")
        if final_head != current_head:
            reasons.add("final-head-does-not-match-current-head")
        if focused_pending and not aggregate_final_pass:
            reasons.add("aggregate-validation-pending")
        actionable_requires_validation = any(
            finding.classification == "actionable" for finding in associated
        )
        if actionable_requires_validation and not required_categories:
            reasons.add("required-validation-categories-missing")
            if _STATE_PRIORITY[validation_state] < _STATE_PRIORITY["validation-incomplete"]:
                validation_state = "validation-incomplete"

        fixed = bool(associated)
        for finding in associated:
            finding_fixed, finding_reasons = _fix_status(
                finding,
                findings_by_id=findings_by_id,
                fixes_by_id=fixes_by_id,
                current_head_sha=current_head,
                expected_head_sha=remediation_plan.head_sha,
            )
            fixed = fixed and finding_fixed
            reasons.update(finding_reasons)
        for result in validation_results:
            if result.state != "validation-passed":
                reasons.update(result.reason_codes)
                reasons.add(result.state)

        eligible = (
            fixed
            and not reasons
            and validation_state == "validation-passed"
            and final_head == current_head
            and not outside_changed
            and not preflight_result.outside_allowed_files
            and not preflight_result.manual_review_items
            and preflight_result.overall_status is Status.PASS
            and not thread.resolved
        )
        reason_tuple = tuple(sorted(reasons))
        action = _suggested_action(reason_tuple, validation_state, eligible)
        if action not in SUGGESTED_ACTIONS:
            raise EvidenceValidationError("coordinator produced unsupported suggested action")
        if validation_state not in VALIDATION_STATES:
            raise EvidenceValidationError("coordinator produced unsupported validation state")
        thread_results.append(
            ThreadResolutionEvidence(
                thread_id=thread.thread_id,
                finding_ids=finding_ids,
                remediation_task_ids=task_ids,
                required_validation_categories=required_categories,
                validation_results=validation_results,
                validation_state=validation_state,
                resolution_eligible=eligible,
                ineligibility_reason_codes=reason_tuple,
                handoff_owner="GitHub Service Agent",
                suggested_action=action,
            )
        )

    tested_shas = tuple(sorted({binding.tested_sha for binding in bindings}))
    validation_evidence_ids = tuple(sorted(binding.evidence_id for binding in bindings))
    base_payload = {
        "repository": snapshot.repository,
        "pr_number": snapshot.pr_number,
        "expected_head_sha": remediation_plan.head_sha,
        "current_head_sha": current_head,
        "tested_shas": tested_shas,
        "final_captured_head_sha": final_head,
        "changed_files": normalized_changed,
        "remediation_task_ids": remediation_plan.task_ids,
        "finding_ids": remediation_plan.finding_ids,
        "review_thread_ids": tuple(result.thread_id for result in thread_results),
        "validation_evidence_ids": validation_evidence_ids,
        "thread_results": tuple(thread_results),
        "thread_resolved": False,
        "execution_authorized": False,
        "external_write_authorized": False,
        "merge_authorized": False,
        "side_effects_performed": False,
    }
    temporary = ResolutionPlan(
        **base_payload,
        resolution_plan_id="resolution-plan:pending",
    )
    plan = ResolutionPlan(
        **base_payload,
        resolution_plan_id="resolution-plan:" + deterministic_id(_plan_identity_payload(temporary)),
    )
    serialize_resolution_plan(plan)
    return plan
