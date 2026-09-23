"""Pure-local deterministic remediation planning for normalized PR review evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .models import (
    AUTHORITY_FIELDS,
    EvidenceValidationError,
    NormalizedPRSnapshot,
    NormalizedReviewThread,
    canonical_json,
    deterministic_id,
)

MAX_CANDIDATES = 5_000
MAX_FILES = 5_000
MAX_ITEMS = 5_000
MAX_STRING_LENGTH = 10_000
MAX_OPTIONAL_EVIDENCE_CHARS = 200_000

FINDING_CLASSIFICATIONS = {
    "actionable",
    "already-fixed",
    "outdated",
    "duplicate",
    "conflicting",
    "out-of-scope",
    "missing-evidence",
    "manual-review-required",
}
COMPUTE_ROUTES = {
    "no-model",
    "small-model-eligible",
    "high-reasoning-required",
    "manual-decision-required",
}
RISKS = {"low", "medium", "high"}

_CANDIDATE_FIELDS = {
    "finding_identity",
    "rule_id",
    "requested_outcome",
    "source_thread_ids",
    "affected_files",
    "owner",
    "risk",
    "requested_summary",
    "proposed_validations",
    "evidence_basis",
    "semantic_ambiguity",
    "high_reasoning_reason",
    "manual_decision_reason",
    "already_fixed_head_sha",
    "already_fixed_condition_absent",
    *AUTHORITY_FIELDS,
}


@dataclass(frozen=True)
class FindingCandidate:
    candidate_id: str
    finding_identity: str
    rule_id: str
    requested_outcome_fingerprint: str
    source_thread_ids: tuple[str, ...]
    affected_files: tuple[str, ...]
    owner: str
    risk: str
    requested_summary: str
    proposed_validations: tuple[str, ...]
    evidence_basis: tuple[str, ...]
    semantic_ambiguity: bool = False
    high_reasoning_reason: str | None = None
    manual_decision_reason: str | None = None
    already_fixed_head_sha: str | None = None
    already_fixed_condition_absent: bool = False
    execution_authorized: bool = False
    external_write_authorized: bool = False
    merge_authorized: bool = False
    side_effects_performed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PlannedFinding:
    finding_id: str
    candidate_id: str
    source_thread_ids: tuple[str, ...]
    reviewer_identities: tuple[str, ...]
    target_paths: tuple[str, ...]
    target_ranges: tuple[str, ...]
    body_fingerprints: tuple[str, ...]
    evidence_basis: tuple[str, ...]
    classification: str
    scope_state: str
    owner: str
    blocking: bool
    compute_route: str
    proposed_validations: tuple[str, ...]
    duplicate_of: str | None = None
    execution_authorized: bool = False
    external_write_authorized: bool = False
    merge_authorized: bool = False
    side_effects_performed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RemediationTask:
    task_id: str
    finding_ids: tuple[str, ...]
    source_thread_ids: tuple[str, ...]
    affected_files: tuple[str, ...]
    owner: str
    risk: str
    requested_summary: str
    prohibited_changes: tuple[str, ...]
    proposed_validations: tuple[str, ...]
    blockers: tuple[str, ...]
    compute_route: str
    handoff_ready: bool
    execution_authorized: bool = False
    external_write_authorized: bool = False
    merge_authorized: bool = False
    side_effects_performed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RemediationPlan:
    repository: str
    pr_number: int
    head_sha: str
    finding_ids: tuple[str, ...]
    task_ids: tuple[str, ...]
    findings: tuple[PlannedFinding, ...]
    tasks: tuple[RemediationTask, ...]
    optional_failure_evidence_id: str | None = None
    optional_repair_handoff_id: str | None = None
    execution_authorized: bool = False
    external_write_authorized: bool = False
    merge_authorized: bool = False
    side_effects_performed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def evidence_id(self) -> str:
        return deterministic_id(self.to_dict())


def _exact(value: Any, expected: type, field: str) -> None:
    if type(value) is not expected:
        raise EvidenceValidationError(f"{field} must be exactly {expected.__name__}")


def _string(value: Any, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    _exact(value, str, field)
    if not value or len(value) > MAX_STRING_LENGTH:
        raise EvidenceValidationError(f"{field} must be non-empty and within size limits")
    return value


def _string_sequence(value: Any, field: str, *, max_items: int = MAX_ITEMS) -> tuple[str, ...]:
    if type(value) not in {list, tuple}:
        raise EvidenceValidationError(f"{field} must be a list or tuple")
    if len(value) > max_items:
        raise EvidenceValidationError(f"{field} exceeds size limit")
    result: list[str] = []
    for index, item in enumerate(value):
        text = _string(item, f"{field}[{index}]")
        assert text is not None
        result.append(text)
    if len(set(result)) != len(result):
        raise EvidenceValidationError(f"{field} contains duplicates")
    return tuple(result)


def _authority_false(payload: dict[str, Any]) -> None:
    for field in AUTHORITY_FIELDS:
        value = payload.get(field, False)
        _exact(value, bool, field)
        if value:
            raise EvidenceValidationError(f"{field} must remain false")


def _normalize_candidate(payload: Any) -> FindingCandidate:
    _exact(payload, dict, "finding candidate")
    if any(type(key) is not str for key in payload):
        raise EvidenceValidationError("finding candidate keys must be strings")
    unknown = set(payload) - _CANDIDATE_FIELDS
    if unknown:
        raise EvidenceValidationError(f"unknown finding candidate fields: {', '.join(sorted(unknown))}")
    _authority_false(payload)

    finding_identity = _string(payload.get("finding_identity"), "finding_identity")
    rule_id = _string(payload.get("rule_id"), "rule_id")
    requested_outcome = _string(payload.get("requested_outcome"), "requested_outcome")
    owner = _string(payload.get("owner"), "owner")
    risk = _string(payload.get("risk"), "risk")
    requested_summary = _string(payload.get("requested_summary"), "requested_summary")
    assert finding_identity and rule_id and requested_outcome and owner and risk and requested_summary
    if risk not in RISKS:
        raise EvidenceValidationError("risk must be low, medium, or high")

    source_thread_ids = _string_sequence(payload.get("source_thread_ids"), "source_thread_ids")
    if not source_thread_ids:
        raise EvidenceValidationError("source_thread_ids must not be empty")
    affected_files = tuple(sorted(_string_sequence(payload.get("affected_files"), "affected_files", max_items=MAX_FILES)))
    if not affected_files:
        raise EvidenceValidationError("affected_files must not be empty")
    proposed_validations = tuple(sorted(_string_sequence(payload.get("proposed_validations", []), "proposed_validations")))
    evidence_basis = tuple(sorted(_string_sequence(payload.get("evidence_basis", []), "evidence_basis")))

    semantic_ambiguity = payload.get("semantic_ambiguity", False)
    already_fixed_condition_absent = payload.get("already_fixed_condition_absent", False)
    _exact(semantic_ambiguity, bool, "semantic_ambiguity")
    _exact(already_fixed_condition_absent, bool, "already_fixed_condition_absent")
    high_reasoning_reason = _string(payload.get("high_reasoning_reason"), "high_reasoning_reason", optional=True)
    manual_decision_reason = _string(payload.get("manual_decision_reason"), "manual_decision_reason", optional=True)
    already_fixed_head_sha = _string(payload.get("already_fixed_head_sha"), "already_fixed_head_sha", optional=True)
    if already_fixed_head_sha is not None:
        if len(already_fixed_head_sha) != 40 or any(char not in "0123456789abcdef" for char in already_fixed_head_sha.lower()):
            raise EvidenceValidationError("already_fixed_head_sha must be a 40-character hexadecimal SHA")
        already_fixed_head_sha = already_fixed_head_sha.lower()
    if already_fixed_condition_absent and already_fixed_head_sha is None:
        raise EvidenceValidationError("already-fixed evidence requires an exact head SHA")

    identity_payload = {
        "finding_identity": finding_identity,
        "rule_id": rule_id,
        "requested_outcome_fingerprint": deterministic_id(requested_outcome),
        "source_thread_ids": source_thread_ids,
        "affected_files": affected_files,
        "owner": owner,
        "risk": risk,
        "requested_summary": requested_summary,
        "proposed_validations": proposed_validations,
        "evidence_basis": evidence_basis,
        "semantic_ambiguity": semantic_ambiguity,
        "high_reasoning_reason": high_reasoning_reason,
        "manual_decision_reason": manual_decision_reason,
        "already_fixed_head_sha": already_fixed_head_sha,
        "already_fixed_condition_absent": already_fixed_condition_absent,
    }
    return FindingCandidate(
        candidate_id=deterministic_id(identity_payload),
        finding_identity=finding_identity,
        rule_id=rule_id,
        requested_outcome_fingerprint=deterministic_id(requested_outcome),
        source_thread_ids=source_thread_ids,
        affected_files=affected_files,
        owner=owner,
        risk=risk,
        requested_summary=requested_summary,
        proposed_validations=proposed_validations,
        evidence_basis=evidence_basis,
        semantic_ambiguity=semantic_ambiguity,
        high_reasoning_reason=high_reasoning_reason,
        manual_decision_reason=manual_decision_reason,
        already_fixed_head_sha=already_fixed_head_sha,
        already_fixed_condition_absent=already_fixed_condition_absent,
    )


def _target_range(thread: NormalizedReviewThread) -> str | None:
    if thread.path is None or thread.line is None:
        return None
    start = thread.start_line or thread.line
    side = thread.side or ""
    return f"{thread.path}:{start}-{thread.line}:{side}"


def _optional_evidence_id(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if type(value) is not dict:
        raise EvidenceValidationError(f"{field} must be a built-in dictionary when supplied")
    serialized = canonical_json(value)
    if len(serialized) > MAX_OPTIONAL_EVIDENCE_CHARS:
        raise EvidenceValidationError(f"{field} exceeds size limit")
    return deterministic_id(value)


def _route_for(candidate: FindingCandidate, classification: str) -> str:
    if classification in {"missing-evidence", "out-of-scope", "manual-review-required"}:
        return "manual-decision-required"
    if classification == "conflicting":
        return "high-reasoning-required"
    if classification in {"duplicate", "outdated", "already-fixed"}:
        return "no-model"
    if candidate.manual_decision_reason:
        return "manual-decision-required"
    if candidate.high_reasoning_reason:
        return "high-reasoning-required"
    if candidate.semantic_ambiguity:
        return "small-model-eligible"
    return "no-model"


def _task_blockers(classification: str, candidate: FindingCandidate) -> tuple[str, ...]:
    if classification == "conflicting":
        return ("conflicting supplied findings require high-reasoning review",)
    if classification == "out-of-scope":
        return ("finding exceeds the supplied authorized file scope",)
    if classification == "missing-evidence":
        return ("required exact-current evidence is incomplete or stale",)
    if classification == "manual-review-required":
        return (candidate.manual_decision_reason or "manual decision is required",)
    return ()


def plan_remediation(
    snapshot: NormalizedPRSnapshot,
    review_threads: tuple[NormalizedReviewThread, ...],
    candidate_payloads: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    allowed_files: tuple[str, ...] | list[str],
    *,
    failure_evidence: dict[str, Any] | None = None,
    repair_handoff: dict[str, Any] | None = None,
) -> RemediationPlan:
    """Build a bounded deterministic plan from immutable caller-supplied evidence."""

    if type(snapshot) is not NormalizedPRSnapshot:
        raise EvidenceValidationError("snapshot must be a NormalizedPRSnapshot")
    if type(review_threads) is not tuple:
        raise EvidenceValidationError("review_threads must be a tuple")
    if len(review_threads) > MAX_ITEMS:
        raise EvidenceValidationError("review_threads exceeds size limit")
    if any(type(thread) is not NormalizedReviewThread for thread in review_threads):
        raise EvidenceValidationError("review_threads must contain only NormalizedReviewThread values")

    thread_ids = [thread.thread_id for thread in review_threads]
    comment_ids = [thread.top_level_comment_id for thread in review_threads]
    if len(set(thread_ids)) != len(thread_ids) or len(set(comment_ids)) != len(comment_ids):
        raise EvidenceValidationError("review_threads contains duplicate identities")
    thread_by_id = {thread.thread_id: thread for thread in review_threads}

    allowed = frozenset(_string_sequence(allowed_files, "allowed_files", max_items=MAX_FILES))
    if type(candidate_payloads) not in {list, tuple}:
        raise EvidenceValidationError("candidate_payloads must be a list or tuple")
    if len(candidate_payloads) > MAX_CANDIDATES:
        raise EvidenceValidationError("candidate_payloads exceeds size limit")
    candidates = tuple(_normalize_candidate(payload) for payload in candidate_payloads)
    if len({candidate.candidate_id for candidate in candidates}) != len(candidates):
        raise EvidenceValidationError("candidate_payloads contains exact duplicate payloads")

    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        referenced = tuple(thread_by_id[thread_id] for thread_id in candidate.source_thread_ids if thread_id in thread_by_id)
        missing_ids = tuple(sorted(set(candidate.source_thread_ids) - set(thread_by_id)))
        ranges = tuple(sorted(filter(None, (_target_range(thread) for thread in referenced))))
        paths = tuple(sorted(set(candidate.affected_files) | {thread.path for thread in referenced if thread.path is not None}))
        outside = tuple(path for path in candidate.affected_files if path not in allowed)
        thread_classes = tuple(thread.classification for thread in referenced)

        evidence = list(candidate.evidence_basis)
        classification = "actionable"
        scope_state = "inside-scope"
        if candidate.manual_decision_reason:
            classification = "manual-review-required"
        elif missing_ids or any(value == "unavailable" for value in thread_classes):
            classification = "missing-evidence"
            evidence.extend(f"missing-thread:{thread_id}" for thread_id in missing_ids)
        elif referenced and all(value in {"outdated", "superseded"} for value in thread_classes):
            classification = "outdated"
        elif outside:
            classification = "out-of-scope"
            scope_state = "outside-scope"
            evidence.extend(f"outside-scope:{path}" for path in outside)
        elif candidate.already_fixed_condition_absent:
            if candidate.already_fixed_head_sha == snapshot.head_sha:
                classification = "already-fixed"
                evidence.append(f"condition-absent-at-head:{snapshot.head_sha}")
            else:
                classification = "missing-evidence"
                evidence.append("already-fixed proof does not match current head")

        base_key = (
            snapshot.repository,
            snapshot.pr_number,
            snapshot.head_sha,
            ranges,
            candidate.finding_identity,
            candidate.rule_id,
        )
        exact_key = (*base_key, candidate.requested_outcome_fingerprint)
        finding_id = deterministic_id(
            {
                "repository": snapshot.repository,
                "pr_number": snapshot.pr_number,
                "head_sha": snapshot.head_sha,
                "candidate_id": candidate.candidate_id,
            }
        )
        rows.append(
            {
                "candidate": candidate,
                "referenced": referenced,
                "ranges": ranges,
                "paths": paths,
                "evidence": tuple(sorted(set(evidence))),
                "classification": classification,
                "scope_state": scope_state,
                "base_key": base_key,
                "exact_key": exact_key,
                "finding_id": finding_id,
                "duplicate_of": None,
            }
        )

    actionable_rows = [row for row in rows if row["classification"] == "actionable"]
    exact_groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in actionable_rows:
        exact_groups.setdefault(row["exact_key"], []).append(row)
    canonical_rows: list[dict[str, Any]] = []
    for group in exact_groups.values():
        ordered = sorted(group, key=lambda row: row["candidate"].candidate_id)
        canonical = ordered[0]
        canonical_rows.append(canonical)
        for duplicate in ordered[1:]:
            duplicate["classification"] = "duplicate"
            duplicate["duplicate_of"] = canonical["finding_id"]

    base_groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in canonical_rows:
        base_groups.setdefault(row["base_key"], []).append(row)
    for group in base_groups.values():
        outcomes = {row["candidate"].requested_outcome_fingerprint for row in group}
        if len(outcomes) > 1:
            for row in group:
                row["classification"] = "conflicting"

    findings: list[PlannedFinding] = []
    tasks: list[RemediationTask] = []
    prohibited_changes = (
        "broaden-scope-without-authorization",
        "resolve-review-thread",
        "write-github",
        "merge-or-auto-merge",
        "external-write",
    )
    for row in sorted(rows, key=lambda item: item["finding_id"]):
        candidate = row["candidate"]
        classification = row["classification"]
        if classification not in FINDING_CLASSIFICATIONS:
            raise EvidenceValidationError("planner produced unsupported classification")
        route = _route_for(candidate, classification)
        if route not in COMPUTE_ROUTES:
            raise EvidenceValidationError("planner produced unsupported compute route")
        referenced = row["referenced"]
        finding = PlannedFinding(
            finding_id=row["finding_id"],
            candidate_id=candidate.candidate_id,
            source_thread_ids=tuple(sorted(candidate.source_thread_ids)),
            reviewer_identities=tuple(sorted({thread.reviewer for thread in referenced})),
            target_paths=row["paths"],
            target_ranges=row["ranges"],
            body_fingerprints=tuple(sorted({thread.body_fingerprint for thread in referenced})),
            evidence_basis=row["evidence"],
            classification=classification,
            scope_state=row["scope_state"],
            owner=candidate.owner,
            blocking=classification in {"conflicting", "out-of-scope", "missing-evidence", "manual-review-required"},
            compute_route=route,
            proposed_validations=candidate.proposed_validations,
            duplicate_of=row["duplicate_of"],
        )
        findings.append(finding)

        if classification not in {"duplicate", "outdated", "already-fixed"}:
            blockers = _task_blockers(classification, candidate)
            task_payload = {
                "finding_ids": (finding.finding_id,),
                "source_thread_ids": finding.source_thread_ids,
                "affected_files": candidate.affected_files,
                "owner": candidate.owner,
                "risk": candidate.risk,
                "requested_summary": candidate.requested_summary,
                "proposed_validations": candidate.proposed_validations,
                "compute_route": route,
                "blockers": blockers,
            }
            tasks.append(
                RemediationTask(
                    task_id=deterministic_id(task_payload),
                    finding_ids=(finding.finding_id,),
                    source_thread_ids=finding.source_thread_ids,
                    affected_files=candidate.affected_files,
                    owner=candidate.owner,
                    risk=candidate.risk,
                    requested_summary=candidate.requested_summary,
                    prohibited_changes=prohibited_changes,
                    proposed_validations=candidate.proposed_validations,
                    blockers=blockers,
                    compute_route=route,
                    handoff_ready=classification == "actionable" and not blockers,
                )
            )

    findings_tuple = tuple(findings)
    tasks_tuple = tuple(sorted(tasks, key=lambda task: task.task_id))
    return RemediationPlan(
        repository=snapshot.repository,
        pr_number=snapshot.pr_number,
        head_sha=snapshot.head_sha,
        finding_ids=tuple(finding.finding_id for finding in findings_tuple),
        task_ids=tuple(task.task_id for task in tasks_tuple),
        findings=findings_tuple,
        tasks=tasks_tuple,
        optional_failure_evidence_id=_optional_evidence_id(failure_evidence, "failure_evidence"),
        optional_repair_handoff_id=_optional_evidence_id(repair_handoff, "repair_handoff"),
    )
