#!/usr/bin/env python3
"""Phase-0 shadow-run CLI: the first production caller of ``select_shadow_issue``.

Read-only. Performs a live paginated open-issue scan against the GitHub REST
API, applies the deterministic narrowing contract, invokes the shadow selector
seam (``08_Tooling/agent-os-execution-service/.../shadow_issue_selection.py``),
and emits the shadow experiment record as JSON.

It performs no GitHub mutation, authorizes no execution, and manufactures no
operational state.

Phase-0 evidence boundary: no live canonical candidate-evidence acquirers exist
for arbitrary backlog issues (lifecycle stage, approval applicability,
dependency, validation, freshness, and claim inputs), and #1460 forbids a reader
from inventing PR-linkage or lifecycle-stage authority. The evidence reader
below therefore supplies no candidate evidence and the seam fail-closes with
``candidate-evidence-incomplete``; the experiment record names the gap instead
of filling it. Building the live evidence chain is Workstream B/C work. Feeding
a ``SELECTED`` result into the governed issue-start path is #3082 (Phase 1+);
this CLI is the producer side of that future connection.

Runtime: run inside the isolated execution-service runtime (``mcp``,
``PyGithub``, ``pyyaml``, plus the sibling ``workflow-scheduler``,
``agent-memory-context-manager`` and ``instructional-workflow-contracts``
distributions), e.g. the venv described in ``SHADOW_ISSUE_SELECTION.md``.
Network access is read-only: only HTTP GET is ever issued. ``GITHUB_TOKEN``,
when set, is used as a bearer token to raise the API rate limit; it is never
logged or written anywhere.
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
    ShadowIssueSelectionResult,
    ShadowSelectionStatus,
    select_shadow_issue,
)
from scripts.agent_os_issue_acceptance.github_issue_source import (  # noqa: E402
    GitHubIssuePageResponse,
)
from scripts.agent_os_issue_acceptance.issue_scanner import IssueStateFilter  # noqa: E402
from scripts.agent_os_candidate_packet_live_input import (  # noqa: E402
    SingleIssueTransportOutcome,
    SingleIssueTransportResult,
)

_API = "https://api.github.com"
_LINK_NEXT_RE = re.compile(r'<([^>]+)>;\s*rel="next"')
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

# The Phase-0 evidence gap, recorded rather than filled. Each missing input
# names the canonical owner that must supply a live acquirer before the
# deterministic baseline can select from the real backlog.
EVIDENCE_GAP = (
    "no live canonical candidate-evidence acquirers for arbitrary backlog issues: "
    "lifecycle-stage, approval-applicability, dependency, validation, freshness, "
    "and primary-claim inputs are unavailable read-only; #1460 forbids inventing "
    "PR-linkage or lifecycle-stage authority inside a reader"
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


class LivePageReader:
    """GitHubIssuePageReader over the live issues endpoint (GET only)."""

    def __init__(self, client: GitHubReadClient) -> None:
        self._client = client

    def read_issue_page(
        self, repository: str, *, page: int, per_page: int, state: str
    ) -> GitHubIssuePageResponse:
        status, headers, body = self._client.get(
            f"/repos/{repository}/issues?state={state}&per_page={per_page}&page={page}"
        )
        if status == 403 and headers.get("x-ratelimit-remaining") == "0":
            return GitHubIssuePageResponse(
                items=(), next_page=None, complete=False, error_kind="rate-limited"
            )
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
        has_next = _LINK_NEXT_RE.search(headers.get("link", "")) is not None
        return GitHubIssuePageResponse(
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


class Phase0CandidateEvidenceReader:
    """Phase-0 evidence boundary: supplies no candidate evidence.

    Returning None for every candidate is the honest Phase-0 behavior: no live
    canonical evidence acquirers exist for arbitrary backlog issues, and #1460
    forbids inventing the missing lifecycle/PR-linkage authority. The seam
    fail-closes with ``candidate-evidence-incomplete`` and the experiment
    record carries EVIDENCE_GAP instead of manufactured state.
    """

    def read_candidate_evidence(self, repository: str, issue_number: int):  # noqa: ANN001, ANN202
        return None


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
        stale_or_ambiguous.append(f"candidate-evidence-unavailable:{EVIDENCE_GAP}")
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
    return parser.parse_args(argv)


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
    except ValueError as exc:
        print(f"agent-os-shadow-run: argument error: {exc}", file=sys.stderr)
        return 2

    client = GitHubReadClient()
    try:
        result = select_shadow_issue(
            repository=args.repository,
            retrieved_at=retrieved_at,
            campaign_id=args.campaign_id,
            page_reader=LivePageReader(client),
            issue_transport=LiveIssueTransport(client),
            candidate_evidence_reader=Phase0CandidateEvidenceReader(),
            candidate_issue_numbers=candidates,
            narrowing_criterion=args.narrowing_criterion,
            explicit_request_order=explicit_order,
        )
    except (TypeError, ValueError) as exc:
        print(f"agent-os-shadow-run: contract violation: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"agent-os-shadow-run: transport failure: {exc}", file=sys.stderr)
        return 1

    record = _build_experiment_record(
        repository=args.repository,
        retrieved_at=retrieved_at,
        campaign_id=args.campaign_id,
        narrowing_criterion=args.narrowing_criterion,
        result=result,
        client=client,
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
