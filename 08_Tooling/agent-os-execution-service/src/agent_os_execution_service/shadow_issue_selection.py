"""Read-only whole-population shadow issue selection for #2832.

This module is a thin execution-service composition seam. It reuses the
canonical paginated issue scanner, caller-supplied canonical candidate evidence,
the existing executable-lane selector, and the existing single-issue live reader.
It performs no mutation or execution and creates no priority or authority.

Narrowing rule (Phase 0 Shadow Admission): narrowing is always explicit and
caller-declared. The caller supplies a bounded candidate set plus a
``narrowing_criterion`` naming the deterministic rule it applied (for example
``"explicit-request:operator-shortlist-2026-10-05"``). This module proves every
narrowed candidate is a member of the complete scanned population, enforces the
64-candidate bound, records the criterion on the result, and advertises
``shadow-selection.population-narrowed`` on every narrowed result. It never
invents a priority, rank, age, or popularity rule to narrow silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Literal, Protocol

from instructional_workflow_contracts.request_interpretation import RequestInterpretation
from agent_os_execution_service.cohort_admission import (
    CohortAdmissionResult,
    CohortAdmissionStatus,
    admit_request_cohort,
)
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
_UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class ShadowSelectionStatus(str, Enum):
    SELECTED = "selected"
    NO_SELECTION = "no-selection"
    REPLAN_REQUIRED = "replan-required"


REASON_CODES = frozenset(
    {
        "shadow-selection.current",
        "shadow-selection.population-incomplete",
        "shadow-selection.population-narrowed",
        "shadow-selection.cohort-admission-failed",
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


def _validate_narrowing_criterion(value: str | None) -> str | None:
    """Validate the caller-declared deterministic narrowing rule name."""
    if value is None:
        return None
    if type(value) is not str:
        raise TypeError("narrowing_criterion must be exact text or None")
    if not 1 <= len(value) <= 128:
        raise ValueError("narrowing_criterion must be 1 to 128 characters")
    if value != value.strip() or not value.isprintable():
        raise ValueError("narrowing_criterion must be stripped printable text")
    return value


@dataclass(frozen=True, slots=True)
class ScanPageProvenance:
    """One scanned page's transport provenance (Phase 1 B5).

    Records exactly what the page reader observed while fetching a single
    page: the requested 1-based page index, the exact source query string
    (state/per_page/page params), the per-page item count, the next-page
    cursor (integer cursor plus the observed ``Link`` next URL), terminal-page
    proof state, the observed rate-limit remainder, and any error kind.
    Provenance never manufactures state: every field is an observation made
    by the reader that served the page. A recorded scan is reconstructible
    from these fields alone.
    """

    page: int
    item_count: int
    next_page: int | None
    source_query_string: str | None
    link_next_url: str | None
    rate_limit_remaining: str | None
    terminal_page_proven: bool
    error_kind: str | None

    def __post_init__(self) -> None:
        if type(self.page) is not int or self.page < 1:
            raise TypeError("page must be a positive exact integer")
        if type(self.item_count) is not int or self.item_count < 0:
            raise TypeError("item_count must be a non-negative exact integer")
        if self.next_page is not None and (
            type(self.next_page) is not int or self.next_page < 1
        ):
            raise TypeError("next_page must be a positive exact integer or None")
        if self.source_query_string is not None and (
            type(self.source_query_string) is not str
            or not self.source_query_string.strip()
        ):
            raise ValueError("source_query_string must be non-empty text or None")
        if self.link_next_url is not None and (
            type(self.link_next_url) is not str or not self.link_next_url
        ):
            raise ValueError("link_next_url must be non-empty text or None")
        if self.rate_limit_remaining is not None and type(self.rate_limit_remaining) is not str:
            raise TypeError("rate_limit_remaining must be exact text or None")
        if type(self.terminal_page_proven) is not bool:
            raise TypeError("terminal_page_proven must be an exact bool")
        if self.error_kind is not None and type(self.error_kind) is not str:
            raise TypeError("error_kind must be exact text or None")

    def to_dict(self) -> dict[str, object]:
        return {
            "page": self.page,
            "item_count": self.item_count,
            "next_page": self.next_page,
            "source_query_string": self.source_query_string,
            "link_next_url": self.link_next_url,
            "rate_limit_remaining": self.rate_limit_remaining,
            "terminal_page_proven": self.terminal_page_proven,
            "error_kind": self.error_kind,
        }


@dataclass
class ScanProvenanceLog:
    """Mutable append-only log a page reader fills during a scan (Phase 1 B5).

    The caller creates one log, hands it to both the page reader and
    ``select_shadow_issue``, and the seam records the filled log on the
    result after the scan. ``note_page`` stamps scan start/end from the
    reader's clock: the first noted page sets ``scan_started_at``, every
    noted page refreshes ``scan_ended_at``. The log carries observations
    only; it never alters the selection.
    """

    entries: list[ScanPageProvenance] = field(default_factory=list)
    scan_started_at: str | None = None
    scan_ended_at: str | None = None

    def note_page(self, entry: ScanPageProvenance, *, at: str) -> None:
        if type(entry) is not ScanPageProvenance:
            raise TypeError("entry must be an exact ScanPageProvenance")
        if type(at) is not str or not _UTC_TIMESTAMP_RE.fullmatch(at):
            raise ValueError("at must use YYYY-MM-DDTHH:MM:SSZ form")
        if self.scan_started_at is None:
            self.scan_started_at = at
        self.scan_ended_at = at
        self.entries.append(entry)


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
    narrowing_criterion: str | None = None
    cohort_admission: CohortAdmissionResult | None = None
    # Phase 1 B5: per-page scan provenance. Additive: every field defaults so
    # all existing constructors keep working unchanged.
    scan_started_at: str | None = None
    scan_ended_at: str | None = None
    scan_source_query: str | None = None
    scan_page_provenance: tuple[ScanPageProvenance, ...] = ()
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
        # The criterion is present exactly when the run was narrowed: the only
        # production constructor (select_shadow_issue) enforces the pairing.
        object.__setattr__(
            self, "narrowing_criterion", _validate_narrowing_criterion(self.narrowing_criterion)
        )
        if self.cohort_admission is not None and type(self.cohort_admission) is not CohortAdmissionResult:
            raise TypeError("cohort_admission must be exact CohortAdmissionResult or None")
        for name in ("scan_started_at", "scan_ended_at"):
            value = getattr(self, name)
            if value is not None and (
                type(value) is not str or not _UTC_TIMESTAMP_RE.fullmatch(value)
            ):
                raise ValueError(f"{name} must use YYYY-MM-DDTHH:MM:SSZ form or None")
        if (
            self.scan_started_at is not None
            and self.scan_ended_at is not None
            and self.scan_started_at > self.scan_ended_at
        ):
            raise ValueError("scan_started_at cannot be later than scan_ended_at")
        if self.scan_source_query is not None and (
            type(self.scan_source_query) is not str or not self.scan_source_query.strip()
        ):
            raise ValueError("scan_source_query must be non-empty text or None")
        if type(self.scan_page_provenance) is not tuple or any(
            type(entry) is not ScanPageProvenance for entry in self.scan_page_provenance
        ):
            raise TypeError(
                "scan_page_provenance must be an exact tuple of ScanPageProvenance"
            )
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
    narrowing_criterion: str | None = None,
    explicit_request_order: tuple[int, ...] = (),
    request_interpretation: RequestInterpretation | None = None,
    scan_provenance_log: ScanProvenanceLog | None = None,
) -> ShadowIssueSelectionResult:
    """Return one current read-only selector result or an explicit fail-closed stop.

    candidate_issue_numbers is a caller-supplied canonical mission/request
    narrowing set. None means the whole scanned open-issue population. The set
    carries no rank semantics; explicit user order is supplied separately through
    explicit_request_order.

    An explicit narrowing set requires narrowing_criterion naming the
    deterministic rule the caller applied. Narrowing without a named rule, or a
    named rule without a narrowing set, is rejected: narrowing is never silent.

    Phase 1 B5: the caller may supply a ``ScanProvenanceLog`` shared with the
    page reader. The reader fills it during the scan; the seam records the
    filled log verbatim on the result so the decision is reconstructible.
    Provenance never alters the selection itself.
    """

    if scan_provenance_log is not None and type(scan_provenance_log) is not ScanProvenanceLog:
        raise TypeError("scan_provenance_log must be an exact ScanProvenanceLog or None")

    scan = scan_connected_issues(
        repository,
        page_reader,
        state=IssueStateFilter.OPEN,
        retrieved_at=retrieved_at,
    )
    population = tuple(record.issue_number for record in scan.records)
    scan_source_query = f"repo={repository} state={IssueStateFilter.OPEN.value}"
    if scan_provenance_log is None:
        provenance_entries: tuple[ScanPageProvenance, ...] = ()
        scan_started_at = None
        scan_ended_at = None
    else:
        provenance_entries = tuple(scan_provenance_log.entries)
        if any(type(entry) is not ScanPageProvenance for entry in provenance_entries):
            raise TypeError("scan_provenance_log holds a non-ScanPageProvenance entry")
        scan_started_at = scan_provenance_log.scan_started_at
        scan_ended_at = scan_provenance_log.scan_ended_at
    provenance_kwargs = {
        "scan_started_at": scan_started_at,
        "scan_ended_at": scan_ended_at,
        "scan_source_query": scan_source_query,
        "scan_page_provenance": provenance_entries,
    }

    if request_interpretation is not None and (
        candidate_issue_numbers is not None or narrowing_criterion is not None
    ):
        raise ValueError(
            "canonical request cohort admission cannot be combined with manual candidate narrowing"
        )
    if candidate_issue_numbers is None:
        if narrowing_criterion is not None:
            raise ValueError(
                "narrowing_criterion requires an explicit candidate_issue_numbers narrowing set"
            )
        narrowed_criterion: str | None = None
    else:
        if narrowing_criterion is None:
            raise ValueError(
                "explicit candidate narrowing requires narrowing_criterion "
                "naming the deterministic rule applied"
            )
        narrowed_criterion = _validate_narrowing_criterion(narrowing_criterion)

    cohort_admission: CohortAdmissionResult | None = None
    if not scan.complete:
        return _result(
            repository=repository,
            retrieved_at=retrieved_at,
            population=population,
            candidates=(),
            scan_page_count=scan.page_count,
            scan_item_count=scan.item_count,
            reason="shadow-selection.population-incomplete",
            narrowing_criterion=narrowed_criterion,
            cohort_admission=cohort_admission,
            **provenance_kwargs,
        )

    records = {record.issue_number: record for record in scan.records}
    if request_interpretation is not None:
        cohort_admission = admit_request_cohort(
            repository=repository,
            population_issue_numbers=population,
            population_source_query=scan_source_query,
            request_interpretation=request_interpretation,
        )
        narrowed_criterion = (
            f"canonical-request:{cohort_admission.request_constraint_identity}"
            if cohort_admission.request_constraint_identity is not None
            else "canonical-request:unresolved"
        )
        candidates = cohort_admission.candidate_issue_numbers
        if cohort_admission.status is CohortAdmissionStatus.FAIL_CLOSED:
            return _result(
                repository=repository,
                retrieved_at=retrieved_at,
                population=population,
                candidates=candidates,
                scan_page_count=scan.page_count,
                scan_item_count=scan.item_count,
                reason="shadow-selection.cohort-admission-failed",
                narrowing_criterion=narrowed_criterion,
                cohort_admission=cohort_admission,
                **provenance_kwargs,
            )
    elif candidate_issue_numbers is None:
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
            narrowing_criterion=narrowed_criterion,
            cohort_admission=cohort_admission,
            **provenance_kwargs,
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
            narrowing_criterion=narrowed_criterion,
            cohort_admission=cohort_admission,
            **provenance_kwargs,
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
            narrowing_criterion=narrowed_criterion,
            cohort_admission=cohort_admission,
            **provenance_kwargs,
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
                narrowing_criterion=narrowed_criterion,
                **provenance_kwargs,
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
                narrowing_criterion=narrowed_criterion,
                **provenance_kwargs,
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
                narrowing_criterion=narrowed_criterion,
                **provenance_kwargs,
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
                narrowing_criterion=narrowed_criterion,
                **provenance_kwargs,
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
            narrowing_criterion=narrowed_criterion,
            cohort_admission=cohort_admission,
            **provenance_kwargs,
        )
    repository_source_revision = next(iter(repository_revisions))

    selection = select_executable_lanes(
        campaign_id=campaign_id,
        requested_lane_count=1,
        substitution_allowed=False,
        explicit_request_order=explicit_request_order,
        candidates=tuple(evidence),
        population_source_query=scan_source_query,
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
            narrowing_criterion=narrowed_criterion,
            cohort_admission=cohort_admission,
            **provenance_kwargs,
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
            narrowing_criterion=narrowed_criterion,
            cohort_admission=cohort_admission,
            **provenance_kwargs,
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
            narrowing_criterion=narrowed_criterion,
            cohort_admission=cohort_admission,
            **provenance_kwargs,
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
            narrowing_criterion=narrowed_criterion,
            cohort_admission=cohort_admission,
            **provenance_kwargs,
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
        reason_codes=(
            ("shadow-selection.current",)
            if narrowed_criterion is None
            else ("shadow-selection.current", "shadow-selection.population-narrowed")
        ),
        narrowing_criterion=narrowed_criterion,
        cohort_admission=cohort_admission,
        **provenance_kwargs,
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
    narrowing_criterion: str | None = None,
    cohort_admission: CohortAdmissionResult | None = None,
    status: ShadowSelectionStatus = ShadowSelectionStatus.NO_SELECTION,
    repository_source_revision: str | None = None,
    selection: ExecutableLaneSelection | None = None,
    scan_started_at: str | None = None,
    scan_ended_at: str | None = None,
    scan_source_query: str | None = None,
    scan_page_provenance: tuple[ScanPageProvenance, ...] = (),
) -> ShadowIssueSelectionResult:
    reasons = (reason,) if narrowing_criterion is None else (
        reason,
        "shadow-selection.population-narrowed",
    )
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
        reason_codes=reasons,
        narrowing_criterion=narrowing_criterion,
        cohort_admission=cohort_admission,
        scan_started_at=scan_started_at,
        scan_ended_at=scan_ended_at,
        scan_source_query=scan_source_query,
        scan_page_provenance=scan_page_provenance,
    )
