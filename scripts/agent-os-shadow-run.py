#!/usr/bin/env python3
"""Phase-0 shadow-run CLI: the first production caller of ``select_shadow_issue``.

Read-only. Performs a live paginated open-issue scan against the GitHub REST
API, applies the deterministic narrowing contract, invokes the shadow selector
seam (``08_Tooling/agent-os-execution-service/.../shadow_issue_selection.py``),
and emits the shadow experiment record as JSON.

It performs no GitHub mutation, authorizes no execution, and manufactures no
operational state.

Phase-0 evidence boundary (#3329 Wire-or-Retire): the production
``LiveCandidateEvidenceReader``
(``scripts/agent_os_issue_acceptance/live_candidate_evidence_reader.py``)
is now wired at the composition point below. It composes the canonical
evidence the shadow-run context can legitimately supply:
- the live issue snapshot read plus the #1464 dependency/validation adapters;
- the repository HEAD SHA read live from the GitHub API (the canonical
  current-revision source; the API equivalent of the caller's checkout SHA);
- ``FreshnessState.CURRENT`` -- this composition performs the live read
  itself, so the evidence is current as of the read (the
  ``live_route_context.py`` precedent for live-verified evidence);
- an honest read-only environment self-description (UNPROBED local
  execution, UNSUPPORTED push -- this CLI never mutates);
- explicit request-supplied context (``--requested-mode``,
  ``--dependency-depth``, ``--substitutable``/``--no-substitutable``),
  absent stays absent, never defaulted.

#3441: ``lifecycle_stage`` is now acquired per candidate from live PR lineage.
``PrLineageAcquirer`` (``scripts/agent_os_issue_acceptance/pr_lineage_reader.py``)
enumerates the all-state pull-request population over this CLI's GET-only
client, proves it complete itself, classifies each pull request with the
existing ``parse_pr`` authority, and feeds the unchanged #3433 evaluator. The
evidence reader's consumer-boundary re-check (``acquisition_bindings_current``)
runs only when it composes, which this CLI never reaches: with
``primary_claims`` unresolved it fails closed first, and the record says so
(``consumer_boundary_revalidation: not-reached``). A stage exists only where exactly one verified closing claim
(or GitHub's own closed state) establishes it; everything else stays
``unavailable`` / ``manual-review`` and fails closed.
It still fails closed with a named ``candidate-evidence.*`` reason wherever
no canonical live owner exists: ``primary_claims`` (no canonical claim owner;
#1460 forbids inventing one) and ``approval_applicability`` (the approval
evidence graph is not reconstructible for arbitrary backlog issues) remain
``None`` here -- surfaced, not manufactured -- and a lifecycle stage alone
never selects an issue. The seam therefore still fail-closes with
``candidate-evidence-incomplete`` for the real backlog, and the experiment
record names the exact missing owner and carries the per-candidate lifecycle
acquisition evidence under ``lifecycle_stage_acquisition``.
#3328: ``--request-interpretation`` supplies the canonical
request-interpretation-v1 record from which the existing cohort admission
(``cohort_admission.py``) derives the bounded candidate cohort, or fails
closed, before any candidate evidence is read; manual ``--candidates`` stays
a diagnostic/experiment input and cannot be combined with it. Feeding a
``SELECTED`` result into the governed issue-start path is #3082 (Phase 1+);
this CLI is the producer side of that future connection.

Runtime: run inside the isolated execution-service runtime (``mcp``,
``PyGithub``, ``pyyaml``, plus the sibling ``workflow-scheduler``,
``agent-memory-context-manager`` and ``instructional-workflow-contracts``
distributions), e.g. the venv described in ``SHADOW_ISSUE_SELECTION.md``.
Network access is read-only: only HTTP GET is ever issued. ``GITHUB_TOKEN``,
when set, is used as a bearer token to raise the API rate limit; it is never
logged or written anywhere.

Phase 1 B5: the CLI records per-page scan provenance (exact query string,
observed Link next URL, rate-limit remainder, scan start/end timestamps) on
the selection result, and emits one finite-mission evidence-ledger entry for
its selection decision into the experiment record's ``evidence_ledger``
section. The ledger mission_id comes from ``--mission-id`` when supplied;
otherwise it is derived deterministically as
``shadow-run:{campaign_id}:{retrieved_at}`` (documented in
``_resolve_mission_id``).
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Mapping

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _entry in (
    str(_REPO_ROOT / "08_Tooling" / "agent-os-execution-service" / "src"),
    str(_REPO_ROOT / "08_Tooling" / "workflow-scheduler" / "src"),
    str(_REPO_ROOT),
):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from agent_os_execution_service.shadow_issue_selection import (  # noqa: E402
    ScanPageProvenance,
    ScanProvenanceLog,
    ShadowIssueSelectionResult,
    ShadowSelectionStatus,
    select_shadow_issue,
)
from instructional_workflow_contracts.request_interpretation import (  # noqa: E402
    RequestInterpretation,
    validate_request_interpretation,
)
from instructional_workflow_contracts.common import ValidationStatus  # noqa: E402
from agent_os_execution_service.evidence_ledger import (  # noqa: E402
    EvidenceLedger,
    NavigationDecisionType,
    hash_decision_inputs,
)
from scripts.agent_os_github_issue_provider.models import (  # noqa: E402
    TrustedRepositoryIdentity,
)
from scripts.agent_os_github_issue_provider.pagination import (  # noqa: E402
    PaginationDiagnosticError,
    parse_link_header,
    validated_next_page,
)
from scripts.agent_os_issue_acceptance.github_issue_source import (  # noqa: E402
    GitHubIssuePageResponse,
)
from scripts.agent_os_issue_acceptance.pr_lineage_reader import (  # noqa: E402
    PR_LINEAGE_READER_CONTRACT_VERSION,
    PrLineageAcquirer,
    PullRequestDetailOutcome,
    PullRequestDetailResult,
)
from scripts.agent_os_issue_acceptance.lifecycle_stage_acquisition import (  # noqa: E402
    ASSOCIATION_POLICIES,
    ASSOCIATION_POLICY_DECLARED_NON_CLOSING_V1,
)
from scripts.agent_os_issue_acceptance.issue_scanner import IssueStateFilter  # noqa: E402
from scripts.agent_os_issue_acceptance.live_candidate_evidence_reader import (  # noqa: E402
    LiveCandidateEvidence,
    LiveCandidateEvidenceReader,
)
from scripts.agent_os_issue_acceptance.issue_operational_state import (  # noqa: E402
    FreshnessState,
)
from scripts.agent_os_issue_acceptance.operating_mode import (  # noqa: E402
    EnvironmentCapabilityEvidence,
    EnvironmentCapabilityState,
    RequestedMode,
)
from scripts.agent_os_candidate_packet_live_input import (  # noqa: E402
    SingleIssueTransportOutcome,
    SingleIssueTransportResult,
)

_API = "https://api.github.com"
_LINK_NEXT_RE = re.compile(r'<([^>]+)>;\s*rel="next"')
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

# Fallback evidence-gap text, used only when the production reader records no
# specific named reason. With #3329 wired, the reader names the exact missing
# canonical owner per candidate instead of this generic gap.
EVIDENCE_GAP = (
    "no canonical candidate-evidence inputs available in this shadow-run "
    "context: primary claims and approval applicability have no canonical "
    "live owners for arbitrary backlog issues (#1460 forbids inventing "
    "PR-linkage claim authority inside a reader), and a lifecycle stage is "
    "acquired only where exactly one verified PR claim establishes it"
)


class GitHubReadClient:
    """Read-only GitHub REST client. Only HTTP GET exists on this class."""

    def __init__(self) -> None:
        self.get_requests = 0
        self.write_requests = 0
        token = os.environ.get("GITHUB_TOKEN")
        self._headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "agent-os-shadow-run/phase0",
        }
        if token:
            self._headers["Authorization"] = f"Bearer {token}"

    def get(self, path: str) -> tuple[int, Mapping[str, str], bytes]:
        self.get_requests += 1
        request = urllib.request.Request(
            _API + path, headers=self._headers, method="GET"
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                headers = {k.lower(): v for k, v in response.headers.items()}
                return response.status, headers, response.read()
        except urllib.error.HTTPError as exc:
            headers = {k.lower(): v for k, v in (exc.headers.items() if exc.headers else [])}
            return exc.code, headers, exc.read() if hasattr(exc, "read") else b""
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"github api unreachable: {exc}") from exc


def _read_repository(
    client: GitHubReadClient, repository: str
) -> tuple[int | None, str]:
    """Read ``(repository id, default branch)``; the id is ``None`` when absent."""
    status, _, body = client.get(f"/repos/{repository}")
    if status != 200:
        raise RuntimeError(
            f"github api: repository read failed for {repository} (http {status})"
        )
    try:
        payload = json.loads(body)
        default_branch = payload["default_branch"]
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(
            f"github api: repository payload malformed for {repository}"
        ) from exc
    if not isinstance(default_branch, str) or not default_branch:
        raise RuntimeError(
            f"github api: default branch missing for {repository}"
        )
    repository_id = payload.get("id") if isinstance(payload, dict) else None
    if type(repository_id) is not int or repository_id < 1:
        repository_id = None
    return repository_id, default_branch


def _fetch_repository_head_sha(client: GitHubReadClient, repository: str) -> str:
    """Fetch the repository's default-branch HEAD SHA via the GitHub API.

    This is the canonical live "current repository SHA" for the shadow
    experiment: the revision the candidate evidence is evaluated against.
    It is GitHub's own ref data, not inference -- the API-based equivalent
    of the "current checkout SHA" the snapshot reader's contract expects
    the caller to know.

    Fail-closed: raises RuntimeError when the ref cannot be read or the
    payload is malformed, which the CLI reports as a transport failure.
    """
    _, default_branch = _read_repository(client, repository)
    return _fetch_branch_head_sha(client, repository, default_branch)


def _fetch_branch_head_sha(
    client: GitHubReadClient, repository: str, default_branch: str
) -> str:
    """Fetch one branch's HEAD SHA (the second half of the head read)."""
    status, _, body = client.get(
        f"/repos/{repository}/branches/{default_branch}"
    )
    if status != 200:
        raise RuntimeError(
            f"github api: branch read failed for {repository}@{default_branch} "
            f"(http {status})"
        )
    try:
        sha = json.loads(body)["commit"]["sha"]
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(
            f"github api: branch payload malformed for "
            f"{repository}@{default_branch}"
        ) from exc
    if not isinstance(sha, str) or len(sha) != 40 or any(
        c not in "0123456789abcdef" for c in sha
    ):
        raise RuntimeError(
            f"github api: branch sha malformed for {repository}@{default_branch}"
        )
    return sha


# Honest environment capability for the read-only shadow context. This CLI
# performs no execution and no GitHub mutation by design (see module
# docstring); UNPROBED/UNSUPPORTED are truthful self-descriptions that can
# authorize nothing, not probe results.
def _shadow_environment_capability() -> EnvironmentCapabilityEvidence:
    return EnvironmentCapabilityEvidence(
        local_execution_state=EnvironmentCapabilityState.UNPROBED,
        push_state=EnvironmentCapabilityState.UNSUPPORTED,
    )


class LivePageReader:
    """GitHubIssuePageReader over the live issues endpoint (GET only).

    Phase 1 B5: records per-page scan provenance -- the exact query string,
    the observed ``Link`` next URL, the observed rate-limit remainder, and
    scan start/end timestamps -- into the caller-shared ScanProvenanceLog, so
    the scan that produced a population is reconstructible from the reader's
    observations alone. Provenance is recorded for every returned page
    response, including rate-limited error responses; pages that raise
    (404/denied/transport failure) abort the scan and carry their own
    exception signal.
    """

    def __init__(
        self, client: GitHubReadClient, provenance_log: ScanProvenanceLog | None = None
    ) -> None:
        self._client = client
        self._provenance_log = provenance_log

    def read_issue_page(
        self, repository: str, *, page: int, per_page: int, state: str
    ) -> GitHubIssuePageResponse:
        query_string = f"state={state}&per_page={per_page}&page={page}"
        now = _datetime.datetime.now(_datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        status, headers, body = self._client.get(
            f"/repos/{repository}/issues?{query_string}"
        )
        rate_limit_remaining = headers.get("x-ratelimit-remaining")
        link_next_url: str | None = None
        link_match = _LINK_NEXT_RE.search(headers.get("link", ""))
        if link_match:
            link_next_url = link_match.group(1)

        def _respond(
            *,
            items: tuple = (),
            next_page: int | None = None,
            complete: bool = True,
            terminal_page_proven: bool = False,
            error_kind: str | None = None,
        ) -> GitHubIssuePageResponse:
            response = GitHubIssuePageResponse(
                items=items,
                next_page=next_page,
                complete=complete,
                terminal_page_proven=terminal_page_proven,
                error_kind=error_kind,
                page=page,
                source_query_string=query_string,
                link_next_url=link_next_url,
                rate_limit_remaining=rate_limit_remaining,
            )
            if self._provenance_log is not None:
                self._provenance_log.note_page(
                    ScanPageProvenance(
                        page=page,
                        item_count=len(response.items),
                        next_page=response.next_page,
                        source_query_string=query_string,
                        link_next_url=link_next_url,
                        rate_limit_remaining=rate_limit_remaining,
                        terminal_page_proven=response.terminal_page_proven,
                        error_kind=error_kind,
                    ),
                    at=now,
                )
            return response

        if status == 403 and headers.get("x-ratelimit-remaining") == "0":
            return _respond(error_kind="rate-limited", complete=False)
        if status == 404:
            raise LookupError(f"repository not found: {repository}")
        if status in (401, 403):
            raise PermissionError(f"github api denied page {page}: http {status}")
        if status != 200:
            raise RuntimeError(f"github api page {page} failed: http {status}")
        try:
            items = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError(f"github api page {page} returned malformed json") from exc
        if not isinstance(items, list):
            raise ValueError(f"github api page {page} returned a non-list payload")
        has_next = link_next_url is not None
        return _respond(
            items=tuple(items),
            next_page=(page + 1) if has_next else None,
            complete=True,
            terminal_page_proven=not has_next,
        )


class LiveIssueTransport:
    """SingleIssueTransport over the live issue endpoint (GET only)."""

    def __init__(self, client: GitHubReadClient) -> None:
        self._client = client

    def get_issue(self, repository: str, issue_number: int) -> SingleIssueTransportResult:
        try:
            status, _, body = self._client.get(f"/repos/{repository}/issues/{issue_number}")
        except RuntimeError:
            return SingleIssueTransportResult(outcome=SingleIssueTransportOutcome.API_ERROR)
        if status == 404:
            return SingleIssueTransportResult(outcome=SingleIssueTransportOutcome.NOT_FOUND)
        if status in (401, 403):
            return SingleIssueTransportResult(
                outcome=SingleIssueTransportOutcome.PERMISSION_DENIED
            )
        if status != 200:
            return SingleIssueTransportResult(outcome=SingleIssueTransportOutcome.API_ERROR)
        try:
            item = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return SingleIssueTransportResult(
                outcome=SingleIssueTransportOutcome.MALFORMED_RESPONSE
            )
        if not isinstance(item, dict):
            return SingleIssueTransportResult(
                outcome=SingleIssueTransportOutcome.MALFORMED_RESPONSE
            )
        return SingleIssueTransportResult(outcome=SingleIssueTransportOutcome.OK, item=item)


class _RepositoryHeadReader:
    """Default-branch SHA and repository identity over the shared GET-only client.

    The repository payload (numeric id, default branch name) is read once per
    run; each later head read is a single branch GET. The numeric id is what
    lets the canonical continuation validator accept GitHub's
    ``/repositories/{id}/...`` next links without trusting an unverified path.
    """

    def __init__(self, client: GitHubReadClient, repository: str) -> None:
        self._client = client
        self._repository = repository
        self._identity: tuple[int | None, str] | None = None

    def _repository_payload(self) -> tuple[int | None, str]:
        if self._identity is None:
            self._identity = _read_repository(self._client, self._repository)
        return self._identity

    def head_sha(self) -> str:
        _, default_branch = self._repository_payload()
        return _fetch_branch_head_sha(self._client, self._repository, default_branch)

    def trusted_identity(self) -> TrustedRepositoryIdentity | None:
        repository_id, _ = self._repository_payload()
        if repository_id is None:
            return None
        return TrustedRepositoryIdentity(
            repository=self._repository, repository_id=repository_id
        )


class LivePullRequestPageReader:
    """PullRequestPageReader over the live pulls endpoint (GET only).

    Continuation and terminal proof come from the provider's canonical
    ``validated_next_page`` (``pulls`` endpoint) -- contiguous successor,
    unchanged page size and state, pinned host and repository path -- not from
    a local regex. A diagnostic from that validator is a malformed response:
    the enumeration then fails closed instead of guessing a next page.

    One stricter rule is local to this reader: a page with no ``next`` whose
    ``last`` relation names any other page contradicts itself, so it is never
    accepted as terminal proof (the shared validator's issues contract, which
    pins that case as terminal, is unchanged).
    """

    def __init__(
        self,
        client: GitHubReadClient,
        trusted_identity=lambda: None,
    ) -> None:
        self._client = client
        self._trusted_identity = trusted_identity

    def read_pull_request_page(
        self, repository: str, *, page: int, per_page: int, state: str
    ) -> GitHubIssuePageResponse:
        query_string = f"state={state}&per_page={per_page}&page={page}"
        status, headers, body = self._client.get(
            f"/repos/{repository}/pulls?{query_string}"
        )
        rate_limit_remaining = headers.get("x-ratelimit-remaining")
        link_header = headers.get("link")
        link_match = _LINK_NEXT_RE.search(link_header or "")
        link_next_url = link_match.group(1) if link_match else None

        def _respond(**kwargs) -> GitHubIssuePageResponse:
            return GitHubIssuePageResponse(
                page=page,
                source_query_string=query_string,
                link_next_url=link_next_url,
                rate_limit_remaining=rate_limit_remaining,
                **kwargs,
            )

        if status == 403 and rate_limit_remaining == "0":
            return _respond(
                items=(), next_page=None, complete=False, error_kind="rate-limited"
            )
        if status == 404:
            raise LookupError(f"repository not found: {repository}")
        if status in (401, 403):
            raise PermissionError(f"github api denied pull-request page {page}: http {status}")
        if status != 200:
            raise RuntimeError(f"github api pull-request page {page} failed: http {status}")
        try:
            items = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError(f"pull-request page {page} returned malformed json") from exc
        if not isinstance(items, list):
            raise ValueError(f"pull-request page {page} returned a non-list payload")
        try:
            next_page, terminal_page_proven = validated_next_page(
                link_header,
                repository=repository,
                current_page=page,
                per_page=per_page,
                state=state,
                trusted_repository_identity=self._trusted_identity(),
                endpoint="pulls",
            )
        except PaginationDiagnosticError as exc:
            raise ValueError(f"pull-request page {page}: {exc.kind}") from exc
        if next_page is None and terminal_page_proven:
            terminal_page_proven = _last_relation_names_page(link_header, page)
        return _respond(
            items=tuple(items),
            next_page=next_page,
            complete=True,
            terminal_page_proven=terminal_page_proven,
        )


def _last_relation_names_page(link_header: str | None, page: int) -> bool:
    """True unless a ``last`` relation names a page other than ``page``.

    Called only after ``validated_next_page`` parsed the same header, so the
    header itself is well formed; an unreadable ``last`` page is not proof.
    """
    last_url = parse_link_header(link_header).get("last")
    if last_url is None:
        return True
    values = urllib.parse.parse_qs(urllib.parse.urlsplit(last_url).query).get("page", [])
    return len(values) == 1 and values[0].isascii() and values[0].isdigit() and int(values[0]) == page


class LivePullRequestDetailReader:
    """PullRequestDetailReader over the live single-pull-request endpoint (GET only)."""

    def __init__(self, client: GitHubReadClient) -> None:
        self._client = client

    def read_pull_request(
        self, repository: str, pull_request_number: int
    ) -> PullRequestDetailResult:
        try:
            status, _, body = self._client.get(
                f"/repos/{repository}/pulls/{pull_request_number}"
            )
        except RuntimeError:
            return PullRequestDetailResult(outcome=PullRequestDetailOutcome.API_ERROR)
        if status == 404:
            return PullRequestDetailResult(outcome=PullRequestDetailOutcome.NOT_FOUND)
        if status in (401, 403):
            return PullRequestDetailResult(
                outcome=PullRequestDetailOutcome.PERMISSION_DENIED
            )
        if status != 200:
            return PullRequestDetailResult(outcome=PullRequestDetailOutcome.API_ERROR)
        try:
            item = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return PullRequestDetailResult(
                outcome=PullRequestDetailOutcome.MALFORMED_RESPONSE
            )
        if not isinstance(item, dict):
            return PullRequestDetailResult(
                outcome=PullRequestDetailOutcome.MALFORMED_RESPONSE
            )
        return PullRequestDetailResult(outcome=PullRequestDetailOutcome.OK, item=item)


class _RecordingCandidateEvidenceReader:
    """Adapt the production reader to the shadow seam, recording the named gap.

    The seam's ``CanonicalCandidateEvidenceReader`` protocol returns evidence
    or ``None``; the first named fail-closed reason is captured so the
    experiment record can name the exact missing canonical owner instead of
    a generic gap. Read-only: this wrapper performs no GitHub mutation.
    """

    def __init__(self, reader: LiveCandidateEvidenceReader) -> None:
        self._reader = reader
        self.first_failure_reason: str | None = None

    def read_candidate_evidence(self, repository: str, issue_number: int):
        outcome = self._reader.read_candidate_evidence_detailed(
            repository, issue_number
        )
        if outcome.evidence is None and self.first_failure_reason is None:
            self.first_failure_reason = outcome.failure_reason
        return outcome.evidence


def _parse_issue_list(raw: str | None, name: str) -> tuple[int, ...] | None:
    if raw is None:
        return None
    try:
        numbers = tuple(int(part.strip()) for part in raw.split(",") if part.strip())
    except ValueError:
        raise ValueError(f"--{name} must be a comma-separated list of issue numbers")
    if not numbers or any(number < 1 for number in numbers):
        raise ValueError(f"--{name} must contain only positive issue numbers")
    if len(set(numbers)) != len(numbers):
        raise ValueError(f"--{name} contains duplicates")
    return tuple(sorted(numbers))


#: Upper bound on candidates evaluated for the record after selection stopped.
RECORD_ONLY_LINEAGE_LIMIT = 25


def _record_only_lineage(acquirer, repository: str, candidate_issue_numbers) -> dict[str, object]:
    """Acquire lineage for candidates the selector never reached (#3441).

    ``select_shadow_issue`` stops at the first candidate with incomplete
    evidence, so one ambiguous candidate hides every later one. This reads
    the remaining candidates through the same GET-only acquirer, reusing its
    one cached pull-request population, purely for the experiment record. The
    selector has already returned; nothing here feeds it, so a later
    candidate's stage can never bypass the earlier candidate's conflict.
    """
    if not acquirer.observations:
        # The selector returned before reading any candidate evidence (for
        # example an over-capacity or invalid request); read nothing either.
        return {"candidates": [], "truncated": False}
    observed = {entry["issue_number"] for entry in acquirer.observations}
    remaining = [number for number in candidate_issue_numbers if number not in observed]
    start = len(acquirer.observations)
    errors: list[dict[str, object]] = []
    for issue_number in remaining[:RECORD_ONLY_LINEAGE_LIMIT]:
        try:
            acquirer.acquire_lifecycle_stage(repository, issue_number)
        except Exception as exc:  # noqa: BLE001 - selection already returned; never crash the record
            errors.append(
                {
                    "issue_number": issue_number,
                    "contract_version": PR_LINEAGE_READER_CONTRACT_VERSION,
                    "outcome": "not-acquired",
                    "reason_codes": ["record-only.acquisition-error"],
                    "failure_detail": f"{type(exc).__name__}: {exc}"[:240],
                }
            )
    candidates = [*map(dict, acquirer.observations[start:]), *errors]
    for entry in candidates:
        # Marked per entry so a merged list can never be read as selector input.
        entry["selection_input"] = False
    candidates.sort(key=lambda entry: entry["issue_number"])
    return {"candidates": candidates, "truncated": len(remaining) > RECORD_ONLY_LINEAGE_LIMIT}


def _build_experiment_record(
    *,
    repository: str,
    retrieved_at: str,
    campaign_id: str,
    result: ShadowIssueSelectionResult,
    client: GitHubReadClient,
    ledger_entries: tuple[dict[str, object], ...] = (),
    evidence_gap_reason: str | None = None,
    lifecycle_acquisition: Mapping[str, object] | None = None,
) -> dict[str, object]:
    # The selector result is the single source for the narrowing actually
    # applied: the operator-declared criterion on the manual path, or the
    # canonical ``canonical-request:<record>`` criterion from #3328 cohort
    # admission (which no CLI flag carries).
    population = result.population_issue_numbers
    candidates = result.candidate_issue_numbers
    narrowing_criterion = result.narrowing_criterion
    candidate_set = set(candidates)

    if result.reason_codes and "shadow-selection.population-incomplete" in result.reason_codes:
        excluded = [
            {"issue_number": number, "reason": "population-incomplete:scan-not-complete"}
            for number in population
        ]
    elif narrowing_criterion is not None:
        excluded = [
            {
                "issue_number": number,
                "reason": f"excluded-by-narrowing:{narrowing_criterion}",
            }
            for number in population
            if number not in candidate_set
        ]
    else:
        excluded = []

    stale_or_ambiguous: list[str] = []
    if "shadow-selection.candidate-evidence-incomplete" in result.reason_codes:
        gap = evidence_gap_reason or EVIDENCE_GAP
        stale_or_ambiguous.append(f"candidate-evidence-unavailable:{gap}")
    for code in result.reason_codes:
        if code in {
            "shadow-selection.population-incomplete",
            "shadow-selection.candidate-revision-mismatch",
            "shadow-selection.repository-revision-conflict",
            "shadow-selection.selected-issue-changed",
            "shadow-selection.selected-issue-reacquire-failed",
            "shadow-selection.issue-revision-unavailable",
        }:
            stale_or_ambiguous.append(f"seam-reported:{code}")

    manual_review: list[str] = []
    if result.status is not ShadowSelectionStatus.SELECTED:
        manual_review.append(
            f"no-selection:{','.join(result.reason_codes)} "
            "(human operator compares AI recommendation against this baseline)"
        )

    return {
        "experiment": "shadow-admission-phase0",
        "repository": repository,
        "retrieved_at": retrieved_at,
        "campaign_id": campaign_id,
        # 1. complete population receipt
        "population_receipt": {
            "scan_complete": "shadow-selection.population-incomplete" not in result.reason_codes,
            "scan_page_count": result.scan_page_count,
            "scan_item_count": result.scan_item_count,
            "population_issue_numbers": list(population),
        },
        # 2. candidate population considered
        "candidate_population": {
            "candidate_issue_numbers": list(candidates),
            "narrowing_criterion": narrowing_criterion,
        },
        # 3. excluded candidates and deterministic reasons
        "excluded_candidates": excluded,
        # 4. AI-selected/recommended candidate (filled by the experiment operator)
        "ai_recommended_candidate": None,
        # 5. deterministic selector result
        "cohort_admission": (
            None
            if result.cohort_admission is None
            else {
                "status": result.cohort_admission.status.value,
                "population_identity": result.cohort_admission.population_identity,
                "population_source_query": result.cohort_admission.population_source_query,
                "request_constraint_identity": result.cohort_admission.request_constraint_identity,
                "canonical_constraints_applied": list(
                    result.cohort_admission.canonical_constraints_applied
                ),
                "candidate_issue_numbers": list(
                    result.cohort_admission.candidate_issue_numbers
                ),
                "candidate_count": result.cohort_admission.candidate_count,
                "population_membership_proven": (
                    result.cohort_admission.population_membership_proven
                ),
                "reason_codes": list(result.cohort_admission.reason_codes),
                "fail_closed_reason": result.cohort_admission.fail_closed_reason,
                "execution_authorized": result.cohort_admission.execution_authorized,
                "side_effects_performed": result.cohort_admission.side_effects_performed,
            }
        ),
        "deterministic_selector_result": {
            "status": result.status.value,
            "reason_codes": list(result.reason_codes),
            "selected_issue_number": result.selected_issue_number,
            "selected_issue_revision": result.selected_issue_revision,
            "repository_source_revision": result.repository_source_revision,
            "narrowing_criterion": result.narrowing_criterion,
            "execution_authorized": result.execution_authorized,
            "side_effects_performed": result.side_effects_performed,
        },
        # 6-8. human comparison (filled by the experiment operator)
        "human_selected_candidate": None,
        "agreement": None,
        "disagreement_reason": None,
        # 9. stale/ambiguous evidence encountered
        "stale_or_ambiguous_evidence": stale_or_ambiguous,
        # 10. manual-review cases
        "manual_review_cases": manual_review,
        # 11. zero-mutation verification
        "zero_mutation_verification": {
            "http_get_requests": client.get_requests,
            "http_write_requests": client.write_requests,
            "github_mutations": 0,
            "execution_authorized": result.execution_authorized,
            "side_effects_performed": result.side_effects_performed,
        },
        # 12. finite-mission evidence ledger (Phase 1 B5): append-only,
        # hash-chained navigation decision entries bound to one mission_id.
        # Additive: the 11 Phase-0 fields above are unchanged.
        "evidence_ledger": list(ledger_entries),
        # 13. lifecycle-stage acquisition evidence (#3441): what the read-only
        # PR-lineage reader observed per candidate. Additive and non-authorizing;
        # None when the run configured no acquirer.
        "lifecycle_stage_acquisition": (
            None if lifecycle_acquisition is None else dict(lifecycle_acquisition)
        ),
    }


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Phase-0 shadow run: live population scan, deterministic narrowing, "
        "shadow selector invocation, experiment record emission. Read-only.",
    )
    parser.add_argument("--repository", default="Blummer92/agent-os")
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument(
        "--association-policy",
        choices=sorted(ASSOCIATION_POLICIES),
        default=ASSOCIATION_POLICY_DECLARED_NON_CLOSING_V1,
        help="PR association policy (default: declared-non-closing-v1)",
    )
    parser.add_argument(
        "--candidates",
        default=None,
        help="comma-separated explicit narrowing set (requires --narrowing-criterion)",
    )
    parser.add_argument("--narrowing-criterion", default=None)
    parser.add_argument(
        "--request-interpretation",
        default=None,
        help=(
            "path to canonical request-interpretation-v1 JSON; when supplied, "
            "ChatGPT Orchestrator cohort admission replaces manual --candidates"
        ),
    )
    parser.add_argument(
        "--explicit-order",
        default=None,
        help="comma-separated explicit request order (subset of --candidates)",
    )
    parser.add_argument(
        "--retrieved-at",
        default=None,
        help="UTC timestamp %%Y-%%m-%%dT%%H:%%M:%%SZ (default: now)",
    )
    parser.add_argument("--output", default=None, help="record path (default: stdout)")
    parser.add_argument(
        "--mission-id",
        default=None,
        help="mission id for the evidence ledger "
        "(default: derived deterministically as shadow-run:{campaign_id}:{retrieved_at})",
    )
    parser.add_argument(
        "--requested-mode",
        default=None,
        choices=[mode.value for mode in RequestedMode],
        help="explicit request operating mode (request-supplied; absent stays absent)",
    )
    parser.add_argument(
        "--dependency-depth",
        default=None,
        type=int,
        help="explicit request dependency depth, non-negative int (request-supplied)",
    )
    parser.add_argument(
        "--substitutable",
        default=None,
        action=argparse.BooleanOptionalAction,
        help="explicit request substitution semantics (request-supplied; "
        "absent stays absent, never defaulted)",
    )
    return parser.parse_args(argv)


def _resolve_mission_id(
    raw: str | None, *, campaign_id: str, retrieved_at: str
) -> str:
    """Resolve the ledger mission_id: an explicit --mission-id wins; otherwise
    it is derived deterministically as shadow-run:{campaign_id}:{retrieved_at}."""
    mission_id = raw if raw is not None else f"shadow-run:{campaign_id}:{retrieved_at}"
    if (
        not isinstance(mission_id, str)
        or not mission_id.strip()
        or len(mission_id) > 256
        or not mission_id.isprintable()
    ):
        raise ValueError("--mission-id must be 1-256 printable characters")
    return mission_id


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    try:
        candidates = _parse_issue_list(args.candidates, "candidates")
        explicit_order = _parse_issue_list(args.explicit_order, "explicit-order") or ()
        request_interpretation = None
        if args.request_interpretation is not None:
            raw_request = json.loads(
                Path(args.request_interpretation).read_text(encoding="utf-8")
            )
            validation = validate_request_interpretation(raw_request)
            if validation.status not in {
                ValidationStatus.VALID,
                ValidationStatus.MANUAL_REVIEW_REQUIRED,
            } or validation.record is None:
                raise ValueError(
                    "request interpretation must be a canonical request-interpretation-v1 record"
                )
            request_interpretation = RequestInterpretation(validation.record)
        if request_interpretation is not None and (
            candidates is not None or args.narrowing_criterion is not None
        ):
            raise ValueError(
                "--request-interpretation cannot be combined with manual candidate narrowing"
            )
        retrieved_at = args.retrieved_at or _datetime.datetime.now(
            _datetime.timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        if not _TIMESTAMP_RE.match(retrieved_at):
            raise ValueError("--retrieved-at must use %Y-%m-%dT%H:%M:%SZ form")
        mission_id = _resolve_mission_id(
            args.mission_id, campaign_id=args.campaign_id, retrieved_at=retrieved_at
        )
    except ValueError as exc:
        print(f"agent-os-shadow-run: argument error: {exc}", file=sys.stderr)
        return 2

    client = GitHubReadClient()
    # #3329 real-live composition: the repository HEAD SHA is read live from
    # the GitHub API (the canonical current-revision source for this
    # read-only context). Fail-closed on transport failure.
    try:
        source_revision = _fetch_repository_head_sha(client, args.repository)
    except RuntimeError as exc:
        print(f"agent-os-shadow-run: transport failure: {exc}", file=sys.stderr)
        return 1
    if args.dependency_depth is not None and args.dependency_depth < 0:
        print(
            "agent-os-shadow-run: argument error: "
            "--dependency-depth must be a non-negative int",
            file=sys.stderr,
        )
        return 2
    # One provenance log shared by the reader and the seam: the reader fills
    # it during the scan, the seam records the filled log on the result.
    provenance_log = ScanProvenanceLog()
    page_reader = LivePageReader(client, provenance_log)
    issue_transport = LiveIssueTransport(client)
    # #3329 Wire-or-Retire: the production canonical evidence reader replaces
    # the Phase-0 always-None stub. This shadow-run context now supplies every
    # input with an actual source:
    # - source_revision: live GitHub API default-branch HEAD SHA (canonical);
    # - freshness_state: CURRENT -- the composition performs the live issue
    #   read itself, so the evidence is current as of observed_at (the
    #   live_route_context.py precedent for live-verified evidence);
    # - environment: honest read-only self-description (UNPROBED local
    #   execution, UNSUPPORTED push -- this CLI never mutates);
    # - requested_mode / dependency_depth / substitutable: explicit
    #   request-supplied context via CLI flags (absent stays absent, never
    #   defaulted).
    # - lifecycle_stage: acquired per candidate from live PR lineage (#3441)
    #   through the unchanged #3433 evaluator; absent or ambiguous lineage
    #   stays fail-closed.
    # primary_claims and approval_applicability have no canonical live owner
    # for arbitrary backlog issues (#1460 forbids inventing claim or freshness
    # authorities), so the reader still fail-closes with their named reasons
    # -- the bounded blockers #3329 surfaces instead of manufacturing evidence.
    head_reader = _RepositoryHeadReader(client, args.repository)
    pr_lineage_acquirer = PrLineageAcquirer(
        repository=args.repository,
        issue_transport=issue_transport,
        page_reader=LivePullRequestPageReader(client, head_reader.trusted_identity),
        detail_reader=LivePullRequestDetailReader(client),
        source_revision_reader=head_reader.head_sha,
        observed_at=retrieved_at,
        association_policy=args.association_policy,
    )
    evidence_reader = _RecordingCandidateEvidenceReader(
        LiveCandidateEvidenceReader(
            LiveCandidateEvidence(
                repository=args.repository,
                issue_transport=issue_transport,
                observed_at=retrieved_at,
                source_revision=source_revision,
                lifecycle_stage=None,
                lifecycle_stage_acquirer=pr_lineage_acquirer,
                primary_claims=None,
                approval_applicability=None,
                freshness_state=FreshnessState.CURRENT,
                requested_mode=args.requested_mode,
                environment=_shadow_environment_capability(),
                dependency_depth=args.dependency_depth,
                substitutable=args.substitutable,
            )
        )
    )
    try:
        result = select_shadow_issue(
            repository=args.repository,
            retrieved_at=retrieved_at,
            campaign_id=args.campaign_id,
            page_reader=page_reader,
            issue_transport=issue_transport,
            candidate_evidence_reader=evidence_reader,
            candidate_issue_numbers=candidates,
            narrowing_criterion=args.narrowing_criterion,
            explicit_request_order=explicit_order,
            request_interpretation=request_interpretation,
            scan_provenance_log=provenance_log,
        )
    except (TypeError, ValueError) as exc:
        print(f"agent-os-shadow-run: contract violation: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"agent-os-shadow-run: transport failure: {exc}", file=sys.stderr)
        return 1

    recorded_at = _datetime.datetime.now(_datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    lifecycle_observations = pr_lineage_acquirer.observations
    record_only_observations = _record_only_lineage(
        pr_lineage_acquirer, args.repository, result.candidate_issue_numbers
    )
    inputs_digest = hash_decision_inputs(
        {
            "repository": args.repository,
            "campaign_id": args.campaign_id,
            "retrieved_at": retrieved_at,
            "candidate_issue_numbers": list(candidates)
            if candidates is not None
            else None,
            "narrowing_criterion": args.narrowing_criterion,
            "explicit_request_order": list(explicit_order),
            "cohort_admission": (
                None
                if result.cohort_admission is None
                else {
                    "request_constraint_identity": (
                        result.cohort_admission.request_constraint_identity
                    ),
                    "population_identity": result.cohort_admission.population_identity,
                    "status": result.cohort_admission.status.value,
                    "candidate_issue_numbers": list(
                        result.cohort_admission.candidate_issue_numbers
                    ),
                    "reason_codes": list(result.cohort_admission.reason_codes),
                }
            ),
            "population_issue_numbers": list(result.population_issue_numbers),
            "scan_page_count": result.scan_page_count,
            "scan_item_count": result.scan_item_count,
            "scan_source_query": result.scan_source_query,
            "scan_page_provenance": [
                entry.to_dict() for entry in result.scan_page_provenance
            ],
            "selection_status": result.status.value,
            "reason_codes": list(result.reason_codes),
            "lifecycle_acquisitions": [
                {
                    "issue_number": observation["issue_number"],
                    "outcome": observation["outcome"],
                    "result_id": observation.get("result_id"),
                    "reason_codes": observation["reason_codes"],
                }
                for observation in lifecycle_observations
            ],
        }
    )
    ledger = EvidenceLedger().append(
        mission_id=mission_id,
        decision_type=NavigationDecisionType.SELECTION,
        decision_label="shadow-selection",
        inputs_digest=inputs_digest,
        reason_codes=result.reason_codes,
        provenance_refs=tuple(
            sorted(
                {
                    f"scan-source-query:{result.scan_source_query}",
                    f"scan-pages:{result.scan_page_count}",
                    f"scan-items:{result.scan_item_count}",
                    f"population-issues:{len(result.population_issue_numbers)}",
                    "experiment-record:population_receipt",
                    "experiment-record:deterministic_selector_result",
                    "experiment-record:lifecycle_stage_acquisition",
                }
            )
        ),
        recorded_at=recorded_at,
        actor="agent-os-shadow-run/phase0",
    )

    record = _build_experiment_record(
        repository=args.repository,
        retrieved_at=retrieved_at,
        campaign_id=args.campaign_id,
        result=result,
        client=client,
        ledger_entries=tuple(entry.to_dict() for entry in ledger.entries),
        evidence_gap_reason=evidence_reader.first_failure_reason,
        lifecycle_acquisition={
            "contract_version": PR_LINEAGE_READER_CONTRACT_VERSION,
            "source": "scripts/agent_os_issue_acceptance/pr_lineage_reader.py",
            "population": pr_lineage_acquirer.population_summary,
            "candidates": list(lifecycle_observations),
            # The selector stops at the first candidate with incomplete evidence;
            # the remaining candidates' lineage is evaluated afterwards for this
            # record only and never reaches the selector.
            "record_only_candidates": record_only_observations["candidates"],
            "record_only_truncated": record_only_observations["truncated"],
            "primary_claims": "unresolved: no canonical owner; reader input stays None",
            "approval_applicability": "unresolved: no canonical owner; reader input stays None",
            # The reader fails closed on the missing primary claims before it
            # composes, so its acquisition_bindings_current re-check never runs
            # here; say so rather than imply the stages were revalidated.
            "consumer_boundary_revalidation": (
                "not-reached: primary_claims and approval_applicability are None, so the "
                "evidence reader fails closed before composition; each stage is bound only "
                "to the acquirer's own issue read and default-branch checks"
            ),
            "execution_authorized": False,
            "side_effects_performed": False,
        },
    )
    # Defense in depth: the read-only client must never have issued a write.
    assert client.write_requests == 0, "read-only client issued a write request"
    assert record["zero_mutation_verification"]["http_write_requests"] == 0

    payload = json.dumps(record, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
