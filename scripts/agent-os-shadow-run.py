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
It still fails closed with a named ``candidate-evidence.*`` reason wherever
no canonical live owner exists: ``lifecycle_stage`` (no lifecycle
authority; #1460 forbids inventing one), ``primary_claims`` (no live
PR-linkage reader; #1460 forbids inventing claim authority), and
``approval_applicability`` (the approval evidence graph is not
reconstructible for arbitrary backlog issues). Those three are #3329's
bounded blockers -- surfaced, not manufactured. The seam therefore still
fail-closes with ``candidate-evidence-incomplete`` for the real backlog,
and the experiment record names the exact missing owner instead of filling
the gap. The real-backlog acceptance canary remains gated on #3328's
legitimate cohort plus caller-supplied request context. Feeding a
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
from agent_os_execution_service.evidence_ledger import (  # noqa: E402
    EvidenceLedger,
    NavigationDecisionType,
    hash_decision_inputs,
)
from scripts.agent_os_issue_acceptance.github_issue_source import (  # noqa: E402
    GitHubIssuePageResponse,
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
    "context: repository source revision, lifecycle stage, primary claims, "
    "approval applicability, freshness, requested mode, environment "
    "capability, dependency depth, and substitutable have no canonical live "
    "owners for arbitrary backlog issues; #1460 forbids inventing PR-linkage "
    "or lifecycle-stage authority inside a reader"
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
    status, _, body = client.get(f"/repos/{repository}")
    if status != 200:
        raise RuntimeError(
            f"github api: repository read failed for {repository} (http {status})"
        )
    try:
        default_branch = json.loads(body)["default_branch"]
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(
            f"github api: repository payload malformed for {repository}"
        ) from exc
    if not isinstance(default_branch, str) or not default_branch:
        raise RuntimeError(
            f"github api: default branch missing for {repository}"
        )
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


def _build_experiment_record(
    *,
    repository: str,
    retrieved_at: str,
    campaign_id: str,
    narrowing_criterion: str | None,
    result: ShadowIssueSelectionResult,
    client: GitHubReadClient,
    ledger_entries: tuple[dict[str, object], ...] = (),
    evidence_gap_reason: str | None = None,
) -> dict[str, object]:
    population = result.population_issue_numbers
    candidates = result.candidate_issue_numbers
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
    }


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Phase-0 shadow run: live population scan, deterministic narrowing, "
        "shadow selector invocation, experiment record emission. Read-only.",
    )
    parser.add_argument("--repository", default="Blummer92/agent-os")
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument(
        "--candidates",
        default=None,
        help="comma-separated explicit narrowing set (requires --narrowing-criterion)",
    )
    parser.add_argument("--narrowing-criterion", default=None)
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
    # lifecycle_stage, primary_claims, and approval_applicability have no
    # canonical live owner for arbitrary backlog issues (#1460 forbids
    # inventing PR-linkage, lifecycle, claim, or freshness authorities), so
    # the reader still fail-closes with their named reasons -- the bounded
    # blockers #3329 surfaces instead of manufacturing evidence.
    evidence_reader = _RecordingCandidateEvidenceReader(
        LiveCandidateEvidenceReader(
            LiveCandidateEvidence(
                repository=args.repository,
                issue_transport=issue_transport,
                observed_at=retrieved_at,
                source_revision=source_revision,
                lifecycle_stage=None,
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
            "population_issue_numbers": list(result.population_issue_numbers),
            "scan_page_count": result.scan_page_count,
            "scan_item_count": result.scan_item_count,
            "scan_source_query": result.scan_source_query,
            "scan_page_provenance": [
                entry.to_dict() for entry in result.scan_page_provenance
            ],
            "selection_status": result.status.value,
            "reason_codes": list(result.reason_codes),
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
        narrowing_criterion=args.narrowing_criterion,
        result=result,
        client=client,
        ledger_entries=tuple(entry.to_dict() for entry in ledger.entries),
        evidence_gap_reason=evidence_reader.first_failure_reason,
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
