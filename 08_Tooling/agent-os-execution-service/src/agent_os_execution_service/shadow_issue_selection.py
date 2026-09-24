"""Read-only whole-population shadow issue selection for #2832.

This module is a thin execution-service composition seam. It reuses the
canonical paginated issue scanner, caller-supplied canonical candidate evidence,
the existing executable-lane selector, and the existing single-issue live reader.
It performs no mutation or execution and creates no priority or authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Literal, Protocol

from scripts.agent_os_candidate_packet.executable_lane_selection import (
    MAX_CANDIDATES,
    CandidateIssueEvidence,
    ExecutableLaneSelection,
    select_executable_lanes,
)
from scripts.agent_os_candidate_packet.stage_models import IssueReadStatus
from scripts.agent_os_candidate_packet_live_input import (
    LiveIssueReader,
    SingleIssueTransport,
)
from scripts.agent_os_github_issue_provider.revision import issue_source_revision
from scripts.agent_os_issue_acceptance.github_issue_source import (
    GitHubIssuePageReader,
    scan_connected_issues,
)
from scripts.agent_os_issue_acceptance.issue_scanner import IssueStateFilter


_ISSUE_REVISION_RE = re.compile(r"^github-issue-v1:[0-9a-f]{64}$")


class ShadowSelectionStatus(str, Enum):
    SELECTED = "selected"
    NO_SELECTION = "no-selection"
    REPLAN_REQUIRED = "replan-required"


REASON_CODES = frozenset(
    {
        "shadow-selection.current",
        "shadow-selection.population-incomplete",
        "shadow-selection.candidate-population-empty",
        "shadow-selection.candidate-population-too-broad",
        "shadow-selection.candidate-not-in-population",
        "shadow-selection.candidate-evidence-incomplete",
        "shadow-selection.candidate-repository-mismatch",
        "shadow-selection.issue-revision-unavailable",
        "shadow-selection.candidate-revision-mismatch",
        "shadow-selection.repository-revision-conflict",
        "shadow-selection.selector-no-executable-lane",
        "shadow-selection.selected-issue-reacquire-failed",
        "shadow-selection.selected-issue-changed",
    }
)


class CanonicalCandidateEvidenceReader(Protocol):
    """Supply already-canonical state/mode evidence for one bounded candidate."""

    def read_candidate_evidence(
        self, repository: str, issue_number: int
    ) -> CandidateIssueEvidence | None: ...


@dataclass(frozen=True, slots=True)
class ShadowIssueSelectionResult:
    repository: str
    retrieved_at: str
    population_issue_numbers: tuple[int, ...]
    candidate_issue_numbers: tuple[int, ...]
    scan_page_count: int
    scan_item_count: int
    repository_source_revision: str | None
    selection: ExecutableLaneSelection | None
    selected_issue_number: int | None
    selected_issue_revision: str | None
    status: ShadowSelectionStatus
    reason_codes: tuple[str, ...]
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if type(self.repository) is not str or self.repository.count("/") != 1:
            raise ValueError("repository must use owner/name form")
        if type(self.retrieved_at) is not str or not self.retrieved_at:
            raise ValueError("retrieved_at must be non-empty text")
        for name in ("population_issue_numbers", "candidate_issue_numbers"):
            values = getattr(self, name)
            if type(values) is not tuple or any(type(v) is not int or v < 1 for v in values):
                raise TypeError(f"{name} must be an exact tuple of positive integers")
            if tuple(sorted(set(values))) != values:
                raise ValueError(f"{name} must be sorted and unique")
        if type(self.scan_page_count) is not int or self.scan_page_count < 1:
            raise TypeError("scan_page_count must be a positive exact integer")
        if type(self.scan_item_count) is not int or self.scan_item_count < 0:
            raise TypeError("scan_item_count must be a non-negative exact integer")
        if self.repository_source_revision is not None and (
            type(self.repository_source_revision) is not str
            or len(self.repository_source_revision) != 40
            or any(c not in "0123456789abcdef" for c in self.repository_source_revision)
        ):
            raise ValueError("repository_source_revision must be a lowercase 40-character SHA")
        if self.selection is not None and type(self.selection) is not ExecutableLaneSelection:
            raise TypeError("selection must be exact ExecutableLaneSelection or None")
        if self.selected_issue_number is not None and (
            type(self.selected_issue_number) is not int or self.selected_issue_number < 1
        ):
            raise TypeError("selected_issue_number must be a positive exact integer or None")
        if self.selected_issue_revision is not None and (
            type(self.selected_issue_revision) is not str
            or not _ISSUE_REVISION_RE.fullmatch(self.selected_issue_revision)
        ):
            raise ValueError("selected_issue_revision must use github-issue-v1:<sha256>")
        if not isinstance(self.status, ShadowSelectionStatus):
            raise TypeError("status must be ShadowSelectionStatus")
        reasons = tuple(sorted(set(self.reason_codes)))
        if not reasons or any(reason not in REASON_CODES for reason in reasons):
            raise ValueError("reason_codes contains an unsupported reason")
        object.__setattr__(self, "reason_codes", reasons)
        if self.status is ShadowSelectionStatus.SELECTED:
            if self.selection is None or self.selected_issue_number is None:
                raise ValueError("selected status requires selection and selected issue")
            if self.selected_issue_revision is None:
                raise ValueError("selected status requires selected issue revision")
            if self.selection.selected_lanes != (self.selected_issue_number,):
                raise ValueError("selected issue must equal the selector's one selected lane")
        elif self.selected_issue_number is not None or self.selected_issue_revision is not None:
            raise ValueError("non-selected status cannot expose a current selected issue")
        if self.execution_authorized is not False or self.side_effects_performed is not False:
            raise ValueError("shadow selection cannot authorize execution or record side effects")


def select_shadow_issue(
    *,
    repository: str,
    retrieved_at: str,
    campaign_id: str,
    page_reader: GitHubIssuePageReader,
    issue_transport: SingleIssueTransport,
    candidate_evidence_reader: CanonicalCandidateEvidenceReader,
    candidate_issue_numbers: tuple[int, ...] | None = None,
    explicit_request_order: tuple[int, ...] = (),
) -> ShadowIssueSelectionResult:
    """Return one current read-only selector result or an explicit fail-closed stop.

    candidate_issue_numbers is a caller-supplied canonical mission/request
    narrowing set. None means the whole scanned open-issue population. The set
    carries no rank semantics; explicit user order is supplied separately through
    explicit_request_order.
    """

    scan = scan_connected_issues(
        repository,
        page_reader,
        state=IssueStateFilter.OPEN,
        retrieved_at=retrieved_at,
    )
    population = tuple(record.issue_number for record in scan.records)

    if not scan.complete:
        return _result(
            repository=repository,
            retrieved_at=retrieved_at,
            population=population,
            candidates=(),
            scan_page_count=scan.page_count,
            scan_item_count=scan.item_count,
            reason="shadow-selection.population-incomplete",
        )

    records = {record.issue_number: record for record in scan.records}
    if candidate_issue_numbers is None:
        candidates = population
    else:
        if type(candidate_issue_numbers) is not tuple or any(
            type(value) is not int or value < 1 for value in candidate_issue_numbers
        ):
            raise TypeError("candidate_issue_numbers must be an exact tuple of positive integers")
        if len(set(candidate_issue_numbers)) != len(candidate_issue_numbers):
            raise ValueError("candidate_issue_numbers contains duplicates")
        candidates = tuple(sorted(candidate_issue_numbers))

    if type(explicit_request_order) is not tuple or any(
        type(value) is not int or value < 1 for value in explicit_request_order
    ):
        raise TypeError("explicit_request_order must be an exact tuple of positive integers")
    if len(set(explicit_request_order)) != len(explicit_request_order):
        raise ValueError("explicit_request_order contains duplicates")
    if any(value not in candidates for value in explicit_request_order):
        raise ValueError("explicit_request_order references a non-candidate issue")

    if not candidates:
        return _result(
            repository=repository,
            retrieved_at=retrieved_at,
            population=population,
            candidates=candidates,
            scan_page_count=scan.page_count,
            scan_item_count=scan.item_count,
            reason="shadow-selection.candidate-population-empty",
        )
    if any(issue_number not in records for issue_number in candidates):
        return _result(
            repository=repository,
            retrieved_at=retrieved_at,
            population=population,
            candidates=candidates,
            scan_page_count=scan.page_count,
            scan_item_count=scan.item_count,
            reason="shadow-selection.candidate-not-in-population",
        )
    if len(candidates) > MAX_CANDIDATES:
        return _result(
            repository=repository,
            retrieved_at=retrieved_at,
            population=population,
            candidates=candidates,
            scan_page_count=scan.page_count,
            scan_item_count=scan.item_count,
            reason="shadow-selection.candidate-population-too-broad",
        )

    evidence: list[CandidateIssueEvidence] = []
    repository_revisions: set[str] = set()
    for issue_number in candidates:
        candidate = candidate_evidence_reader.read_candidate_evidence(
            repository, issue_number
        )
        if type(candidate) is not CandidateIssueEvidence:
            return _result(
                repository=repository,
                retrieved_at=retrieved_at,
                population=population,
                candidates=candidates,
                scan_page_count=scan.page_count,
                scan_item_count=scan.item_count,
                reason="shadow-selection.candidate-evidence-incomplete",
            )
        state = candidate.operational_state
        if state.repository.casefold() != repository.casefold():
            return _result(
                repository=repository,
                retrieved_at=retrieved_at,
                population=population,
                candidates=candidates,
                scan_page_count=scan.page_count,
                scan_item_count=scan.item_count,
                reason="shadow-selection.candidate-repository-mismatch",
            )
        scanned_revision = records[issue_number].source_revision
        if not _ISSUE_REVISION_RE.fullmatch(scanned_revision):
            return _result(
                repository=repository,
                retrieved_at=retrieved_at,
                population=population,
                candidates=candidates,
                scan_page_count=scan.page_count,
                scan_item_count=scan.item_count,
                reason="shadow-selection.issue-revision-unavailable",
            )
        if scanned_revision not in state.evidence_ids:
            return _result(
                repository=repository,
                retrieved_at=retrieved_at,
                population=population,
                candidates=candidates,
                scan_page_count=scan.page_count,
                scan_item_count=scan.item_count,
                reason="shadow-selection.candidate-revision-mismatch",
            )
        repository_revisions.add(state.source_revision)
        evidence.append(candidate)

    if len(repository_revisions) != 1:
        return _result(
            repository=repository,
            retrieved_at=retrieved_at,
            population=population,
            candidates=candidates,
            scan_page_count=scan.page_count,
            scan_item_count=scan.item_count,
            reason="shadow-selection.repository-revision-conflict",
        )
    repository_source_revision = next(iter(repository_revisions))

    selection = select_executable_lanes(
        campaign_id=campaign_id,
        requested_lane_count=1,
        substitution_allowed=False,
        explicit_request_order=explicit_request_order,
        candidates=tuple(evidence),
    )
    if not selection.selected_lanes:
        return _result(
            repository=repository,
            retrieved_at=retrieved_at,
            population=population,
            candidates=candidates,
            scan_page_count=scan.page_count,
            scan_item_count=scan.item_count,
            reason="shadow-selection.selector-no-executable-lane",
            repository_source_revision=repository_source_revision,
            selection=selection,
        )

    selected = selection.selected_lanes[0]
    current = LiveIssueReader(transport=issue_transport).read_issue(repository, selected)
    if current.status is not IssueReadStatus.OK or current.item is None:
        return _result(
            repository=repository,
            retrieved_at=retrieved_at,
            population=population,
            candidates=candidates,
            scan_page_count=scan.page_count,
            scan_item_count=scan.item_count,
            reason="shadow-selection.selected-issue-reacquire-failed",
            status=ShadowSelectionStatus.REPLAN_REQUIRED,
            repository_source_revision=repository_source_revision,
            selection=selection,
        )
    try:
        current_revision = issue_source_revision(current.item)
    except (TypeError, ValueError):
        return _result(
            repository=repository,
            retrieved_at=retrieved_at,
            population=population,
            candidates=candidates,
            scan_page_count=scan.page_count,
            scan_item_count=scan.item_count,
            reason="shadow-selection.selected-issue-reacquire-failed",
            status=ShadowSelectionStatus.REPLAN_REQUIRED,
            repository_source_revision=repository_source_revision,
            selection=selection,
        )
    if current_revision != records[selected].source_revision:
        return _result(
            repository=repository,
            retrieved_at=retrieved_at,
            population=population,
            candidates=candidates,
            scan_page_count=scan.page_count,
            scan_item_count=scan.item_count,
            reason="shadow-selection.selected-issue-changed",
            status=ShadowSelectionStatus.REPLAN_REQUIRED,
            repository_source_revision=repository_source_revision,
            selection=selection,
        )

    return ShadowIssueSelectionResult(
        repository=repository,
        retrieved_at=retrieved_at,
        population_issue_numbers=population,
        candidate_issue_numbers=candidates,
        scan_page_count=scan.page_count,
        scan_item_count=scan.item_count,
        repository_source_revision=repository_source_revision,
        selection=selection,
        selected_issue_number=selected,
        selected_issue_revision=current_revision,
        status=ShadowSelectionStatus.SELECTED,
        reason_codes=("shadow-selection.current",),
    )


def _result(
    *,
    repository: str,
    retrieved_at: str,
    population: tuple[int, ...],
    candidates: tuple[int, ...],
    scan_page_count: int,
    scan_item_count: int,
    reason: str,
    status: ShadowSelectionStatus = ShadowSelectionStatus.NO_SELECTION,
    repository_source_revision: str | None = None,
    selection: ExecutableLaneSelection | None = None,
) -> ShadowIssueSelectionResult:
    return ShadowIssueSelectionResult(
        repository=repository,
        retrieved_at=retrieved_at,
        population_issue_numbers=population,
        candidate_issue_numbers=candidates,
        scan_page_count=scan_page_count,
        scan_item_count=scan_item_count,
        repository_source_revision=repository_source_revision,
        selection=selection,
        selected_issue_number=None,
        selected_issue_revision=None,
        status=status,
        reason_codes=(reason,),
    )
