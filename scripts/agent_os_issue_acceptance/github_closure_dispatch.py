"""Production GitHub adapter for governed issue closure (#3489).

This is the missing production caller for the existing closure machinery.
``run_closure_batch`` (approval domain) already defines the full governed
sequence -- finite candidate set, satisfaction and independent-acceptance
checks, owner-authorization admission, fresh-read verification, dispatch,
canonical readback, reconciliation, continuation past blocked items -- but
it had no production reader or writer: its protocols were implemented only
by test fakes, and the MCP closure tools are pure projections that perform
no GitHub I/O. This module supplies the live adapter, in the reporting
domain (reporting may import approval), without touching any approval
contract, authorization model, or evaluator.

Transport is an injected callable::

    request(method, path, body) -> (status: int, payload: dict)

so every behaviour below is testable without network access. The default
factory :func:`github_api_transport` uses the canonical GitHub client and
request helper, without a second HTTP implementation. Candidate issues come only from the caller-supplied manifest --
a finite, explicit set -- never from population enumeration.

Writer contract (exactly the fixed host dispatch contract): PATCH the
issue with ``{"state": "closed", "state_reason": "completed"}`` and
nothing else. A lost or ambiguous write response is reported as
:class:`ClosureWriteUncertain` so the batch reconciles through its
canonical readback instead of retrying blindly; an exact failure (4xx
and other non-5xx statuses) is a ``RuntimeError`` carrying the status,
never a false success. The writer never retries.

Reader contract: every read is a fresh GET of the single issue. A payload
carrying a ``pull_request`` key is a pull request, not an issue, and is
rejected with ``ValueError`` so the batch blocks rather than closing a
PR. Labels are included in full; any label outside the canonical label
shape fails closed with ``ValueError`` instead of being silently dropped.
The observed revision is content-addressed over the closure-relevant
fields, so it is identical across the batch's initial and fresh reads
when nothing changed (the verification gate then passes) and any
closure-relevant change fails the gate closed, as designed.

CLI: ``main`` reads a manifest, and writes only with ``--live``. Without
``--live`` it performs a dry run -- one fresh readback plus
``evaluate_issue_closure`` per issue -- and never constructs a writer.
The token is read only from the environment variable named by
``--token-env`` (default ``GITHUB_TOKEN``); it is never read from a file.
With ``--live`` and no token, the CLI exits 2 before any GitHub call.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import fields
from typing import Any

from github import Github

from scripts.agent_os_github_issue_provider.auth import build_token_client
from scripts.agent_os_github_issue_provider.request import GitHubRequestError, request_json

from .closure_admission_actions import (
    ClosureAcceptanceEvidence,
    ClosureIssueReadback,
    ClosureWriteUncertain,
    IssueClosureRequest,
    classify_closure_readback,
    evaluate_issue_closure,
    run_closure_batch,
)
from .lifecycle_mutation_authorization import LifecycleOwnerDecision
from .lifecycle_mutation_guard import LifecycleStateSnapshot
from .merge_authorization import MergeExecutionObservation
from .models import LinkedIssueParseStatus
from .parse_pr import parse_linked_issue_result

__all__ = [
    "GitHubClosureReader",
    "GitHubClosureWriter",
    "Transport",
    "github_api_transport",
    "load_closure_manifest",
    "run_closure_dispatch",
    "run_post_merge_closure_dispatch",
    "main",
]

# Callable transport: (method, path, body) -> (HTTP status, JSON payload).
Transport = Callable[[str, str, dict[str, object] | None], tuple[int, Any]]

_LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
_MANIFEST_KEYS = frozenset(
    {
        "repository",
        "issue_number",
        "authorizer_id",
        "decision_id",
        "decision_recorded",
        "evaluator_id",
        "evidence_id",
        "verdict",
    }
)
_MANIFEST_OPTIONAL_KEYS = frozenset(
    {
        "acceptance_issue_number",
        "acceptance_validated_head_sha",
        "satisfaction",
    }
)
_ACCEPTANCE_VERDICTS = frozenset({"pass", "fail", "missing"})
_CLOSE_PAYLOAD: dict[str, object] = {"state": "closed", "state_reason": "completed"}


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _revision(
    *,
    repository: str,
    issue_number: int,
    issue_state: str,
    state_reason: str | None,
    lifecycle_labels: tuple[str, ...],
    issue_body_digest: str,
) -> str:
    core = {
        "repository": repository,
        "issue_number": issue_number,
        "issue_state": issue_state,
        "state_reason": state_reason or "",
        "lifecycle_labels": sorted(lifecycle_labels),
        "issue_body_digest": issue_body_digest,
    }
    return "github-issue:" + hashlib.sha256(
        _canonical_json(core).encode("utf-8")
    ).hexdigest()


def _label_names(raw_labels: object) -> tuple[str, ...]:
    if type(raw_labels) is not list:
        raise ValueError("issue labels must be a list")
    names: list[str] = []
    for item in raw_labels:
        if type(item) is str:
            name = item
        elif type(item) is dict:
            name = item.get("name")
            if type(name) is not str:
                raise ValueError("issue label name must be a string")
        else:
            raise ValueError("issue label must be a string or an object with a name")
        if not _LABEL_RE.fullmatch(name):
            raise ValueError(f"issue label {name!r} is outside the canonical shape")
        names.append(name)
    return tuple(sorted(names))


def github_api_transport(token: str | None) -> Transport:
    """Adapt the canonical GitHub requester to the closure transport contract.

    Shared auth/request modules own credentials, HTTP encoding, and low-level
    errors. Writes use one attempt and never retry an uncertain result.
    Anonymous dry runs retain read-only access without credentials.
    """
    client = (
        build_token_client(
            {"GITHUB_TOKEN": token},
            user_agent="agent-os-closure-dispatch",
        )
        if token
        else Github(
            retry=None,
            lazy=False,
            user_agent="agent-os-closure-dispatch",
        )
    )

    def request(
        method: str, path: str, body: dict[str, object] | None
    ) -> tuple[int, Any]:
        try:
            response = request_json(
                client,
                method,
                path,
                input_payload=body,
                max_attempts=1,
            )
            return 200, response.payload
        except GitHubRequestError as exc:
            if type(exc.status) is int:
                return exc.status, {}
            if exc.kind == "transport-unavailable":
                raise ConnectionError("github-transport-unavailable") from exc
            raise RuntimeError(f"github-transport-failed:{exc.kind}") from exc

    return request


class GitHubClosureReader:
    """Live GitHub reader implementing the closure reader protocol."""

    def __init__(self, request: Transport) -> None:
        self._request = request

    def _fetch(
        self, repository: str, issue_number: int
    ) -> tuple[LifecycleStateSnapshot, str, str | None]:
        status, payload = self._request(
            "GET", f"/repos/{repository}/issues/{issue_number}", None
        )
        if status != 200:
            raise RuntimeError(f"github-issue-read-failed:{status}")
        if type(payload) is not dict:
            raise ValueError("issue read payload must be an object")
        if "pull_request" in payload:
            raise ValueError("payload is a pull request, not an issue")
        if "number" in payload and payload["number"] != issue_number:
            raise ValueError("issue read payload names a different issue")
        repository_url = payload.get("repository_url")
        if type(repository_url) is str:
            suffix = repository_url.rsplit("/repos/", 1)[-1]
            if "/repos/" not in repository_url or suffix != repository:
                raise ValueError("issue read payload names a different repository")
        issue_state = payload.get("state")
        if issue_state not in ("open", "closed"):
            raise ValueError("issue read payload has an unsupported state")
        body = payload.get("body")
        if body is None:
            body_text = ""
        elif type(body) is str:
            body_text = body
        else:
            raise ValueError("issue body must be a string or null")
        body_digest = hashlib.sha256(body_text.encode("utf-8")).hexdigest()
        labels = _label_names(payload.get("labels", []))
        raw_reason = payload.get("state_reason")
        if raw_reason is not None and type(raw_reason) is not str:
            raise ValueError("issue state_reason must be a string or null")
        snapshot = LifecycleStateSnapshot(
            repository=repository,
            issue_number=issue_number,
            pull_request_number=None,
            source_head=None,
            base_head=None,
            pr_state="none",
            merged=False,
            issue_state=issue_state,
            review_state="clear",
            unresolved_threads=0,
            lifecycle_labels=labels,
            observed_revision=_revision(
                repository=repository,
                issue_number=issue_number,
                issue_state=issue_state,
                state_reason=raw_reason,
                lifecycle_labels=labels,
                issue_body_digest=body_digest,
            ),
        )
        return snapshot, body_digest, raw_reason

    def read_issue_snapshot(
        self, repository: str, issue_number: int
    ) -> LifecycleStateSnapshot:
        snapshot, _, _ = self._fetch(repository, issue_number)
        return snapshot

    def read_issue_readback(
        self, repository: str, issue_number: int
    ) -> ClosureIssueReadback:
        snapshot, body_digest, raw_reason = self._fetch(repository, issue_number)
        # An open issue carries no terminal reason; a closed issue carries
        # GitHub's reason, validated by ClosureIssueReadback.
        state_reason = None if snapshot.issue_state == "open" else raw_reason
        return ClosureIssueReadback(
            snapshot=snapshot,
            state_reason=state_reason,
            issue_body_digest=body_digest,
        )


class GitHubClosureWriter:
    """Live GitHub writer implementing the closure writer protocol."""

    def __init__(self, request: Transport) -> None:
        self._request = request

    def close_issue(
        self, repository: str, issue_number: int, *, state_reason: str
    ) -> None:
        if state_reason != "completed":
            raise ValueError("closure writer only closes with state_reason completed")
        try:
            status, payload = self._request(
                "PATCH",
                f"/repos/{repository}/issues/{issue_number}",
                dict(_CLOSE_PAYLOAD),
            )
        except OSError as exc:
            # Timeout / connection failure: the write may have landed.
            # Never retry here; the batch reconciles through readback.
            raise ClosureWriteUncertain(
                f"github-issue-close-uncertain:{type(exc).__name__}"
            ) from exc
        if status == 200:
            if type(payload) is dict:
                if "state" in payload and payload["state"] != "closed":
                    raise ClosureWriteUncertain(
                        "github-issue-close-ambiguous: payload still open"
                    )
                if "state_reason" in payload and payload["state_reason"] != "completed":
                    raise ClosureWriteUncertain(
                        "github-issue-close-ambiguous: payload reason mismatch"
                    )
            return None
        if 500 <= status <= 599:
            raise ClosureWriteUncertain(f"github-issue-close-uncertain:{status}")
        raise RuntimeError(f"github-issue-close-failed:{status}")


def _exact_str(value: object, name: str) -> str:
    if type(value) is not str or not value:
        raise TypeError(f"{name} must be a non-empty built-in string")
    return value


def _exact_positive_int(value: object, name: str) -> int:
    # type(...) is int, not isinstance: a bool is not an issue number.
    if type(value) is not int or value < 1:
        raise TypeError(f"{name} must be a positive built-in integer")
    return value


def load_closure_manifest(mapping: Mapping[str, object]) -> tuple[IssueClosureRequest, ...]:
    """Strictly load a manifest mapping into the finite closure set.

    The manifest is exactly ``{"requests": [...]}``; each request carries
    exactly the required keys plus the optional acceptance/satisfaction
    keys. Anything else -- extra keys, bool-as-int, duplicate issue
    numbers, an empty set -- raises ``TypeError``/``ValueError`` and the
    CLI exits 2 without touching GitHub.
    """
    if not isinstance(mapping, Mapping):
        raise TypeError("closure manifest must be a mapping")
    if set(mapping) != {"requests"}:
        raise ValueError("closure manifest must carry exactly the 'requests' key")
    raw_requests = mapping["requests"]
    if type(raw_requests) is not list or not raw_requests:
        raise ValueError("closure manifest requests must be a non-empty list")
    requests: list[IssueClosureRequest] = []
    seen: set[int] = set()
    for raw in raw_requests:
        if not isinstance(raw, Mapping):
            raise TypeError("closure request must be a mapping")
        keys = set(raw)
        if not keys <= (_MANIFEST_KEYS | _MANIFEST_OPTIONAL_KEYS):
            raise ValueError("closure request carries unsupported keys")
        if not _MANIFEST_KEYS <= keys:
            raise ValueError("closure request is missing required keys")
        repository = _exact_str(raw["repository"], "repository")
        issue_number = _exact_positive_int(raw["issue_number"], "issue_number")
        if issue_number in seen:
            raise ValueError("closure manifest contains a duplicate issue")
        seen.add(issue_number)
        authorizer_id = _exact_str(raw["authorizer_id"], "authorizer_id")
        decision_id = _exact_str(raw["decision_id"], "decision_id")
        if type(raw["decision_recorded"]) is not bool:
            raise TypeError("decision_recorded must be a built-in bool")
        decision_recorded = raw["decision_recorded"]
        evaluator_id = _exact_str(raw["evaluator_id"], "evaluator_id")
        evidence_id = _exact_str(raw["evidence_id"], "evidence_id")
        verdict = raw["verdict"]
        if type(verdict) is not str or verdict not in _ACCEPTANCE_VERDICTS:
            raise ValueError("acceptance verdict is unsupported")
        acceptance_issue_number = raw.get("acceptance_issue_number")
        if acceptance_issue_number is not None:
            acceptance_issue_number = _exact_positive_int(
                acceptance_issue_number, "acceptance_issue_number"
            )
        acceptance_head = raw.get("acceptance_validated_head_sha")
        if acceptance_head is not None:
            acceptance_head = _exact_str(
                acceptance_head, "acceptance_validated_head_sha"
            )
        satisfaction = raw.get("satisfaction")
        if satisfaction is not None and not isinstance(satisfaction, Mapping):
            raise TypeError("satisfaction must be a mapping or absent")
        decision = LifecycleOwnerDecision(
            repository=repository,
            issue_number=issue_number,
            pull_request_number=None,
            requested_mutations=("close-issue",),
            authorizer_id=authorizer_id,
            decision_id=decision_id,
            decision_recorded=decision_recorded,
        )
        acceptance = ClosureAcceptanceEvidence(
            verdict=verdict,  # type: ignore[arg-type]
            evidence_id=evidence_id,
            evaluator_id=evaluator_id,
            issue_number=acceptance_issue_number,
            validated_head_sha=acceptance_head,
        )
        requests.append(
            IssueClosureRequest(
                decision=decision,
                acceptance=acceptance,
                satisfaction=satisfaction,  # type: ignore[arg-type]
            )
        )
    return tuple(requests)


def _outcome_dict(outcome: object) -> dict[str, object]:
    receipt = getattr(outcome, "receipt", None)
    receipt_id = None
    if isinstance(receipt, dict):
        receipt_id = receipt.get("receipt_id")
    return {
        "issue_number": outcome.issue_number,  # type: ignore[attr-defined]
        "status": outcome.status,  # type: ignore[attr-defined]
        "reason_codes": list(outcome.reason_codes),  # type: ignore[attr-defined]
        "readback_verified": outcome.readback_verified,  # type: ignore[attr-defined]
        "receipt_id": receipt_id,
    }


def run_closure_dispatch(
    manifest: Mapping[str, object] | tuple[IssueClosureRequest, ...],
    transport: Transport,
) -> list[dict[str, object]]:
    """Run the live governed closure batch for a loaded manifest.

    ``manifest`` is either the tuple returned by
    :func:`load_closure_manifest` or a raw mapping to load first. The
    batch itself -- admission, verification, dispatch, readback,
    continuation past blocked items -- is entirely ``run_closure_batch``;
    this function only supplies it with the production reader and writer.
    """
    if isinstance(manifest, Mapping):
        requests = load_closure_manifest(manifest)
    else:
        requests = manifest
    outcomes = run_closure_batch(
        requests,
        reader=GitHubClosureReader(transport),
        writer=GitHubClosureWriter(transport),
    )
    return [_outcome_dict(outcome) for outcome in outcomes]


def _verify_post_merge_observation(
    observation: MergeExecutionObservation,
    requests: tuple[IssueClosureRequest, ...],
    transport: Transport,
) -> None:
    """Correlate canonical merge-module evidence with a fresh merged PR.

    Merge evidence is a routing prerequisite, never closure authority.
    A single observed PR must have exactly one unambiguous linked issue in
    the canonical PR parser before the separately gated closure batch runs.
    """
    if type(observation) is not MergeExecutionObservation:
        raise TypeError("merge observation must be canonical MergeExecutionObservation")
    # Check content identity rather than treating a supplied hash as authority.
    observation.__post_init__()
    if len(requests) != 1:
        raise ValueError("post-merge dispatch requires exactly one issue request")
    decision = requests[0].decision
    if decision.repository != observation.repository:
        raise ValueError("merge-observation.repository-mismatch")
    if decision.issue_number is None:
        raise ValueError("merge-observation.issue-number-missing")

    path = (
        f"/repos/{observation.repository}/pulls/"
        f"{observation.pull_request_number}"
    )
    status, raw = transport("GET", path, None)
    if status != 200 or type(raw) is not dict:
        raise ValueError("merge-observation.pr-readback-unavailable")
    if (
        type(raw.get("number")) is not int
        or raw["number"] != observation.pull_request_number
        or raw.get("state") != "closed"
        or raw.get("merged") is not True
        or type(raw.get("merged_at")) is not str
        or not raw["merged_at"]
        or raw.get("merge_commit_sha") != observation.observed_merge_commit_sha
    ):
        raise ValueError("merge-observation.pr-not-verified-merged")
    head = raw.get("head")
    base = raw.get("base")
    if (
        type(head) is not dict
        or head.get("sha") != observation.observed_head_sha
        or type(base) is not dict
        or base.get("ref") != "main"
        or type(base.get("repo")) is not dict
        or base["repo"].get("full_name") != observation.repository
    ):
        raise ValueError("merge-observation.pr-identity-mismatch")
    title, body = raw.get("title"), raw.get("body")
    if type(title) is not str or type(body) is not str:
        raise ValueError("merge-observation.pr-linkage-unavailable")
    linkage = parse_linked_issue_result(body, title)
    target = decision.issue_number
    if linkage.status is LinkedIssueParseStatus.RESOLVED:
        if (
            linkage.issue_number != target
            or any(ref.issue_number != target for ref in linkage.bare_references)
        ):
            # A closing directive for one issue cannot silently absorb other
            # issue references. Investigate ambiguous lineage first.
            raise ValueError("merge-observation.pr-linkage-ambiguous")
    elif linkage.status is LinkedIssueParseStatus.INFORMATIONAL:
        if {ref.issue_number for ref in linkage.bare_references} != {target}:
            raise ValueError("merge-observation.pr-linkage-ambiguous")
    else:
        raise ValueError("merge-observation.pr-linkage-not-admitted")


def run_post_merge_closure_dispatch(
    observation: MergeExecutionObservation,
    manifest: Mapping[str, object] | tuple[IssueClosureRequest, ...],
    transport: Transport,
) -> list[dict[str, object]]:
    """Consume the existing merge observation and governed closure batch.

    Fresh GitHub merged-PR readback binds the observation to the exact
    issue. Closure is still refused unless the *independent* owner decision,
    satisfaction, QA, and fresh issue admission permit it. There is no merge
    or issue-write authority in the observation.
    """
    requests = (
        load_closure_manifest(manifest)
        if isinstance(manifest, Mapping)
        else manifest
    )
    _verify_post_merge_observation(observation, requests, transport)
    outcomes = run_closure_dispatch(requests, transport)
    return [
        {
            **outcome,
            "merge_observation_id": observation.observation_id,
            "merge_commit_sha": observation.observed_merge_commit_sha,
        }
        for outcome in outcomes
    ]


def _load_merge_observation(path: str) -> MergeExecutionObservation:
    """Read one canonical merge-execution observation; reject extra fields."""
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    allowed = {field.name for field in fields(MergeExecutionObservation) if field.init}
    if type(payload) is not dict or set(payload) != allowed:
        raise ValueError("merge observation fields are invalid")
    return MergeExecutionObservation(**payload)


def _dry_run_outcomes(
    requests: tuple[IssueClosureRequest, ...], reader: GitHubClosureReader
) -> list[dict[str, object]]:
    """Dry-run evaluation: readback + admission only, never a writer."""
    outcomes: list[dict[str, object]] = []
    for request in requests:
        decision = request.decision
        issue_number = decision.issue_number
        assert issue_number is not None
        repository = decision.repository
        try:
            readback = reader.read_issue_readback(repository, issue_number)
        except Exception:
            outcomes.append(
                {
                    "issue_number": issue_number,
                    "status": "blocked",
                    "reason_codes": ["closure.evidence-unavailable"],
                    "readback_verified": False,
                    "receipt_id": None,
                }
            )
            continue
        snapshot = readback.snapshot
        if snapshot.repository != repository or snapshot.issue_number != issue_number:
            outcomes.append(
                {
                    "issue_number": issue_number,
                    "status": "blocked",
                    "reason_codes": ["closure.readback-identity-mismatch"],
                    "readback_verified": False,
                    "receipt_id": None,
                }
            )
            continue
        if snapshot.issue_state == "closed":
            status, reasons, verified = classify_closure_readback(
                issue_closed=True,
                state_reason=readback.state_reason,
                lifecycle_labels=snapshot.lifecycle_labels,
                wrote=False,
            )
            outcomes.append(
                {
                    "issue_number": issue_number,
                    "status": (
                        "already-closed"
                        if verified and status == "closed-verified"
                        else status
                    ),
                    "reason_codes": list(reasons),
                    "readback_verified": verified,
                    "receipt_id": None,
                }
            )
            continue
        if readback.state_reason is not None:
            outcomes.append(
                {
                    "issue_number": issue_number,
                    "status": "readback-inconsistent",
                    "reason_codes": ["closure.readback-inconsistent"],
                    "readback_verified": False,
                    "receipt_id": None,
                }
            )
            continue
        receipt = evaluate_issue_closure(
            request,
            snapshot,
            current_issue_body_digest=readback.issue_body_digest,
        )
        outcomes.append(
            {
                "issue_number": issue_number,
                "status": "would-close"
                if receipt["admitted"] is True
                else "blocked",
                "reason_codes": list(receipt["reason_codes"]),  # type: ignore[arg-type]
                "readback_verified": False,
                "receipt_id": receipt["receipt_id"],
            }
        )
    return outcomes


def main(argv: list[str] | None = None, *, transport: Transport | None = None) -> int:
    """CLI entry point. Returns a process exit code; prints one JSON object.

    ``transport`` is a test seam only: when supplied, it replaces the
    canonical GitHub transport (and the live token check is skipped, since the
    injected transport is the test's credential surface). In production
    use it is always ``None``.
    """
    parser = argparse.ArgumentParser(
        prog="github_closure_dispatch",
        description="Governed GitHub issue closure dispatch (#3489).",
    )
    parser.add_argument("--manifest", required=True, help="Path to the JSON manifest.")
    parser.add_argument(
        "--merge-observation",
        help="Canonical merge-module observation JSON. Requires verified merged-PR readback.",
    )
    parser.add_argument(
        "--token-env",
        default="GITHUB_TOKEN",
        help="Environment variable holding the GitHub token (live mode only).",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Actually dispatch closures. Without this flag, dry-run only.",
    )
    args = parser.parse_args(argv)
    try:
        with open(args.manifest, encoding="utf-8") as handle:
            raw_manifest = json.load(handle)
    except (OSError, ValueError) as exc:
        print(f"manifest error: {exc}", file=sys.stderr)
        return 2
    try:
        requests = load_closure_manifest(raw_manifest)
    except (TypeError, ValueError) as exc:
        print(f"manifest error: {exc}", file=sys.stderr)
        return 2
    if args.live and transport is None:
        token = os.environ.get(args.token_env)
        if not token:
            print(
                f"live mode requires a token in ${args.token_env}",
                file=sys.stderr,
            )
            return 2
    else:
        token = os.environ.get(args.token_env) if transport is None else None
    live_transport = transport if transport is not None else github_api_transport(token)
    observation = None
    if args.merge_observation is not None:
        try:
            observation = _load_merge_observation(args.merge_observation)
            _verify_post_merge_observation(observation, requests, live_transport)
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            print(f"merge observation error: {exc}", file=sys.stderr)
            return 2
    if args.live:
        outcomes = (
            run_post_merge_closure_dispatch(observation, requests, live_transport)
            if observation is not None
            else run_closure_dispatch(requests, live_transport)
        )
    else:
        # Dry run: no writer constructed, regardless of merge observation.
        outcomes = _dry_run_outcomes(requests, GitHubClosureReader(live_transport))
    if observation is not None:
        outcomes = [
            {
                **outcome,
                "merge_observation_id": observation.observation_id,
                "merge_commit_sha": observation.observed_merge_commit_sha,
            }
            for outcome in outcomes
        ] if not args.live else outcomes
    print(json.dumps({"live": bool(args.live), "outcomes": outcomes}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
