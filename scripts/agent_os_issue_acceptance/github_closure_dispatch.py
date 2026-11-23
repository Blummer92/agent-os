"""Production GitHub reader/writer for the governed closure batch (#3489).

This module supplies the one production implementation of the
``ClosureIssueReader`` / ``ClosureIssueWriter`` protocols that the existing
``run_closure_batch`` (approval domain) already defines. Until this module,
those protocols were implemented only by test fakes, while the MCP closure
tools are pure projections that perform no GitHub I/O. This module changes
neither: admission, receipt verification, satisfaction, and lifecycle
evaluation are imported unchanged from ``closure_admission_actions``.

TRUST BOUNDARY — read this before calling anything here. This module
authenticates nothing. It takes ``tuple[IssueClosureRequest, ...]`` objects
from its caller, exactly as the MCP admit/verify tools take request objects
from the host. The caller — a trusted host session, e.g. the GitHub Service
Agent session acting under runtime approval for the write — must have
reacquired the owner decision and the independent QA evidence from their
trusted sources (owner-authored records, QA artifacts) before constructing
those objects. There is deliberately NO manifest format, NO CLI, and NO
file loader in this module: a previous revision accepted a JSON manifest
carrying ``decision_recorded`` / ``authorizer_id`` / ``evaluator_id`` /
``evidence_id`` / ``verdict`` as caller strings, and the canonical producer
checks only that ``decision_recorded`` is True and that evaluator differs
from authorizer — so any manifest author could manufacture apparently valid
owner authorization and independent QA evidence. That surface is deleted,
not repaired: a caller-authored file must never become an authority source.

The same boundary applies to merge evidence. ``run_post_merge_closure_dispatch``
takes a ``MergeExecutionObservation`` object from the host that observed the
merge; it never loads one from a file. The observation itself is corroborated
against a fresh merged-PR readback (head, merge commit, actor when GitHub
supplies one, base, and PR-to-issue linkage) before the batch runs, and merge
evidence is a routing prerequisite only: closure still requires the
independent owner decision, satisfaction, QA, and fresh issue admission
inside ``run_closure_batch``. A head-bound QA record cannot be honoured by
the issue-only reader below (its snapshot carries no PR head), and fails
closed by the canonical ADV-2 rule — that is the intended behaviour, not a
gap to paper over with a caller-supplied head.

Reader honesty. The reader performs one fresh GET of a single issue and
builds an ISSUE-ONLY snapshot: ``pull_request_number`` / ``source_head`` /
``base_head`` are None, ``pr_state`` is ``"none"``, ``merged`` is False, and
``review_state`` is ``"unknown"`` — the value the snapshot type provides for
unobserved review state. An issue-only read cannot claim ``"clear"``.
The observed revision is the CANONICAL provider revision
(``github-issue-v1:<sha256>`` from
``agent_os_github_issue_provider.revision.issue_source_revision``), so any
change to the canonical payload fields (title, state, body, timestamps,
labels, reason) moves the revision and the batch's verification gate fails
closed. A payload carrying a ``pull_request`` key is a pull request, not an
issue, and is rejected.

Writer contract (exactly the fixed host dispatch contract): PATCH the issue
with ``{"state": "closed", "state_reason": "completed"}`` and nothing else
for the close itself. A lost or ambiguous write response is reported as
``ClosureWriteUncertain`` so the batch reconciles through its canonical
readback instead of retrying blindly; an exact failure is a ``RuntimeError``
carrying the status, never a false success. The writer never retries.
Requirement 3 reconciliation is a separate, post-close phase in
``run_closure_dispatch`` only, and only for items this batch freshly
closed and verified: it removes exactly the ``status:ready`` label when
the verified readback still carries it, posts one deterministic evidence
comment built only from verified facts (repository, issue, completed
reason, acceptance evidence id and evaluator, admission receipt id — no
closing keyword, no host-invented prose), and then re-reads the issue to
verify the label is gone and the comment is present. Any reconciliation
failure keeps the verified closure outcome but records a distinct
``closed-verified-reconciliation-failed`` status; it never retries, never
touches any other label, and never reconciles an already-closed item,
whose batch path carries no admission receipt for this run.

Transport is an injected callable::

    request(method, path, body) -> (status: int, payload: dict)

so every behaviour below is testable without network access. The default
factory :func:`github_api_transport` uses the canonical GitHub client and
request helper, without a second HTTP implementation.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from typing import Any

from github import Github

from scripts.agent_os_github_issue_provider.auth import build_token_client
from scripts.agent_os_github_issue_provider.request import GitHubRequestError, request_json
from scripts.agent_os_github_issue_provider.revision import issue_source_revision

from .closure_admission_actions import (
    ClosureIssueReadback,
    ClosureWriteUncertain,
    IssueClosureRequest,
    run_closure_batch,
)
from .lifecycle_mutation_guard import LifecycleStateSnapshot
from .merge_authorization import MergeExecutionObservation
from .models import LinkedIssueParseStatus
from .parse_pr import parse_linked_issue_result

__all__ = [
    "GitHubClosureReader",
    "GitHubClosureWriter",
    "Transport",
    "github_api_transport",
    "run_closure_dispatch",
    "run_post_merge_closure_dispatch",
]

# Callable transport: (method, path, body) -> (HTTP status, JSON payload).
Transport = Callable[[str, str, dict[str, object] | None], tuple[int, Any]]

_LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
_CLOSE_PAYLOAD: dict[str, object] = {"state": "closed", "state_reason": "completed"}


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
    """Live GitHub reader implementing the closure reader protocol.

    Issue-only: see the module trust-boundary note for why the snapshot
    carries no PR state and ``review_state="unknown"``.
    """

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
        # Canonical provider revision: missing canonical fields fail closed
        # here (ValueError from issue_source_revision) instead of silently
        # producing a weaker, adapter-local revision.
        observed_revision = issue_source_revision(payload)
        snapshot = LifecycleStateSnapshot(
            repository=repository,
            issue_number=issue_number,
            pull_request_number=None,
            source_head=None,
            base_head=None,
            pr_state="none",
            merged=False,
            issue_state=issue_state,
            review_state="unknown",
            unresolved_threads=0,
            lifecycle_labels=labels,
            observed_revision=observed_revision,
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

    def remove_label(
        self, repository: str, issue_number: int, *, label: str
    ) -> None:
        if label != "status:ready":
            raise ValueError("closure writer only removes the status:ready label")
        try:
            status, _payload = self._request(
                "DELETE",
                f"/repos/{repository}/issues/{issue_number}/labels/{label}",
                None,
            )
        except OSError as exc:
            raise ClosureWriteUncertain(
                f"github-issue-label-remove-uncertain:{type(exc).__name__}"
            ) from exc
        if status in (200, 204, 404):
            # 404 means the label is already gone: the reconciliation goal
            # is achieved. The post-phase re-read still verifies this.
            return None
        if 500 <= status <= 599:
            raise ClosureWriteUncertain(
                f"github-issue-label-remove-uncertain:{status}"
            )
        raise RuntimeError(f"github-issue-label-remove-failed:{status}")

    def list_comment_bodies(
        self, repository: str, issue_number: int
    ) -> list[str]:
        status, payload = self._request(
            "GET",
            f"/repos/{repository}/issues/{issue_number}/comments",
            None,
        )
        if status != 200 or not isinstance(payload, list):
            raise RuntimeError("comment readback unavailable")
        return [
            item.get("body")
            for item in payload
            if isinstance(item, dict) and isinstance(item.get("body"), str)
        ]

    def post_comment(
        self, repository: str, issue_number: int, *, body: str
    ) -> None:
        if type(body) is not str or not body.strip():
            raise ValueError("evidence comment body must be a non-empty string")
        if "closes #" in body.lower() or "fixes #" in body.lower() or "resolves #" in body.lower():
            raise ValueError("evidence comment must not carry a closing keyword")
        try:
            status, _payload = self._request(
                "POST",
                f"/repos/{repository}/issues/{issue_number}/comments",
                {"body": body},
            )
        except OSError as exc:
            raise ClosureWriteUncertain(
                f"github-issue-comment-uncertain:{type(exc).__name__}"
            ) from exc
        if status in (200, 201):
            return None
        if 500 <= status <= 599:
            raise ClosureWriteUncertain(f"github-issue-comment-uncertain:{status}")
        raise RuntimeError(f"github-issue-comment-failed:{status}")


def _completion_comment(
    *,
    repository: str,
    issue_number: int,
    evidence_id: str,
    evaluator_id: str,
    receipt_id: str | None,
) -> str:
    # Deterministic, verified-facts-only body. No closing keyword, no
    # host-invented claim about scope, and no other issue reference.
    return (
        "Governed closure verified.\n"
        f"Repository: {repository}\n"
        f"Issue: {issue_number}\n"
        "State: closed, reason completed.\n"
        f"Acceptance evidence: {evidence_id} (evaluator {evaluator_id}).\n"
        f"Admission receipt: {receipt_id or 'unavailable'}.\n"
        "Verified by canonical post-write readback."
    )


def _reconcile_closed_items(
    *,
    requests: tuple[IssueClosureRequest, ...],
    outcomes: object,
    reader: GitHubClosureReader,
    writer: GitHubClosureWriter,
) -> list[dict[str, object]]:
    """Post-close requirement 3 reconciliation for freshly closed items.

    Only items whose batch outcome starts with ``closed-verified`` and is
    readback-verified are eligible: those are the items this run admitted,
    verified, closed, and read back. Already-closed, blocked, and failed
    items are returned unchanged, and a reconciliation failure on one item
    never stops the next item. No step here retries.
    """
    by_issue = {item.decision.issue_number: item for item in requests}
    reconciled: list[dict[str, object]] = []
    for outcome in outcomes:  # type: ignore[attr-defined]
        record = _outcome_dict(outcome)
        status = str(record["status"])
        if not status.startswith("closed-verified") or not record["readback_verified"]:
            record["label_reconciled"] = False
            record["evidence_comment_posted"] = False
            reconciled.append(record)
            continue
        request = by_issue.get(outcome.issue_number)  # type: ignore[attr-defined]
        if request is None:
            record["label_reconciled"] = False
            record["evidence_comment_posted"] = False
            reconciled.append(record)
            continue
        repository = request.decision.repository
        issue_number = request.decision.issue_number
        assert issue_number is not None
        stale_ready = "closure.stale-ready-label-present" in outcome.reason_codes  # type: ignore[attr-defined]
        try:
            if stale_ready:
                writer.remove_label(repository, issue_number, label="status:ready")
            writer.post_comment(
                repository,
                issue_number,
                body=_completion_comment(
                    repository=repository,
                    issue_number=issue_number,
                    evidence_id=request.acceptance.evidence_id,
                    evaluator_id=request.acceptance.evaluator_id,
                    receipt_id=record["receipt_id"] if isinstance(record["receipt_id"], str) else None,
                ),
            )
            after = reader.read_issue_readback(repository, issue_number)
            if after.snapshot.issue_state != "closed" or after.state_reason != "completed":
                raise RuntimeError("reconciliation readback no longer closed-completed")
            if stale_ready and "status:ready" in after.snapshot.lifecycle_labels:
                raise RuntimeError("reconciliation readback still carries status:ready")
            if not stale_ready and "status:ready" in after.snapshot.lifecycle_labels:
                # A label that appeared between reads is not silently ignored.
                raise RuntimeError("reconciliation readback carries status:ready")
            # Verify the posted comment is present by receipt id, when known.
            receipt_id = record["receipt_id"]
            if isinstance(receipt_id, str):
                bodies = writer.list_comment_bodies(repository, issue_number)
                if receipt_id not in " ".join(bodies):
                    raise RuntimeError("reconciliation comment not found in readback")
            # After successful reconciliation the label requirement is
            # discharged: the status no longer claims it is required.
            record["status"] = (
                status.replace("-label-reconciliation-required", "")
                if stale_ready
                else status
            )
            record["label_reconciled"] = stale_ready
            record["evidence_comment_posted"] = True
            reasons = list(record["reason_codes"])
            if stale_ready and "closure.label-reconciled" not in reasons:
                reasons.append("closure.label-reconciled")
            if "closure.evidence-comment-posted" not in reasons:
                reasons.append("closure.evidence-comment-posted")
            record["reason_codes"] = reasons
        except Exception as exc:
            # Closure itself stays verified; only reconciliation failed.
            record["status"] = "closed-verified-reconciliation-failed"
            record["label_reconciled"] = False
            record["evidence_comment_posted"] = False
            reasons = list(record["reason_codes"])
            reasons.append(f"closure.reconciliation-failed:{type(exc).__name__}")
            record["reason_codes"] = reasons
        reconciled.append(record)
    return reconciled


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
    requests: tuple[IssueClosureRequest, ...],
    transport: Transport,
) -> list[dict[str, object]]:
    """Run the live governed closure batch for trusted caller requests.

    ``requests`` must be ``IssueClosureRequest`` objects the trusted host
    caller built from owner decisions and independent QA evidence it
    reacquired from trusted sources. This function accepts no manifest,
    file, or CLI input: see the module trust-boundary note. The batch
    itself — admission, verification, dispatch, readback, continuation past
    blocked items — is entirely ``run_closure_batch``; this function only
    supplies it with the production reader and writer, then runs the
    requirement 3 reconciliation phase for freshly closed items only.
    A reconciliation failure on one item never stops the next item, and
    never un-verifies its closure.
    """
    if type(requests) is not tuple:
        raise TypeError("closure requests must be an exact tuple")
    reader = GitHubClosureReader(transport)
    writer = GitHubClosureWriter(transport)
    outcomes = run_closure_batch(
        requests,
        reader=reader,
        writer=writer,
    )
    return _reconcile_closed_items(
        requests=requests, outcomes=outcomes, reader=reader, writer=writer
    )


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
    # The merge-module observation is evidence, not a host-authenticated
    # receipt. A fresh PR readback must corroborate every observable binding.
    if raw.get("merged_by") is not None:
        actor = raw["merged_by"]
        if type(actor) is not dict or actor.get("login") != observation.observed_actor_id:
            raise ValueError("merge-observation.actor-mismatch")
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
    requests: tuple[IssueClosureRequest, ...],
    transport: Transport,
) -> list[dict[str, object]]:
    """Consume the existing merge observation and governed closure batch.

    Fresh GitHub merged-PR readback binds the observation to the exact
    issue. Closure is still refused unless the *independent* owner decision,
    satisfaction, QA, and fresh issue admission permit it. There is no merge
    or issue-write authority in the observation.
    """
    if type(requests) is not tuple:
        raise TypeError("closure requests must be an exact tuple")
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
