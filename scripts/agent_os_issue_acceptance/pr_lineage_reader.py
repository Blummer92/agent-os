"""Read-only PR-lineage evidence acquisition for the shadow lifecycle-stage path (#3441).

The #3433 evaluator (``lifecycle_stage_acquisition``) derives a
``LifecycleStage`` from caller-supplied PR-lineage facts but reads nothing. This
module is the production-reachable *source* of those facts: it enumerates the
repository's all-state pull-request population through an injected read port,
proves that enumeration complete itself, classifies every pull request against
one issue with the existing ``parse_pr`` authority, re-reads the relevant pull
requests, and hands the unchanged evaluator exactly its input types.

Reuse, not replacement
----------------------
- Linkage authority is ``parse_pr.parse_linked_issue_result``; no second parser.
- Page containers are the existing ``GitHubIssuePageResponse`` (content
  agnostic); pagination continuation proof comes from the provider's
  ``validated_next_page`` (see the CLI reader), not from this module.
- The per-issue read is ``LiveIssueReader`` over the caller's existing
  ``SingleIssueTransport``; the issue revision is the provider's
  ``issue_source_revision``.
- The lifecycle decision is the unchanged ``acquire_lifecycle_stage``.

Completeness is proven here, not asserted by the caller
-------------------------------------------------------
``PrLineageEnumeration(complete=True)`` is produced only when the enumerator
itself observed: every page read succeeded; each ``next_page`` was the
contiguous successor; the last page carried positive terminal proof; the
explicit page bound was not exhausted; every record was well formed and belongs
to this repository; and no pull request was listed twice. A repeat proves the
population shifted while it was being listed (the listing is newest-first, so a
pull request opened mid-listing pushes an older one onto the next page) and
that the newly opened pull request was never observed. Anything else (bound
exhausted, rate limit, malformed record, repeated or conflicting record, moved
default branch, list/detail disagreement) yields an *incomplete* enumeration, which the evaluator turns into a fail-closed
``unavailable`` result. An exhausted bound is never negative evidence.

Classification of a pull request against issue ``N``
----------------------------------------------------
============================  ====================================================
parse result                  treatment
============================  ====================================================
RESOLVED to ``N``             claim -> passed to the evaluator (verified there)
RESOLVED to another issue,    ambiguous claim: resolving elsewhere says nothing
also naming ``N``             about the other issues a pull request names
MANUAL_REVIEW mentioning N    ambiguous claim -> passed to the evaluator, which
                              answers ``manual-review`` (never silently dropped)
INFORMATIONAL naming ``N``    declared non-closing reference -> recorded as
                              evidence, not a claim (the author said so)
GitHub would close ``N``      ambiguous claim unless it is the resolved claim
                              (``detect_github_effective_closing_references``,
                              which masks nothing: code spans, fences, negation)
NONE / mentions only others   unrelated
============================  ====================================================
One pull request has one role per issue: claim, then ambiguous, then declared
non-closing. A repository-qualified reference to a *different* repository is
unrelated.

What this module never does
---------------------------
No GitHub client, write, or credential; no inference from labels, branch names,
issue prose, PR age, search rank, or AI judgment; no new selector, scheduler,
store, lifecycle evaluator, or authority. ``primary_claims`` and
``approval_applicability`` stay with their own (unresolved) owners: this module
supplies a lifecycle stage only, and a stage alone never selects an issue.

Known limits (documented, not hidden)
-------------------------------------
- The evaluator emits ``closed``/``draft-pr``/``review``/``merged`` only; most
  open backlog issues have no verified PR and therefore stay ``unavailable``.
- One population snapshot serves a whole run; a pull request opened after the
  snapshot and before the run ends is not seen. The default-branch SHA and the
  re-read of every relevant pull request bound that window but cannot close it.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Mapping, Protocol

from scripts.agent_os_candidate_packet.stage_models import IssueReadStatus
from scripts.agent_os_candidate_packet_live_input import (
    LiveIssueReader,
    SingleIssueTransport,
)
from scripts.agent_os_github_issue_provider.revision import issue_source_revision

from .github_issue_source import GitHubIssuePageResponse
from .issue_operational_state import MAX_PRIMARY_CLAIMS, IssueState
from .lifecycle_stage_acquisition import (
    ASSOCIATION_POLICIES,
    ASSOCIATION_POLICY_DECLARED_NON_CLOSING_V1,
    LifecycleStageAcquisitionRequest,
    LifecycleStageAcquisitionResult,
    PrLineageEnumeration,
    VerifiedPrLineage,
    acquire_lifecycle_stage,
)
from .models import LinkedIssueParseResult, LinkedIssueParseStatus
from .parse_pr import (
    detect_github_effective_closing_references,
    parse_linked_issue_result,
)

PR_LINEAGE_READER_CONTRACT_VERSION = "1.0"

#: The population is always the all-state listing: a merged or closed pull
#: request is lineage evidence, so an open-only listing would hide it.
POPULATION_STATE = "all"
DEFAULT_PAGE_SIZE = 100
#: Explicit page bound. The repository holds ~1.6k pull requests (17 pages at
#: 100); the bound leaves headroom and is *reported*, never silently hit.
DEFAULT_MAX_PAGES = 40

_MAX_NOTE_CHARS = 480
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

# --- bounded reason vocabulary ------------------------------------------------
REASON_POPULATION_COMPLETE = "pr-lineage.population-complete"
REASON_PAGE_BOUND_EXHAUSTED = "pr-lineage.page-bound-exhausted"
REASON_PAGINATION_UNPROVEN = "pr-lineage.pagination-unproven"
REASON_PAGE_READ_FAILED = "pr-lineage.page-read-failed"
REASON_MALFORMED_PR_RECORD = "pr-lineage.malformed-pr-record"
REASON_CONFLICTING_DUPLICATE = "pr-lineage.conflicting-duplicate-observation"
REASON_POPULATION_SHIFTED = "pr-lineage.population-shifted-during-listing"
REASON_CROSS_REPOSITORY_RECORD = "pr-lineage.cross-repository-record"
REASON_DEFAULT_BRANCH_MOVED = "pr-lineage.default-branch-moved"
REASON_DEFAULT_BRANCH_UNREADABLE = "pr-lineage.default-branch-unreadable"
REASON_DETAIL_READ_FAILED = "pr-lineage.detail-read-failed"
REASON_LIST_DETAIL_DISAGREEMENT = "pr-lineage.list-detail-disagreement"
REASON_CLAIMS_EXCEED_BOUND = "pr-lineage.claims-exceed-bound"
REASON_ISSUE_READ_FAILED = "pr-lineage.issue-read-failed"
REASON_ISSUE_STATE_UNSUPPORTED = "pr-lineage.issue-state-unsupported"
REASON_ISSUE_REVISION_UNAVAILABLE = "pr-lineage.issue-revision-unavailable"
REASON_REPOSITORY_MISMATCH = "pr-lineage.repository-mismatch"
REASON_LINEAGE_NOT_CONSULTED = "pr-lineage.closed-issue-lineage-not-consulted"

ROLE_CLAIM = "claim"
ROLE_AMBIGUOUS = "ambiguous"
ROLE_DECLARED_NON_CLOSING = "declared-non-closing"
#: One role per (issue, pull request): the strongest wins.
_ROLE_PRIORITY = {ROLE_CLAIM: 0, ROLE_AMBIGUOUS: 1, ROLE_DECLARED_NON_CLOSING: 2}


class PullRequestPageReader(Protocol):
    """Read port for one page of the all-state pull-request listing."""

    def read_pull_request_page(
        self,
        repository: str,
        *,
        page: int,
        per_page: int,
        state: str,
    ) -> GitHubIssuePageResponse:
        """Return one normalized page (the container is content agnostic)."""


class PullRequestDetailOutcome(str, Enum):
    OK = "ok"
    NOT_FOUND = "not-found"
    PERMISSION_DENIED = "permission-denied"
    MALFORMED_RESPONSE = "malformed-response"
    API_ERROR = "api-error"


@dataclass(frozen=True, slots=True)
class PullRequestDetailResult:
    outcome: PullRequestDetailOutcome
    item: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if type(self.outcome) is not PullRequestDetailOutcome:
            raise TypeError("outcome must be a PullRequestDetailOutcome")
        if (self.outcome is PullRequestDetailOutcome.OK) != (self.item is not None):
            raise ValueError("an item accompanies exactly the ok outcome")


class PullRequestDetailReader(Protocol):
    """Read port for one exact pull request."""

    def read_pull_request(
        self, repository: str, pull_request_number: int
    ) -> PullRequestDetailResult:
        """Perform one read-only GET of one pull request."""


SourceRevisionReader = Callable[[], str]


# --- normalized pull-request facts ----------------------------------------------
class _PrRecordError(ValueError):
    """A pull-request record that cannot be trusted as evidence."""


@dataclass(frozen=True, slots=True)
class PrFact:
    """The lifecycle-relevant facts of one pull request, text reduced to a digest."""

    number: int
    is_open: bool
    is_draft: bool
    is_merged: bool
    head_sha: str
    branch: str
    base_repository: str
    text_digest: str

    def comparable(self) -> tuple[object, ...]:
        return (
            self.is_open,
            self.is_draft,
            self.is_merged,
            self.head_sha,
            self.base_repository.casefold(),
            self.text_digest,
        )


def _text_digest(title: str, body: str) -> str:
    return hashlib.sha256(f"{title}\0{body}".encode("utf-8")).hexdigest()


def _record_text(
    value: object, name: str, *, allow_empty: bool = False, nullable: bool = False
) -> str:
    if value is None and nullable:
        return ""
    if type(value) is not str:
        raise _PrRecordError(f"{name} must be text")
    if not value and not allow_empty:
        raise _PrRecordError(f"{name} must be non-empty")
    return value


def _pr_mapping_to_fact(raw: object) -> tuple[PrFact, str, str]:
    """Normalize one REST pull-request object; reject anything untrustworthy.

    Returns ``(fact, title, body)``. A closed pull request keeps GitHub's
    ``draft`` flag, so ``is_draft`` is only true while the pull request is
    open (the evaluator requires ``draft`` to imply ``open``).
    """
    if not isinstance(raw, Mapping):
        raise _PrRecordError("pull-request record must be a mapping")
    number = raw.get("number")
    if type(number) is not int or number < 1:
        raise _PrRecordError("number must be a positive integer")
    state = raw.get("state")
    if state not in {"open", "closed"}:
        raise _PrRecordError("state must be open or closed")
    draft = raw.get("draft")
    if type(draft) is not bool:
        raise _PrRecordError("draft must be a boolean")
    merged_at = raw.get("merged_at")
    if merged_at is not None and type(merged_at) is not str:
        raise _PrRecordError("merged_at must be text or null")
    is_merged = merged_at is not None
    merged_flag = raw.get("merged")
    if merged_flag is not None and (type(merged_flag) is not bool or merged_flag != is_merged):
        raise _PrRecordError("merged flag disagrees with merged_at")
    is_open = state == "open"
    if is_merged and is_open:
        raise _PrRecordError("a merged pull request cannot be open")
    head = raw.get("head")
    base = raw.get("base")
    if not isinstance(head, Mapping) or not isinstance(base, Mapping):
        raise _PrRecordError("head and base must be mappings")
    head_sha = head.get("sha")
    if type(head_sha) is not str or not _SHA40_RE.fullmatch(head_sha):
        raise _PrRecordError("head sha must be a lowercase 40-character SHA")
    branch = _record_text(head.get("ref"), "head ref")
    base_repo = base.get("repo")
    if not isinstance(base_repo, Mapping):
        raise _PrRecordError("base repo must be a mapping")
    base_repository = _record_text(base_repo.get("full_name"), "base repo full_name")
    if not _REPOSITORY_RE.fullmatch(base_repository):
        raise _PrRecordError("base repo full_name is malformed")
    title = _record_text(raw.get("title"), "title", allow_empty=True)
    body = _record_text(raw.get("body"), "body", allow_empty=True, nullable=True)
    fact = PrFact(
        number=number,
        is_open=is_open,
        is_draft=draft and is_open,
        is_merged=is_merged,
        head_sha=head_sha,
        branch=branch,
        base_repository=base_repository,
        text_digest=_text_digest(title, body),
    )
    return fact, title, body


# --- population ----------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class PrReference:
    """One pull request's reference to one issue, as classified by ``parse_pr``."""

    issue_number: int
    pull_request_number: int
    role: str


@dataclass(frozen=True, slots=True)
class PrPageObservation:
    """Transport observations of one served page (provenance, never state)."""

    page: int
    item_count: int
    next_page: int | None
    terminal_page_proven: bool
    source_query_string: str | None
    link_next_url: str | None
    rate_limit_remaining: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "page": self.page,
            "item_count": self.item_count,
            "next_page": self.next_page,
            "terminal_page_proven": self.terminal_page_proven,
            "source_query_string": self.source_query_string,
            "link_next_url": self.link_next_url,
            "rate_limit_remaining": self.rate_limit_remaining,
        }


@dataclass(frozen=True, slots=True)
class PrPopulation:
    """The all-state pull-request population and the proof (or failure) of its completeness.

    ``facts`` and ``references`` are empty unless ``complete`` is true: a partial
    listing can never prove the absence of a pull request, so it is not exposed
    as evidence at all.
    """

    repository: str
    observed_at: str
    source_revision: str
    source_query: str
    complete: bool
    reason_codes: tuple[str, ...]
    note: str
    page_observations: tuple[PrPageObservation, ...] = ()
    facts: tuple[PrFact, ...] = ()
    references: tuple[PrReference, ...] = ()
    duplicate_observations: int = 0

    def __post_init__(self) -> None:
        if not self.reason_codes:
            raise ValueError("reason_codes must be non-empty")
        if not self.complete and (self.facts or self.references):
            raise ValueError("an incomplete population exposes no facts")

    def summary(self) -> dict[str, object]:
        return {
            "complete": self.complete,
            "reason_codes": list(self.reason_codes),
            "note": self.note,
            "repository": self.repository,
            "source_query": self.source_query,
            "source_revision": self.source_revision,
            "observed_at": self.observed_at,
            "page_count": len(self.page_observations),
            "pull_request_count": len(self.facts),
            "duplicate_observations": self.duplicate_observations,
            "pages": [observation.to_dict() for observation in self.page_observations],
        }


def _incomplete_population(
    *,
    repository: str,
    observed_at: str,
    source_revision: str,
    source_query: str,
    reason: str,
    detail: str,
    observations: tuple[PrPageObservation, ...],
    duplicates: int = 0,
) -> PrPopulation:
    return PrPopulation(
        repository=repository,
        observed_at=observed_at,
        source_revision=source_revision,
        source_query=source_query,
        complete=False,
        reason_codes=(reason,),
        note=detail[:_MAX_NOTE_CHARS],
        page_observations=observations,
        duplicate_observations=duplicates,
    )


def _classify_references(
    number: int, title: str, body: str, repository: str
) -> list[PrReference]:
    """Classify one pull request's references to issues with the ``parse_pr`` authority.

    ``parse_linked_issue_result`` decides the one claim. Every other
    same-repository issue the pull request names, and every same-repository
    issue GitHub would close on merge, stays visible as an ambiguous reference
    instead of being dropped.
    """
    parsed: LinkedIssueParseResult = parse_linked_issue_result(body, title)
    key = repository.casefold()
    roles: dict[int, str] = {}

    def same_repository(candidate_repository: str | None) -> bool:
        return candidate_repository is None or candidate_repository.casefold() == key

    def record(issue_number: int, role: str) -> None:
        current = roles.get(issue_number)
        if current is None or _ROLE_PRIORITY[role] < _ROLE_PRIORITY[current]:
            roles[issue_number] = role

    mentioned_role = ROLE_AMBIGUOUS
    mentioned = [*parsed.explicit_candidates, *parsed.bare_references]
    if parsed.status is LinkedIssueParseStatus.RESOLVED and parsed.issue_number is not None:
        record(parsed.issue_number, ROLE_CLAIM)
    elif parsed.status is LinkedIssueParseStatus.INFORMATIONAL:
        mentioned_role = ROLE_DECLARED_NON_CLOSING
        mentioned = list(parsed.bare_references)
    for candidate in mentioned:
        if same_repository(candidate.repository):
            record(candidate.issue_number, mentioned_role)
    # GitHub closes on merge whatever parse_pr masks; such a target that is not
    # the claim is a competing lineage reference. "#N" covers this repository
    # (the detector folds the canonical repository into the short form).
    for reference in detect_github_effective_closing_references(body, title):
        target_repository, _, target_number = reference.target.rpartition("#")
        if same_repository(target_repository or None):
            record(int(target_number), ROLE_AMBIGUOUS)
    return [PrReference(issue, number, role) for issue, role in sorted(roles.items())]


def enumerate_pull_request_population(
    repository: str,
    reader: PullRequestPageReader,
    *,
    observed_at: str,
    source_revision: str,
    per_page: int = DEFAULT_PAGE_SIZE,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> PrPopulation:
    """Enumerate the all-state population and prove (or disprove) completeness.

    The returned population is ``complete`` only on positive terminal proof
    within ``max_pages``; every other outcome is an incomplete population
    carrying the named reason. No exception from the injected reader escapes.
    """
    if type(repository) is not str or not _REPOSITORY_RE.fullmatch(repository):
        raise ValueError("repository must use owner/name form")
    if type(observed_at) is not str or not _TIMESTAMP_RE.fullmatch(observed_at):
        raise ValueError("observed_at must use YYYY-MM-DDTHH:MM:SSZ")
    if type(source_revision) is not str or not _SHA40_RE.fullmatch(source_revision):
        raise ValueError("source_revision must be a lowercase 40-character SHA")
    if type(per_page) is not int or not 1 <= per_page <= 100:
        raise ValueError("per_page must be an integer from 1 to 100")
    if type(max_pages) is not int or max_pages < 1:
        raise ValueError("max_pages must be a positive integer")

    source_query = f"repo={repository} pulls state={POPULATION_STATE} per_page={per_page}"
    observations: list[PrPageObservation] = []
    facts: dict[int, PrFact] = {}
    references: list[PrReference] = []
    duplicates = 0
    page = 1

    def incomplete(reason: str, detail: str) -> PrPopulation:
        return _incomplete_population(
            repository=repository,
            observed_at=observed_at,
            source_revision=source_revision,
            source_query=source_query,
            reason=reason,
            detail=detail,
            observations=tuple(observations),
            duplicates=duplicates,
        )

    while True:
        try:
            response = reader.read_pull_request_page(
                repository, page=page, per_page=per_page, state=POPULATION_STATE
            )
        except PermissionError:
            return incomplete(REASON_PAGE_READ_FAILED, f"page {page}: permission-denied")
        except LookupError:
            return incomplete(REASON_PAGE_READ_FAILED, f"page {page}: source-inaccessible")
        except RuntimeError:
            return incomplete(REASON_PAGE_READ_FAILED, f"page {page}: api-error")
        except (TypeError, ValueError) as error:
            return incomplete(
                REASON_PAGE_READ_FAILED, f"page {page}: malformed-response ({error})"
            )
        if type(response) is not GitHubIssuePageResponse:
            return incomplete(REASON_PAGE_READ_FAILED, f"page {page}: malformed-response")
        observations.append(
            PrPageObservation(
                page=page,
                item_count=len(response.items),
                next_page=response.next_page,
                terminal_page_proven=response.terminal_page_proven,
                source_query_string=response.source_query_string,
                link_next_url=response.link_next_url,
                rate_limit_remaining=response.rate_limit_remaining,
            )
        )
        if response.error_kind is not None:
            return incomplete(
                REASON_PAGE_READ_FAILED, f"page {page}: {response.error_kind}"
            )
        if not response.complete:
            return incomplete(REASON_PAGINATION_UNPROVEN, f"page {page}: completeness unknown")

        for raw in response.items:
            try:
                fact, title, body = _pr_mapping_to_fact(raw)
            except _PrRecordError as error:
                return incomplete(REASON_MALFORMED_PR_RECORD, f"page {page}: {error}")
            if fact.base_repository.casefold() != repository.casefold():
                return incomplete(
                    REASON_CROSS_REPOSITORY_RECORD,
                    f"page {page}: pull request #{fact.number} belongs to "
                    f"{fact.base_repository}",
                )
            earlier = facts.get(fact.number)
            if earlier is not None:
                duplicates += 1
                if earlier.comparable() != fact.comparable():
                    return incomplete(
                        REASON_CONFLICTING_DUPLICATE,
                        f"page {page}: pull request #{fact.number} changed while listing",
                    )
                # Even an identical repeat proves a pull request was opened
                # mid-listing and shifted this one onto the next page: the new
                # one was never observed, so the population is not complete.
                return incomplete(
                    REASON_POPULATION_SHIFTED,
                    f"page {page}: pull request #{fact.number} listed twice; "
                    "the population shifted while listing",
                )
            facts[fact.number] = fact
            try:
                references.extend(_classify_references(fact.number, title, body, repository))
            except ValueError as error:
                return incomplete(
                    REASON_MALFORMED_PR_RECORD,
                    f"page {page}: pull request #{fact.number} references unreadable ({error})",
                )

        if response.next_page is None:
            if not response.terminal_page_proven:
                return incomplete(
                    REASON_PAGINATION_UNPROVEN,
                    f"page {page}: no next page and no terminal proof",
                )
            break
        if (
            type(response.next_page) is not int
            or response.next_page != page + 1
        ):
            return incomplete(
                REASON_PAGINATION_UNPROVEN,
                f"page {page}: next_page={response.next_page!r} is not the contiguous successor",
            )
        if page >= max_pages:
            return incomplete(
                REASON_PAGE_BOUND_EXHAUSTED,
                f"page bound of {max_pages} exhausted before terminal pagination proof",
            )
        page += 1

    ordered = tuple(sorted(facts.values(), key=lambda item: item.number))
    note = (
        f"all-state PR population proven complete: pages={len(observations)} "
        f"pull_requests={len(ordered)} terminal_page_proven=true "
        f"default_branch={source_revision[:12]} observed_at={observed_at}"
    )
    return PrPopulation(
        repository=repository,
        observed_at=observed_at,
        source_revision=source_revision,
        source_query=source_query,
        complete=True,
        reason_codes=(REASON_POPULATION_COMPLETE,),
        note=note[:_MAX_NOTE_CHARS],
        page_observations=tuple(observations),
        facts=ordered,
        references=tuple(
            sorted(references, key=lambda item: (item.issue_number, item.pull_request_number))
        ),
        duplicate_observations=duplicates,
    )


# --- acquirer ------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class LifecycleStageAcquisitionAttempt:
    """One acquirer attempt: an evaluator result, or the reason none could be built.

    ``evidence`` is the JSON-ready record of what was observed for the issue.
    It is projection only and carries no authority.
    """

    result: LifecycleStageAcquisitionResult | None
    failure_reason: str | None = None
    failure_detail: str | None = None
    evidence: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if (self.result is None) == (self.failure_reason is None):
            raise ValueError("attempt must carry a result or a failure reason, not both")
        if self.result is not None and type(self.result) is not LifecycleStageAcquisitionResult:
            raise TypeError("result must be an exact LifecycleStageAcquisitionResult")

    @property
    def reason_codes(self) -> tuple[str, ...]:
        if self.result is not None:
            return self.result.reason_codes
        assert self.failure_reason is not None
        return (self.failure_reason,)


class LifecycleStageAcquirer(Protocol):
    """Per-issue lifecycle source consumed by ``LiveCandidateEvidenceReader``."""

    def acquire_lifecycle_stage(
        self, repository: str, issue_number: int
    ) -> LifecycleStageAcquisitionAttempt:
        """Return the evaluator result for one issue, or a named failure."""


@dataclass(slots=True)
class PrLineageAcquirer:
    """Per-run lifecycle-stage source over live (injected) read ports.

    The population is enumerated lazily on the first open candidate and reused
    for the whole run, so reads scale with the repository, not with candidates.
    Nothing here writes, authorizes, selects, or persists.
    """

    repository: str
    issue_transport: SingleIssueTransport
    page_reader: PullRequestPageReader
    detail_reader: PullRequestDetailReader
    source_revision_reader: SourceRevisionReader
    observed_at: str
    per_page: int = DEFAULT_PAGE_SIZE
    max_pages: int = DEFAULT_MAX_PAGES
    # Required and keyword-only (#3690 CR-4): the composing caller (the
    # shadow-run CLI) owns the policy choice; there is no library default.
    association_policy: str = field(kw_only=True)
    _population: PrPopulation | None = field(default=None, init=False, repr=False)
    _index: dict[int, list[PrReference]] | None = field(default=None, init=False, repr=False)
    _observations: list[dict[str, object]] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        if type(self.repository) is not str or not _REPOSITORY_RE.fullmatch(self.repository):
            raise ValueError("repository must use owner/name form")
        if type(self.observed_at) is not str or not _TIMESTAMP_RE.fullmatch(self.observed_at):
            raise ValueError("observed_at must use YYYY-MM-DDTHH:MM:SSZ")
        for name in ("issue_transport", "page_reader", "detail_reader"):
            if getattr(self, name) is None:
                raise TypeError(f"{name} is required")
        if not callable(self.source_revision_reader):
            raise TypeError("source_revision_reader must be callable")
        if type(self.per_page) is not int or not 1 <= self.per_page <= 100:
            raise ValueError("per_page must be an integer from 1 to 100")
        if type(self.max_pages) is not int or self.max_pages < 1:
            raise ValueError("max_pages must be a positive integer")
        if type(self.association_policy) is not str or self.association_policy not in ASSOCIATION_POLICIES:
            raise ValueError("association_policy must be a supported exact policy")

    # -- observability ---------------------------------------------------------
    @property
    def observations(self) -> tuple[Mapping[str, object], ...]:
        return tuple(self._observations)

    @property
    def population_summary(self) -> Mapping[str, object] | None:
        return None if self._population is None else self._population.summary()

    # -- port ------------------------------------------------------------------
    def acquire_lifecycle_stage(
        self, repository: str, issue_number: int
    ) -> LifecycleStageAcquisitionAttempt:
        attempt = self._acquire(repository, issue_number)
        self._observations.append(self._observation(issue_number, attempt))
        return attempt

    # -- internals -------------------------------------------------------------
    def _failure(
        self, reason: str, detail: str, evidence: Mapping[str, object] | None = None
    ) -> LifecycleStageAcquisitionAttempt:
        return LifecycleStageAcquisitionAttempt(
            result=None, failure_reason=reason, failure_detail=detail, evidence=evidence
        )

    def _acquire(self, repository: str, issue_number: int) -> LifecycleStageAcquisitionAttempt:
        if type(repository) is not str or repository.casefold() != self.repository.casefold():
            return self._failure(REASON_REPOSITORY_MISMATCH, "repository differs from the reader")
        if type(issue_number) is not int or issue_number < 1:
            raise TypeError("issue_number must be a positive built-in integer")

        # 1. The exact issue: structured state plus content-addressed revision.
        read = LiveIssueReader(transport=self.issue_transport).read_issue(
            repository, issue_number
        )
        if read.status is not IssueReadStatus.OK or read.item is None:
            return self._failure(
                REASON_ISSUE_READ_FAILED, f"issue read status {read.status.value}"
            )
        raw_state = read.item.get("state")
        if raw_state == "open":
            issue_state = IssueState.OPEN
        elif raw_state == "closed":
            issue_state = IssueState.CLOSED
        else:
            return self._failure(REASON_ISSUE_STATE_UNSUPPORTED, "issue state is not open/closed")
        try:
            issue_revision = issue_source_revision(read.item)
        except ValueError as error:
            return self._failure(REASON_ISSUE_REVISION_UNAVAILABLE, str(error))

        # 2. The current default-branch SHA, read at acquisition time.
        try:
            current_revision = self.source_revision_reader()
        except RuntimeError as error:
            return self._failure(REASON_DEFAULT_BRANCH_UNREADABLE, str(error))
        if type(current_revision) is not str or not _SHA40_RE.fullmatch(current_revision):
            return self._failure(
                REASON_DEFAULT_BRANCH_UNREADABLE, "default-branch SHA is malformed"
            )

        def finish(
            lineage: tuple[VerifiedPrLineage, ...],
            enumeration: PrLineageEnumeration,
            evidence: Mapping[str, object],
        ) -> LifecycleStageAcquisitionAttempt:
            """Hand the unchanged evaluator its input and keep the enumeration proof visible."""
            result = acquire_lifecycle_stage(
                LifecycleStageAcquisitionRequest(
                    repository=self.repository,
                    issue_number=issue_number,
                    issue_state=issue_state,
                    issue_source_revision=issue_revision,
                    source_revision=current_revision,
                    observed_at=self.observed_at,
                    pr_lineage=lineage,
                    lineage_enumeration=enumeration,
                    association_policy=self.association_policy,
                )
            )
            return LifecycleStageAcquisitionAttempt(
                result=result,
                evidence={
                    **evidence,
                    "enumeration_complete": enumeration.complete,
                    "enumeration_note": enumeration.enumeration_note,
                },
            )

        # 3. A closed issue's stage is GitHub's own state; lineage is not consulted.
        if issue_state is IssueState.CLOSED:
            return finish(
                (),
                PrLineageEnumeration(False, REASON_LINEAGE_NOT_CONSULTED),
                {"lineage_consulted": False},
            )

        # 4. The population, enumerated once and bound to the default branch.
        population = self._ensure_population(current_revision)
        if population.complete and population.source_revision != current_revision:
            enumeration = PrLineageEnumeration(
                False,
                (
                    f"{REASON_DEFAULT_BRANCH_MOVED}: population read at "
                    f"{population.source_revision[:12]}, default branch is now "
                    f"{current_revision[:12]}"
                ),
            )
            return finish(
                (),
                enumeration,
                {"lineage_consulted": True, "stale_reason": REASON_DEFAULT_BRANCH_MOVED},
            )
        if not population.complete:
            enumeration = PrLineageEnumeration(
                False, f"{population.reason_codes[0]}: {population.note}"[:_MAX_NOTE_CHARS]
            )
            return finish((), enumeration, {"lineage_consulted": True})

        # 5. Classify, then re-read every pull request that could claim the issue.
        references = (self._index or {}).get(issue_number, [])
        claims = sorted({r.pull_request_number for r in references if r.role == ROLE_CLAIM})
        ambiguous = sorted(
            {r.pull_request_number for r in references if r.role == ROLE_AMBIGUOUS}
            - set(claims)
        )
        non_closing = sorted(
            {r.pull_request_number for r in references if r.role == ROLE_DECLARED_NON_CLOSING}
            - set(claims)
            - set(ambiguous)
        )
        classification = {
            "lineage_consulted": True,
            "claims": claims,
            "ambiguous_references": ambiguous,
            "declared_non_closing_references": non_closing,
        }
        relevant = sorted(
            {*claims, *ambiguous, *(
                non_closing
                if self.association_policy == ASSOCIATION_POLICY_DECLARED_NON_CLOSING_V1
                else ()
            )}
        )
        if self.association_policy == ASSOCIATION_POLICY_DECLARED_NON_CLOSING_V1:
            classification["association_policy"] = self.association_policy
        if len(relevant) > MAX_PRIMARY_CLAIMS:
            enumeration = PrLineageEnumeration(
                False,
                f"{REASON_CLAIMS_EXCEED_BOUND}: {len(relevant)} pull requests reference "
                f"issue #{issue_number}; the evaluator accepts at most {MAX_PRIMARY_CLAIMS}",
            )
            return finish((), enumeration, classification)
        facts = {fact.number: fact for fact in population.facts}
        lineage: list[VerifiedPrLineage] = []
        for number in relevant:
            verified = self._reread(facts[number])
            if isinstance(verified, str):
                enumeration = PrLineageEnumeration(False, verified[:_MAX_NOTE_CHARS])
                return finish((), enumeration, classification)
            lineage.append(verified)

        return finish(tuple(lineage), PrLineageEnumeration(True, population.note), classification)

    def _ensure_population(self, current_revision: str) -> PrPopulation:
        if self._population is None:
            population = enumerate_pull_request_population(
                self.repository,
                self.page_reader,
                observed_at=self.observed_at,
                source_revision=current_revision,
                per_page=self.per_page,
                max_pages=self.max_pages,
            )
            if population.complete:
                # The listing took time: the default branch must not have moved
                # while it was read, or merged/closed states may be mixed.
                try:
                    after = self.source_revision_reader()
                except RuntimeError:
                    after = ""
                if after != current_revision:
                    population = _incomplete_population(
                        repository=self.repository,
                        observed_at=self.observed_at,
                        source_revision=current_revision,
                        source_query=population.source_query,
                        reason=REASON_DEFAULT_BRANCH_MOVED,
                        detail=(
                            "default branch changed while the population was read "
                            f"({current_revision[:12]} -> {after[:12] or 'unreadable'})"
                        ),
                        observations=population.page_observations,
                        duplicates=population.duplicate_observations,
                    )
            self._population = population
            index: dict[int, list[PrReference]] = {}
            for reference in population.references:
                index.setdefault(reference.issue_number, []).append(reference)
            self._index = index
        return self._population

    def _reread(self, listed: PrFact) -> VerifiedPrLineage | str:
        """Re-read one pull request; a verified lineage entry, or the incompleteness note."""
        detail = self.detail_reader.read_pull_request(self.repository, listed.number)
        if type(detail) is not PullRequestDetailResult:
            return f"{REASON_DETAIL_READ_FAILED}: #{listed.number} malformed reader result"
        if detail.outcome is not PullRequestDetailOutcome.OK or detail.item is None:
            return (
                f"{REASON_DETAIL_READ_FAILED}: #{listed.number} {detail.outcome.value}"
            )
        try:
            fact, title, body = _pr_mapping_to_fact(detail.item)
        except _PrRecordError as error:
            return f"{REASON_MALFORMED_PR_RECORD}: #{listed.number} detail: {error}"
        if fact.number != listed.number or fact.comparable() != listed.comparable():
            return (
                f"{REASON_LIST_DETAIL_DISAGREEMENT}: #{listed.number} changed between the "
                "listing and the exact read"
            )
        try:
            return VerifiedPrLineage(
                pull_request_number=fact.number,
                repository=fact.base_repository,
                is_open=fact.is_open,
                is_draft=fact.is_draft,
                is_merged=fact.is_merged,
                head_sha=fact.head_sha,
                branch=fact.branch,
                pr_title=title,
                pr_body=body,
                observed_at=self.observed_at,
            )
        except (TypeError, ValueError) as error:
            return f"{REASON_MALFORMED_PR_RECORD}: #{listed.number} {error}"

    def _observation(
        self, issue_number: int, attempt: LifecycleStageAcquisitionAttempt
    ) -> dict[str, object]:
        record: dict[str, object] = {
            "issue_number": issue_number,
            "contract_version": PR_LINEAGE_READER_CONTRACT_VERSION,
            "reason_codes": list(attempt.reason_codes),
        }
        if attempt.result is not None:
            result = attempt.result
            record.update(
                {
                    "outcome": result.outcome.value,
                    "lifecycle_stage": (
                        None if result.lifecycle_stage is None else result.lifecycle_stage.value
                    ),
                    "verified_claims": list(result.verified_claims),
                    "issue_source_revision": result.issue_source_revision,
                    "source_revision": result.source_revision,
                    "result_id": result.result_id,
                }
            )
        else:
            record["outcome"] = "not-acquired"
            record["failure_detail"] = attempt.failure_detail
        if attempt.evidence is not None:
            record["lineage"] = dict(attempt.evidence)
        if self.association_policy == ASSOCIATION_POLICY_DECLARED_NON_CLOSING_V1:
            record["association_policy"] = self.association_policy
        return record


__all__ = [
    "DEFAULT_MAX_PAGES",
    "DEFAULT_PAGE_SIZE",
    "LifecycleStageAcquirer",
    "LifecycleStageAcquisitionAttempt",
    "PR_LINEAGE_READER_CONTRACT_VERSION",
    "PrFact",
    "PrLineageAcquirer",
    "PrPageObservation",
    "PrPopulation",
    "PrReference",
    "PullRequestDetailOutcome",
    "PullRequestDetailReader",
    "PullRequestDetailResult",
    "PullRequestPageReader",
    "enumerate_pull_request_population",
]
