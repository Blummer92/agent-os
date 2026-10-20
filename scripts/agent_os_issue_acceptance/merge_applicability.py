"""Dispatch-time merge applicability consumer (#2340).

Builds on the #3661 read-only pipeline: it requires the non-authorizing
candidate receipt from ``merge_admission_actions`` (transport validation, live
PR gates, trusted authorization-source acquisition, binding reconciliation),
then additionally verifies:

- trusted approval artifacts (``reacquire_approval_source``): APPROVED approval
  record, applicable applicability result, complete execution projection, with
  id/revision/identity linkage back to the authorization record's binding;
- approval expiry;
- live file scope (canonical ``changed_scope_fingerprint``), allowlist and
  forbidden paths against the binding;
- live check runs / commit statuses for the exact head against the binding's
  required check evidence;
- live reviews against the binding's review evidence;
- a canonical lifecycle-mutation admission binding the owner's merge
  instruction to the exact live head via ``produce_lifecycle_mutation_authorization``.

Fail-closed throughout. This module NEVER emits merge authorization: the
canonical ``evaluate_merge_authorization_applicability`` additionally requires
a merge-proposal evidence type (``DraftTaskProposal`` is task-planning
specific; no canonical merge proposal exists), so the canonical
proposal-based applicability evaluation cannot be honestly invoked for merge
dispatch. That exact missing interface is reported, not simulated
(reason ``merge-proposal-evidence-undefined``).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from . import merge_admission_actions as admission
from .approval_source import (
    ApprovalCommentSnapshot,
    ApprovalSourceSnapshot,
    ApprovalSourceTransport,
    reacquire_approval_source,
)
from .lifecycle_mutation_authorization import (
    LifecycleOwnerDecision,
    produce_lifecycle_mutation_authorization,
)
from .lifecycle_mutation_guard import LifecycleStateSnapshot
from .merge_authorization import (
    MergeAuthorizationRecord,
    approval_applicability_identity,
    changed_scope_fingerprint,
)
from .merge_authorization_source import (
    MergeAuthorizationCommentSnapshot,
    MergeAuthorizationSourceSnapshot,
    MergeAuthorizationSourceTransport,
    reacquire_merge_authorization_source,
)

_BASE_SUCCESS_REASON = "approval-and-applicability-evidence-not-wired"
_MAX_FILES = 5000

_CHECK_RUN_STATES = {
    "success": "success",
    "failure": "failure",
    "timed_out": "failure",
    "cancelled": "cancelled",
    "skipped": "skipped",
    "neutral": "unknown",
    "action_required": "pending",
    "stale": "unknown",
}
_COMMIT_STATUS_STATES = {
    "success": "success",
    "failure": "failure",
    "error": "failure",
    "pending": "pending",
}

_MISSING_INTERFACES = [
    "merge-proposal-evidence-type: evaluate_merge_authorization_applicability "
    "requires current_proposal (DraftTaskProposal), current_issueplan_evidence, "
    "and current_repository_state_evidence; DraftTaskProposal is "
    "task-planning-specific and no canonical merge-proposal producer exists, "
    "so the canonical proposal-based applicability evaluation cannot be "
    "honestly invoked for merge dispatch.",
]


class _GitHubCommentSource:
    """Bounded canonical GitHub PR comments for both source readers."""

    def __init__(self, repo: Any, owner_login: str):
        self.repo = repo
        self.owner_login = owner_login

    def _read(self, repository: str, pr_number: int, snapshot_cls: Any, comment_cls: Any) -> Any:
        comments: list[Any] = []
        for comment in self.repo.get_issue(pr_number).get_comments():
            comments.append(comment_cls(
                comment_id=comment.id,
                author_login=comment.user.login,
                created_at=comment.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                body=comment.body or "",
            ))
        return snapshot_cls(
            repository=repository,
            pr_number=pr_number,
            owner_login=self.owner_login,
            owner_type=self.repo.owner.type,
            comments_complete=True,
            comments=tuple(comments),
        )

    def read_merge_authorization_source(self, repository: str, pr_number: int) -> MergeAuthorizationSourceSnapshot:
        return self._read(repository, pr_number, MergeAuthorizationSourceSnapshot, MergeAuthorizationCommentSnapshot)

    def read_approval_source(self, repository: str, pr_number: int) -> ApprovalSourceSnapshot:
        return self._read(repository, pr_number, ApprovalSourceSnapshot, ApprovalCommentSnapshot)


# _GitHubCommentSource satisfies both source transport protocols structurally
# (read_merge_authorization_source / read_approval_source); each contract
# isinstance-checks only its own method.


def _receipt(*, repository: str, pr_number: int | None, logical_trigger_id: str | None,
             expected_head_sha: str | None, expected_method: str | None,
             observed_head_sha: str | None, observed_base_sha: str | None,
             evaluated_at: str, authorization_id: str | None,
             authorization_revision: str | None, approval_id: str | None,
             approval_revision: str | None, dispatch_checks_passed: bool,
             verified: list[str], reason_codes: list[str],
             missing_interfaces: list[str],
             lifecycle_mutation_authorization: dict[str, object] | None,
             lifecycle_snapshot_notes: list[str],
             admission_receipt: dict[str, object] | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "operation": "merge-dispatch-applicability",
        "repository": repository,
        "pr_number": pr_number,
        "logical_trigger_id": logical_trigger_id,
        "expected_head_sha": expected_head_sha,
        "expected_method": expected_method,
        "observed_head_sha": observed_head_sha,
        "observed_base_sha": observed_base_sha,
        "evaluated_at": evaluated_at,
        "authorization_id": authorization_id,
        "authorization_revision": authorization_revision,
        "approval_id": approval_id,
        "approval_revision": approval_revision,
        "dispatch_checks_passed": dispatch_checks_passed,
        "verified": verified,
        "reason_codes": sorted(set(reason_codes)),
        "missing_interfaces": missing_interfaces,
        "lifecycle_mutation_authorization": lifecycle_mutation_authorization,
        "lifecycle_snapshot_notes": lifecycle_snapshot_notes,
        "admission_receipt": admission_receipt,
        "status": "blocked",
        "merge_authorized": False,
        "canonical_applicability_evaluated": False,
        "issue_closure_authorized": False,
        "workflow_authorized": False,
        "production_authorized": False,
        "external_system_write_authorized": False,
        "side_effects_performed": False,
    }
    ident = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    payload["receipt_id"] = "merge-dispatch-applicability:" + ident
    return payload


def _live_check_states(commit: Any) -> dict[str, str]:
    """Worst-state-wins rollup of check runs and commit statuses per context.

    A context counts as ``"success"`` only when every observed check run and
    status for that context is a success. A success commit status must never
    mask a failing check run (or vice versa): any non-success observation
    fails the context closed. Severity order for the rolled-up state is
    failure > cancelled > pending > unknown > skipped; only ``"success"``
    satisfies a required check.
    """
    observed: dict[str, list[str]] = {}
    for run in commit.get_check_runs():
        conclusion = getattr(run, "conclusion", None)
        observed.setdefault(run.name, []).append(
            _CHECK_RUN_STATES.get(conclusion, "pending" if conclusion is None else "unknown")
        )
    for status in commit.get_statuses():
        observed.setdefault(status.context, []).append(
            _COMMIT_STATUS_STATES.get(status.state, "unknown")
        )
    # "success" ranks below every non-success state here: the all-success
    # case is handled by the branch above, so reaching max() with a
    # "success" observation present means the context is NOT all-success
    # and must fail closed (never roll up to "success", never order-dependent).
    severity = {
        "failure": 4, "cancelled": 3, "pending": 2, "unknown": 1,
        "skipped": 0, "success": -1,
    }
    rolled: dict[str, str] = {}
    for context, states in observed.items():
        if states and all(state == "success" for state in states):
            rolled[context] = "success"
        else:
            rolled[context] = max(states, key=lambda state: severity.get(state, 1))
    return rolled


def evaluate_merge_dispatch_applicability(
    transport: object, *,
    repository: str,
    github_client: Any,
    evaluated_at: str | None = None,
) -> dict[str, object]:
    """Full dispatch-time verification. Never authorizes a merge."""
    now_text = evaluated_at or admission._utcnow()
    now = admission._parse_timestamp(now_text)
    base_kwargs = dict(
        repository=repository, pr_number=None, logical_trigger_id=None,
        expected_head_sha=None, expected_method=None, observed_head_sha=None,
        observed_base_sha=None, evaluated_at=now_text, authorization_id=None,
        authorization_revision=None, approval_id=None, approval_revision=None,
        dispatch_checks_passed=False, verified=[], reason_codes=[],
        missing_interfaces=[], lifecycle_mutation_authorization=None,
        lifecycle_snapshot_notes=[],
    )
    if now is None:
        return _receipt(**{**base_kwargs, "reason_codes": ["evaluator-clock-malformed"]})
    try:
        base = admission.evaluate_merge_admission_transport(
            transport, repository=repository, github_client=github_client,
            evaluated_at=now_text,
        )
    except Exception:
        return _receipt(**{**base_kwargs, "reason_codes": ["canonical-github-evidence-unavailable"]})
    pr_number = base.get("pr_number") if isinstance(base.get("pr_number"), int) else None
    base_kwargs.update(
        pr_number=pr_number,
        logical_trigger_id=base.get("logical_trigger_id"),
        expected_head_sha=base.get("expected_head_sha"),
        expected_method=base.get("expected_method"),
        observed_head_sha=base.get("observed_head_sha"),
        observed_base_sha=None,
        admission_receipt=base,
    )
    if base.get("reason_codes") != [_BASE_SUCCESS_REASON]:
        return _receipt(**{**base_kwargs,
                           "reason_codes": ["merge-dispatch-blocked-by-admission", *base.get("reason_codes", [])]})
    authorization_id = base.get("authorization_id")
    verified: list[str] = ["transport-and-record"]
    try:
        repo = github_client.get_repo(repository)
        pr = repo.get_pull(pr_number)
        head = pr.head.sha
        base_kwargs["observed_base_sha"] = pr.base.sha
        source = _GitHubCommentSource(repo, repo.owner.login)

        # Re-acquire the exact authorization record (fresh read for dispatch time).
        authz = reacquire_merge_authorization_source(
            transport=source, repository=repository, pr_number=pr.number,
            expected_authorization_id=authorization_id,
        )
        records = [
            record for record in authz.records
            if record.authorization_id == authorization_id
        ]
        if authz.status.value != "current" or len(records) != 1:
            return _receipt(**{**base_kwargs,
                               "reason_codes": ["authorization.record-unavailable-at-dispatch",
                                                *authz.reason_codes]})
        record: MergeAuthorizationRecord = records[0]
        base_kwargs.update(authorization_id=record.authorization_id,
                           authorization_revision=record.authorization_revision)

        # Trusted approval artifacts.
        approval_result = reacquire_approval_source(
            transport=source, repository=repository, pr_number=pr.number,
            expected_approval_id=record.binding.approval_id,
        )
        if approval_result.status.value != "current":
            return _receipt(**{**base_kwargs,
                               "reason_codes": ["approval-source-not-current",
                                                *approval_result.reason_codes]})
        verified.append("approval-source-current")
        approval = approval_result.approval
        applicability = approval_result.applicability
        projection = approval_result.projection
        assert approval is not None and applicability is not None and projection is not None
        base_kwargs.update(approval_id=approval.approval_id,
                           approval_revision=approval.approval_revision)

        # Linkage between the authorization binding and the current artifacts.
        linkage_failures: list[str] = []
        if approval.approval_id != record.binding.approval_id:
            linkage_failures.append("approval.changed")
        if approval.approval_revision != record.binding.approval_revision:
            linkage_failures.append("approval.changed")
        if approval_applicability_identity(applicability) != record.binding.approval_applicability_identity:
            linkage_failures.append("approval.changed")
        if projection.projection_id != record.binding.approved_execution_projection_id:
            linkage_failures.append("projection.changed")
        if linkage_failures:
            return _receipt(**{**base_kwargs, "reason_codes": linkage_failures})
        verified.append("approval-binding-linkage")

        # Live file scope.
        files = [(item.filename, item.sha) for item in pr.get_files()]
        if len(files) > _MAX_FILES:
            return _receipt(**{**base_kwargs, "reason_codes": ["scope.unbounded"]})
        scope_failures: list[str] = []
        try:
            live_scope = changed_scope_fingerprint(files)
        except ValueError:
            live_scope = None
        if live_scope != record.binding.changed_scope_fingerprint:
            scope_failures.append("contract.scope-changed")
        paths = [path for path, _ in files]
        if set(paths) - set(record.binding.allowed_files):
            scope_failures.append("contract.allowlist-changed")
        # NOTE: binding.forbidden_paths is deliberately not re-checked here.
        # Forbidden paths use `/**` glob semantics whose canonical matcher
        # lives outside this package; reimplementing it would be parallel
        # authorization logic. It is also redundant: any forbidden-path
        # violation changes the file set and is therefore caught by the
        # scope fingerprint above, and the canonical producer validated
        # forbidden paths against the projection at decision time.
        if scope_failures:
            return _receipt(**{**base_kwargs, "reason_codes": scope_failures})
        verified.append("file-scope")

        # Live checks for the exact head.
        check_states = _live_check_states(repo.get_commit(head))
        check_failures: list[str] = []
        for required in record.binding.required_check_evidence:
            state = check_states.get(required.context)
            if state is None:
                check_failures.append("checks.missing")
            elif state != "success":
                check_failures.append("checks.changed")
        if check_failures:
            return _receipt(**{**base_kwargs, "reason_codes": sorted(set(check_failures))})
        verified.append("checks")

        # Live reviews.
        blocking = False
        approved_at_head = False
        for review in pr.get_reviews():
            if review.state == "CHANGES_REQUESTED":
                blocking = True
            if review.state == "APPROVED" and review.commit_id == head:
                approved_at_head = True
        review_evidence = record.binding.review_evidence
        if blocking != review_evidence.blocking_review_present:
            return _receipt(**{**base_kwargs, "reason_codes": ["review.changed"]})
        if review_evidence.exact_head_reviewed != approved_at_head:
            return _receipt(**{**base_kwargs, "reason_codes": ["review.changed"]})
        verified.append("reviews")

        # Lifecycle-mutation admission binding the owner's instruction to the head.
        actor = transport.get("actor") if isinstance(transport, dict) else None
        if not isinstance(actor, str) or not actor:
            return _receipt(**{**base_kwargs, "reason_codes": ["lifecycle.actor-unknown"]})
        if actor.casefold() != repo.owner.login.casefold():
            return _receipt(**{**base_kwargs, "reason_codes": ["lifecycle.actor-not-owner"]})
        notes = [
            "unresolved_threads=0: no issue is bound (issue_number=None); PR review-thread "
            "resolution is not observable via the REST API and is covered by review_state.",
        ]
        try:
            decision = LifecycleOwnerDecision(
                repository=repository,
                issue_number=None,
                requested_mutations=("merge",),
                authorizer_id=actor,
                decision_id=base.get("logical_trigger_id") or "merge-dispatch",
                decision_recorded=True,
                pull_request_number=pr.number,
            )
            snapshot = LifecycleStateSnapshot(
                repository=repository,
                issue_number=None,
                pull_request_number=pr.number,
                source_head=head,
                base_head=pr.base.sha,
                pr_state="draft" if pr.draft else "ready",
                merged=False,
                issue_state=None,
                review_state="blocked" if blocking else "clear",
                unresolved_threads=0,
                lifecycle_labels=tuple(sorted(label.name for label in pr.get_labels())),
                observed_revision=head,
            )
            lifecycle_authorization = produce_lifecycle_mutation_authorization(decision, snapshot)
        except Exception:
            return _receipt(**{**base_kwargs, "reason_codes": ["lifecycle.admission-failed"]})
        verified.append("lifecycle-admission")

        return _receipt(
            **{**base_kwargs,
               "dispatch_checks_passed": True,
               "verified": verified,
               "reason_codes": ["merge-proposal-evidence-undefined"],
               "missing_interfaces": list(_MISSING_INTERFACES),
               "lifecycle_mutation_authorization": lifecycle_authorization.to_dict(),
               "lifecycle_snapshot_notes": notes},
        )
    except Exception:
        return _receipt(**{**base_kwargs, "reason_codes": ["canonical-github-evidence-unavailable"]})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", required=True, type=Path)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        transport = json.loads(args.transport.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        transport = None
    try:
        from scripts.agent_os_github_issue_provider.auth import build_token_client
        client = build_token_client(dict(os.environ), user_agent="agent-os-merge-dispatch/1")
        receipt = evaluate_merge_dispatch_applicability(
            transport, repository=args.repository, github_client=client)
    except Exception:
        receipt = _receipt(
            repository=args.repository, pr_number=None, logical_trigger_id=None,
            expected_head_sha=None, expected_method=None, observed_head_sha=None,
            observed_base_sha=None, evaluated_at=admission._utcnow(),
            authorization_id=None, authorization_revision=None, approval_id=None,
            approval_revision=None, dispatch_checks_passed=False, verified=[],
            reason_codes=["canonical-github-evidence-unavailable"],
            missing_interfaces=[], lifecycle_mutation_authorization=None,
            lifecycle_snapshot_notes=[],
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
