"""Destination-local writer for #1467 Coding Command Center guidance.

Consumes the already-computed #1097 CodingCommandCenterHandoff contract and
updates only Next Action / Blocked Reason on one existing Tasks / Issues row.
It owns no GitHub interpretation, readiness, blocker ordering, or authority.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Protocol

DATA_SOURCE_ID = "5216eacf-639d-4881-92bc-a634ead56669"
HANDOFF_SCHEMA_NAME = "agent-os-coding-command-center-handoff"
HANDOFF_SCHEMA_VERSION = "1.0"
WRITABLE_FIELDS = frozenset({"next_action", "blocked_reason"})


class WriteState(str, Enum):
    DRY_RUN = "DRY_RUN"
    PRECHECK_FAILED = "PRECHECK_FAILED"
    UPDATED = "UPDATED"
    UNCHANGED_SKIP = "UNCHANGED_SKIP"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class CodingCommandCenterHandoffEvidence:
    repository: str
    issue_number: int
    source_revision: str
    smallest_next_action: str
    primary_blocker: str | None
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PropertyBinding:
    logical_field: str
    property_name: str
    property_type: str


@dataclass(frozen=True, slots=True)
class NotionPropertySpec:
    name: str
    property_type: str


@dataclass(frozen=True, slots=True)
class NotionTaskPageEvidence:
    page_id: str
    source_link: str
    next_action: str | None
    blocked_reason: str | None


class NotionOperationalGuidanceClient(Protocol):
    def fetch_schema(self, data_source_id: str) -> tuple[NotionPropertySpec, ...]: ...
    def find_exact(self, *, data_source_id: str, property_name: str, value: str) -> tuple[NotionTaskPageEvidence, ...]: ...
    def update_page(self, *, page_id: str, properties: tuple[tuple[str, str], ...]) -> None: ...
    def fetch_page(self, page_id: str) -> NotionTaskPageEvidence | None: ...


@dataclass(frozen=True, slots=True)
class OperationalGuidanceWriteRequest:
    data_source_id: str
    source_link: str
    source_link_property_name: str
    expected_repository: str
    expected_issue_number: int
    expected_source_revision: str
    handoff: CodingCommandCenterHandoffEvidence
    next_action_binding: PropertyBinding
    blocked_reason_binding: PropertyBinding
    dry_run: bool = True


@dataclass(frozen=True, slots=True)
class OperationalGuidanceWriteResult:
    state: WriteState
    page_id: str | None
    intended_next_action: str | None
    intended_blocked_reason: str | None
    reason_codes: tuple[str, ...]
    readback_verified: bool = False
    external_write_performed: bool = False
    authority_created: Literal[False] = field(default=False, init=False)


def parse_coding_command_center_handoff(payload: object) -> CodingCommandCenterHandoffEvidence:
    if type(payload) is not dict:
        raise ValueError("handoff payload must be an exact mapping")
    if payload.get("schema_name") != HANDOFF_SCHEMA_NAME or payload.get("schema_version") != HANDOFF_SCHEMA_VERSION:
        raise ValueError("unsupported handoff schema")
    repository = payload.get("repository")
    issue_number = payload.get("issue_number")
    source_revision = payload.get("source_revision")
    next_action = payload.get("smallest_next_action")
    blocker = payload.get("primary_blocker")
    reasons = payload.get("reason_codes")
    if type(repository) is not str or "/" not in repository:
        raise ValueError("invalid repository")
    if type(issue_number) is not int or issue_number < 1:
        raise ValueError("invalid issue number")
    if type(source_revision) is not str or len(source_revision) != 40:
        raise ValueError("invalid source revision")
    if type(next_action) is not str or not next_action:
        raise ValueError("invalid smallest next action")
    if blocker is not None and (type(blocker) is not str or not blocker):
        raise ValueError("invalid primary blocker")
    if type(reasons) is not list or any(type(item) is not str for item in reasons):
        raise ValueError("invalid reason codes")
    return CodingCommandCenterHandoffEvidence(repository, issue_number, source_revision, next_action, blocker, tuple(reasons))


def plan_and_write_operational_guidance(
    request: OperationalGuidanceWriteRequest,
    client: NotionOperationalGuidanceClient | None = None,
) -> OperationalGuidanceWriteResult:
    reason = _validate_request(request)
    if reason:
        return _result(request, WriteState.PRECHECK_FAILED, (reason,))
    blocker = request.handoff.primary_blocker or ""
    if request.dry_run:
        return _result(request, WriteState.DRY_RUN, ("operational-guidance-dry-run-valid",), next_action=request.handoff.smallest_next_action, blocker=blocker)
    if client is None:
        return _result(request, WriteState.PRECHECK_FAILED, ("operational-guidance-client-required",), next_action=request.handoff.smallest_next_action, blocker=blocker)
    try:
        schema = client.fetch_schema(request.data_source_id)
    except Exception:
        return _result(request, WriteState.FAILED, ("operational-guidance-schema-read-failed",))
    expected = {
        request.source_link_property_name: "url",
        request.next_action_binding.property_name: request.next_action_binding.property_type,
        request.blocked_reason_binding.property_name: request.blocked_reason_binding.property_type,
    }
    actual = {item.name: item.property_type for item in schema}
    if any(actual.get(name) != kind for name, kind in expected.items()):
        return _result(request, WriteState.PRECHECK_FAILED, ("operational-guidance-schema-drift",))
    try:
        candidates = client.find_exact(data_source_id=request.data_source_id, property_name=request.source_link_property_name, value=request.source_link)
    except Exception:
        return _result(request, WriteState.FAILED, ("operational-guidance-target-read-failed",))
    exact = tuple(page for page in candidates if type(page) is NotionTaskPageEvidence and page.source_link == request.source_link)
    if len(exact) != 1:
        code = "operational-guidance-target-missing" if not exact else "operational-guidance-target-ambiguous"
        return _result(request, WriteState.PRECHECK_FAILED, (code,))
    page = exact[0]
    intended_next = request.handoff.smallest_next_action
    intended_blocker = blocker
    changes: list[tuple[str, str]] = []
    if page.next_action != intended_next:
        changes.append((request.next_action_binding.property_name, intended_next))
    if (page.blocked_reason or "") != intended_blocker:
        changes.append((request.blocked_reason_binding.property_name, intended_blocker))
    if not changes:
        return _verified(request, page.page_id, intended_next, intended_blocker, WriteState.UNCHANGED_SKIP, False, ("operational-guidance-unchanged",))
    try:
        client.update_page(page_id=page.page_id, properties=tuple(changes))
        readback = client.fetch_page(page.page_id)
    except Exception:
        return _result(request, WriteState.FAILED, ("operational-guidance-update-or-readback-failed",), page_id=page.page_id, next_action=intended_next, blocker=intended_blocker, external=True)
    if not _matches(readback, page.page_id, request.source_link, intended_next, intended_blocker):
        return _result(request, WriteState.FAILED, ("operational-guidance-readback-mismatch",), page_id=page.page_id, next_action=intended_next, blocker=intended_blocker, external=True)
    return _verified(request, page.page_id, intended_next, intended_blocker, WriteState.UPDATED, True, ("operational-guidance-updated-verified",))


def _validate_request(request: OperationalGuidanceWriteRequest) -> str | None:
    if type(request) is not OperationalGuidanceWriteRequest:
        return "operational-guidance-request-invalid"
    if request.data_source_id != DATA_SOURCE_ID:
        return "operational-guidance-data-source-mismatch"
    if request.source_link != f"https://github.com/{request.expected_repository}/issues/{request.expected_issue_number}":
        return "operational-guidance-source-link-identity-mismatch"
    if request.handoff.repository != request.expected_repository or request.handoff.issue_number != request.expected_issue_number:
        return "operational-guidance-handoff-identity-mismatch"
    if request.handoff.source_revision != request.expected_source_revision:
        return "operational-guidance-handoff-stale"
    bindings = (request.next_action_binding, request.blocked_reason_binding)
    if any(binding.logical_field not in WRITABLE_FIELDS or binding.property_type != "text" for binding in bindings):
        return "operational-guidance-binding-invalid"
    if {binding.logical_field for binding in bindings} != WRITABLE_FIELDS:
        return "operational-guidance-binding-invalid"
    if request.next_action_binding.property_name != "Next Action" or request.blocked_reason_binding.property_name != "Blocked Reason":
        return "operational-guidance-binding-invalid"
    if request.source_link_property_name != "Source Link":
        return "operational-guidance-source-link-binding-invalid"
    return None


def _matches(page: NotionTaskPageEvidence | None, page_id: str, source_link: str, next_action: str, blocker: str) -> bool:
    return page is not None and type(page) is NotionTaskPageEvidence and page.page_id == page_id and page.source_link == source_link and page.next_action == next_action and (page.blocked_reason or "") == blocker


def _result(request: OperationalGuidanceWriteRequest, state: WriteState, reasons: tuple[str, ...], *, page_id: str | None = None, next_action: str | None = None, blocker: str | None = None, external: bool = False) -> OperationalGuidanceWriteResult:
    return OperationalGuidanceWriteResult(state, page_id, next_action, blocker, reasons, False, external)


def _verified(request: OperationalGuidanceWriteRequest, page_id: str, next_action: str, blocker: str, state: WriteState, external: bool, reasons: tuple[str, ...]) -> OperationalGuidanceWriteResult:
    return OperationalGuidanceWriteResult(state, page_id, next_action, blocker, reasons, True, external)
