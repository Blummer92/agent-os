from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .issue_metadata import load_issue_form_fields, metadata_contract, parse_issue_form_body
from .label_map import expected_labels, load_label_map

_MANAGED_PREFIXES = ("owner:", "status:", "type:", "epic:")
_MANAGED_EXACT = {"agent-os"}


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


def reconcile_issue_labels(
    provider: IssueLabelProvider,
    repository: str,
    issue_number: int,
    *,
    issue_form_path: str | Path,
    label_map_path: str | Path,
    dry_run: bool = True,
    label_write_authorized: bool = False,
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
    owners = tuple(sorted(label for label in desired_managed if label.startswith("owner:")))
    statuses = tuple(sorted(label for label in desired_managed if label.startswith("status:")))
    if len(owners) != 1 or len(statuses) != 1:
        return _result(initial, (), (), (), "manual-review", ("ambiguous-owner-or-readiness",), dry_run)

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
    if not label_write_authorized:
        return _result(initial, desired_managed, to_add, to_remove, "blocked", ("label-write-authorization-required",), False, unmanaged)

    current = provider.read(repository, issue_number)
    if current.body != initial.body or current.labels != initial.labels or current.state != initial.state:
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


def _is_managed(label: str) -> bool:
    return label in _MANAGED_EXACT or label.startswith(_MANAGED_PREFIXES)


def _result(snapshot, desired, add, remove, status, reasons, dry_run, unmanaged=(), changed=False):
    return IssueLabelReconciliationResult(snapshot.repository, snapshot.issue_number, tuple(sorted(desired)), tuple(add), tuple(remove), tuple(unmanaged), status, tuple(reasons), dry_run, changed)
