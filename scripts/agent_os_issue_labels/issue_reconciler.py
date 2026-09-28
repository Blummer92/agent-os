from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Protocol

from scripts.agent_os_issue_acceptance.lifecycle_mutation_guard import LifecycleMutationAdmissionResult
from scripts.agent_os_issue_acceptance.issue_operational_state import ReadinessState

from .issue_metadata import load_issue_form_fields, metadata_contract, parse_issue_form_body
from .label_map import expected_labels, load_label_map

_MANAGED_PREFIXES = ("owner:", "status:", "type:", "epic:")
_MANAGED_EXACT = {"agent-os"}
_ACTIVE_READINESS_LABELS = {
    ReadinessState.READY: "status:ready",
    ReadinessState.BLOCKED: "status:blocked",
    ReadinessState.NEEDS_DECISION: "status:needs-decision",
}


class IssueLabelProvider(Protocol):
    def read(self, repository: str, issue_number: int) -> "LiveIssueSnapshot": ...
    def available_labels(self, repository: str) -> tuple[str, ...]: ...
    def add_label(self, repository: str, issue_number: int, label: str) -> None: ...
    def remove_label(self, repository: str, issue_number: int, label: str) -> None: ...


@dataclass(frozen=True, slots=True)
class LiveIssueSnapshot:
    repository: str
    issue_number: int
    body: str
    labels: tuple[str, ...] = ()
    state: str = "open"


@dataclass(frozen=True, slots=True)
class LineageProjectionResult:
    repository: str
    issue_number: int
    original_parent_issue_number: int | None
    root_cause_issue_number: int | None
    projection_status: str
    reason_codes: tuple[str, ...]
    would_change_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IssueLabelReconciliationResult:
    repository: str
    issue_number: int
    desired_managed_labels: tuple[str, ...]
    labels_to_add: tuple[str, ...]
    labels_to_remove: tuple[str, ...]
    unmanaged_labels_preserved: tuple[str, ...]
    convergence_status: str
    reason_codes: tuple[str, ...]
    dry_run: bool
    side_effects_performed: bool



_LINEAGE_REF_RE = re.compile(r"^#([1-9][0-9]*)$")


def project_issue_lineage(
    provider: IssueLabelProvider,
    repository: str,
    issue_number: int,
    *,
    issue_form_path: str | Path,
    expected_original_parent: int | None = None,
    expected_root_cause: int | None = None,
) -> LineageProjectionResult:
    """Validate canonical body lineage and produce a non-mutating backfill projection."""
    snapshot = provider.read(repository, issue_number)
    fields = load_issue_form_fields(issue_form_path)
    metadata = parse_issue_form_body(snapshot.body, fields)
    if metadata_contract(metadata) != "tiered":
        return LineageProjectionResult(repository, issue_number, None, None, "manual-review", ("canonical-tiered-metadata-required",), ())

    parent, parent_reason = _single_lineage_ref(metadata, "original_parent_issue_number")
    root, root_reason = _single_lineage_ref(metadata, "root_cause_issue_number")
    reasons = tuple(reason for reason in (parent_reason, root_reason) if reason)
    if reasons:
        return LineageProjectionResult(repository, issue_number, parent, root, "manual-review", reasons, ())

    if root is not None:
        try:
            root_snapshot = provider.read(repository, root)
        except Exception as exc:
            return LineageProjectionResult(repository, issue_number, parent, root, "blocked", (f"root-cause-read-failure:{type(exc).__name__}",), ())
        if root_snapshot.state != "open":
            return LineageProjectionResult(repository, issue_number, parent, root, "blocked", ("root-cause-not-open",), ())

    changes: list[str] = []
    if expected_original_parent is not None and parent != expected_original_parent:
        changes.append("original_parent_issue_number")
    if expected_root_cause is not None and root != expected_root_cause:
        try:
            expected_root = provider.read(repository, expected_root_cause)
        except Exception as exc:
            return LineageProjectionResult(repository, issue_number, parent, root, "blocked", (f"expected-root-cause-read-failure:{type(exc).__name__}",), ())
        if expected_root.state != "open":
            return LineageProjectionResult(repository, issue_number, parent, root, "blocked", ("expected-root-cause-not-open",), ())
        changes.append("root_cause_issue_number")

    status = "would-change" if changes else "already-current"
    return LineageProjectionResult(repository, issue_number, parent, root, status, (), tuple(changes))


def project_issue_lineage_batch(
    provider: IssueLabelProvider,
    repository: str,
    issue_numbers: tuple[int, ...],
    *,
    issue_form_path: str | Path,
    expected_lineage: dict[int, tuple[int | None, int | None]] | None = None,
) -> tuple[LineageProjectionResult, ...]:
    """Finite dry-run projection that continues past item-local unresolved records."""
    expected_lineage = expected_lineage or {}
    results: list[LineageProjectionResult] = []
    for issue_number in issue_numbers:
        parent, root = expected_lineage.get(issue_number, (None, None))
        try:
            results.append(project_issue_lineage(
                provider,
                repository,
                issue_number,
                issue_form_path=issue_form_path,
                expected_original_parent=parent,
                expected_root_cause=root,
            ))
        except Exception as exc:
            results.append(LineageProjectionResult(repository, issue_number, None, None, "blocked", (f"provider-read-failure:{type(exc).__name__}",), ()))
    return tuple(results)


def _single_lineage_ref(metadata: dict[str, list[str]], field: str) -> tuple[int | None, str | None]:
    values = metadata.get(field, [])
    if not values:
        return None, None
    if len(values) != 1:
        return None, f"{field}-ambiguous"
    match = _LINEAGE_REF_RE.fullmatch(values[0].strip())
    if match is None:
        return None, f"{field}-invalid"
    return int(match.group(1)), None

def reconcile_issue_labels(
    provider: IssueLabelProvider,
    repository: str,
    issue_number: int,
    *,
    issue_form_path: str | Path,
    label_map_path: str | Path,
    dry_run: bool = True,
    lifecycle_admission: LifecycleMutationAdmissionResult | None = None,
    canonical_readiness: ReadinessState | None = None,
) -> IssueLabelReconciliationResult:
    initial = provider.read(repository, issue_number)
    fields = load_issue_form_fields(issue_form_path)
    metadata = parse_issue_form_body(initial.body, fields)
    if metadata_contract(metadata) != "tiered":
        return _result(initial, (), (), (), "manual-review", ("canonical-tiered-metadata-required",), dry_run)

    label_map = load_label_map(label_map_path)
    desired, unknown = expected_labels(metadata, label_map)
    if unknown:
        return _result(initial, (), (), (), "manual-review", ("unmapped-metadata-value",), dry_run)

    desired_managed = frozenset(label for label in desired if _is_managed(label))
    if canonical_readiness is not None:
        if type(canonical_readiness) is not ReadinessState:
            return _result(initial, (), (), (), "manual-review", ("canonical-readiness-invalid",), dry_run)
        readiness_label = _ACTIVE_READINESS_LABELS.get(canonical_readiness)
        if readiness_label is None:
            return _result(initial, (), (), (), "manual-review", ("canonical-readiness-not-active",), dry_run)
        desired_managed = frozenset(
            label for label in desired_managed if not label.startswith("status:")
        ) | {readiness_label}
    owners = tuple(sorted(label for label in desired_managed if label.startswith("owner:")))
    statuses = tuple(sorted(label for label in desired_managed if label.startswith("status:")))
    if len(owners) != 1 or len(statuses) != 1:
        return _result(initial, (), (), (), "manual-review", ("ambiguous-owner-or-readiness",), dry_run)

    if initial.state == "closed":
        desired_managed = frozenset(
            label for label in desired_managed if not label.startswith("status:")
        )

    existing = frozenset(initial.labels)
    existing_managed = frozenset(label for label in existing if _is_managed(label))
    unmanaged = tuple(sorted(existing - existing_managed))
    to_add = tuple(sorted(desired_managed - existing))
    to_remove = tuple(sorted(existing_managed - desired_managed))
    available = frozenset(provider.available_labels(repository))
    if set(to_add) - available:
        return _result(initial, desired_managed, to_add, to_remove, "blocked", ("managed-label-unavailable",), dry_run, unmanaged)

    if not to_add and not to_remove:
        return _result(initial, desired_managed, (), (), "already-current", (), dry_run, unmanaged)
    if dry_run:
        return _result(initial, desired_managed, to_add, to_remove, "would-change", (), True, unmanaged)

    admission_reason = _admission_blocker(lifecycle_admission)
    if admission_reason is not None:
        return _result(initial, desired_managed, to_add, to_remove, "blocked", (admission_reason,), False, unmanaged)

    current = provider.read(repository, issue_number)
    if current.body != initial.body or frozenset(current.labels) != frozenset(initial.labels) or current.state != initial.state:
        return _result(initial, desired_managed, to_add, to_remove, "blocked", ("issue-state-changed-before-mutation",), False, unmanaged)

    changed = False
    try:
        for label in to_add:
            provider.add_label(repository, issue_number, label)
            changed = True
        for label in to_remove:
            provider.remove_label(repository, issue_number, label)
            changed = True
    except Exception as exc:
        return _result(initial, desired_managed, to_add, to_remove, "blocked", (f"provider-write-failure:{type(exc).__name__}",), False, unmanaged, changed)

    after = provider.read(repository, issue_number)
    if after.body != initial.body or after.state != initial.state:
        return _result(initial, desired_managed, to_add, to_remove, "blocked", ("issue-state-changed-during-mutation",), False, unmanaged, changed)
    actual = frozenset(after.labels)
    actual_managed = frozenset(label for label in actual if _is_managed(label))
    if actual_managed != desired_managed or not set(unmanaged).issubset(actual):
        return _result(initial, desired_managed, to_add, to_remove, "blocked", ("readback-mismatch",), False, unmanaged, changed)
    return _result(initial, desired_managed, to_add, to_remove, "converged", (), False, unmanaged, changed)


def reconcile_issue_batch(provider: IssueLabelProvider, repository: str, issue_numbers: tuple[int, ...], **kwargs) -> tuple[IssueLabelReconciliationResult, ...]:
    results = []
    for issue_number in issue_numbers:
        try:
            results.append(reconcile_issue_labels(provider, repository, issue_number, **kwargs))
        except Exception as exc:
            results.append(IssueLabelReconciliationResult(repository, issue_number, (), (), (), (), "blocked", (f"provider-read-failure:{type(exc).__name__}",), bool(kwargs.get("dry_run", True)), False))
    return tuple(results)


def _admission_blocker(admission: LifecycleMutationAdmissionResult | None) -> str | None:
    if admission is None:
        return "lifecycle-admission-required"
    if type(admission) is not LifecycleMutationAdmissionResult:
        return "lifecycle-admission-invalid"
    if admission.requested_mutation != "replace-lifecycle-labels" or not admission.admitted:
        return "lifecycle-admission-refused"
    return None


def _is_managed(label: str) -> bool:
    return label in _MANAGED_EXACT or label.startswith(_MANAGED_PREFIXES)


def _result(snapshot, desired, add, remove, status, reasons, dry_run, unmanaged=(), changed=False):
    return IssueLabelReconciliationResult(snapshot.repository, snapshot.issue_number, tuple(sorted(desired)), tuple(add), tuple(remove), tuple(unmanaged), status, tuple(reasons), dry_run, changed)
