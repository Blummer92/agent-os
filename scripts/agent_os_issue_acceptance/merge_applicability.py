"""Read-only merge-specific dispatch applicability consumer (#2340, #3463).

Reacquires the owner-authored authorization record, exact live PR, changed
files, checks, reviews and complete GraphQL review-thread evidence. Only schema
1.2 records are dispatchable; historical 1.1 records remain readable but are
not current merge authority. The canonical merge evaluator decides using the
native binding, not a task-planning approval triple. This module performs no
merge. A host still must independently recheck the exact head and receipt
immediately before any separately authorized mutation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from . import merge_admission_actions as admission
from .checks.forbidden_paths import _matches as forbidden_path_matches
from .path_contract import normalize_declared_path
from .lifecycle_mutation_authorization import (
    LifecycleOwnerDecision,
    produce_lifecycle_mutation_authorization,
)
from .lifecycle_mutation_guard import LifecycleStateSnapshot
from .merge_authorization import (
    MergeAuthorizationRecord,
    MERGE_AUTHORIZATION_CURRENT_SCHEMA_VERSION,
    MergeCheckEvidence,
    MergeReviewEvidence,
    PullRequestMergeEvidence,
    changed_scope_fingerprint,
    evaluate_merge_authorization_applicability,
    pr_metadata_fingerprint,
)
from .merge_authorization_source import (
    MergeAuthorizationCommentSnapshot,
    MergeAuthorizationSourceSnapshot,
    MergeAuthorizationSourceTransport,
    github_comment_snapshot,
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

class _GitHubCommentSource:
    """Bounded GitHub PR comments for the trusted merge-authorization reader."""

    def __init__(self, repo: Any, owner_login: str):
        self.repo = repo
        self.owner_login = owner_login

    def _read(self, repository: str, pr_number: int, snapshot_cls: Any, comment_cls: Any) -> Any:
        # Single shared extraction point (merge_authorization_source.
        # github_comment_snapshot) so app-performance evidence is
        # captured identically here and in merge admission.
        comments = [
            github_comment_snapshot(comment)
            for comment in self.repo.get_issue(pr_number).get_comments()
        ]
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




# S2 human-origin trust boundary (issue #3463, owner decision 2026-10-25).
# The runtime human approval card is the ONLY accepted human-origin
# attestation for a production merge. Repository evaluation never observes
# that card: the card is invisible to the agent, its tool result carries
# only an approved/declined status with no attestation id, signature, or
# parameter hash, and no standing merge grant exists. A dispatch receipt
# therefore always reports human-origin attestation as required-but-not-
# observed, and never emits merge_authorized=true on record evidence
# alone. An executor may merge only when BOTH hold: (a) this receipt
# shows content admission passed (status awaiting-human-attestation,
# dispatch_checks_passed true, canonical result applicable), and (b) a
# fresh per-call approval card was tapped for exactly the binding
# parameters below, with no standing grant and a re-prompt on any
# parameter change. A GitHub comment, owner-login match, PAT/OAuth
# authorship, or agent-written declaration is never a substitute.
HUMAN_ORIGIN_MECHANISM = "runtime-human-approval-card"
HUMAN_ORIGIN_REASON = "human-origin-attestation-required"


def _human_origin_attestation(binding: dict[str, object] | None) -> dict[str, object]:
    return {
        "status": "required-not-observed",
        "mechanism": HUMAN_ORIGIN_MECHANISM,
        "binding": binding,
        "observed_by_repository": False,
    }


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
             admission_receipt: dict[str, object] | None = None,
             status: str = "blocked",
             merge_authorized: bool = False,
             canonical_applicability_evaluated: bool = False,
             canonical_applicability_result: dict[str, object] | None = None,
             authorization_expires_at: str | None = None,
             human_origin_binding: dict[str, object] | None = None) -> dict[str, object]:
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
        "status": status,
        "merge_authorized": merge_authorized,
        "human_origin_attestation": _human_origin_attestation(human_origin_binding),
        "canonical_applicability_evaluated": canonical_applicability_evaluated,
        "canonical_applicability_result": canonical_applicability_result,
        "authorization_expires_at": authorization_expires_at,
        "issue_closure_authorized": False,
        "workflow_authorized": False,
        "production_authorized": False,
        "external_system_write_authorized": False,
        "side_effects_performed": False,
    }
    ident = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    payload["receipt_id"] = "merge-dispatch-applicability:" + ident
    return payload


_GITHUB_ACTIONS_BOT_ID = 41898282


def _status_identity(status: Any) -> str | None:
    """Identify the actual commit-status author, never the saved binding."""
    creator = getattr(status, "creator", None)
    if creator is None:
        return None
    login = getattr(creator, "login", None)
    user_id = getattr(creator, "id", None)
    if login == "github-actions[bot]" and user_id == _GITHUB_ACTIONS_BOT_ID:
        return "github-actions"
    if not isinstance(login, str) or not login:
        return None
    if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
        return None
    return login


def _check_run_identity(run: Any) -> str | None:
    app = getattr(run, "app", None)
    slug = getattr(app, "slug", None) if app is not None else None
    app_id = getattr(app, "id", None) if app is not None else None
    if not isinstance(slug, str) or not slug:
        return None
    if not isinstance(app_id, int) or isinstance(app_id, bool) or app_id <= 0:
        return None
    if slug == "github-actions" and app_id != 15368:
        return None
    return slug


def _latest_evidence(commit: Any) -> dict[str, tuple[str, str | None, bool]]:
    """Use latest-per-context status and check-run records, with live origin.

    GitHub's commit-status listing is newest-first; explicit status IDs
    govern ordering when available. Neither historical failures nor historical
    successes can mask the latest status. A check run and commit status sharing
    a name must independently succeed with the same verified publisher.
    The final boolean records whether a real commit status was observed.
    """
    runs: dict[str, tuple[int | None, str, str | None]] = {}
    statuses: dict[str, tuple[int | None, str, str | None]] = {}
    for run in commit.get_check_runs():
        context = getattr(run, "name", None)
        if not isinstance(context, str) or not context:
            raise ValueError("check-run context unavailable")
        raw_id = getattr(run, "id", None)
        run_id = raw_id if type(raw_id) is int and raw_id > 0 else None
        conclusion = getattr(run, "conclusion", None)
        state = _CHECK_RUN_STATES.get(
            conclusion, "pending" if conclusion is None else "unknown"
        )
        prior = runs.get(context)
        if prior is None or (
            run_id is not None and prior[0] is not None and run_id > prior[0]
        ):
            runs[context] = (run_id, state, _check_run_identity(run))
        elif run_id is None or prior[0] is None or run_id == prior[0]:
            runs[context] = (run_id, "unknown", None)

    for status in commit.get_statuses():
        context = getattr(status, "context", None)
        if not isinstance(context, str) or not context:
            raise ValueError("commit-status context unavailable")
        raw_id = getattr(status, "id", None)
        status_id = raw_id if type(raw_id) is int and raw_id > 0 else None
        state = _COMMIT_STATUS_STATES.get(getattr(status, "state", None), "unknown")
        prior = statuses.get(context)
        if prior is None or (
            status_id is not None and prior[0] is not None and status_id > prior[0]
        ):
            statuses[context] = (status_id, state, _status_identity(status))
        # No IDs: the GitHub API orders statuses newest first, so retain first.
        elif status_id is not None and prior[0] is None:
            # Cannot reliably compare an identified status with an unidentified one.
            statuses[context] = (None, "unknown", None)

    result: dict[str, tuple[str, str | None, bool]] = {}
    for context in set(runs) | set(statuses):
        run = runs.get(context)
        status = statuses.get(context)
        if run is not None and status is not None:
            if (
                run[1] == status[1] == "success"
                and run[2] is not None and run[2] == status[2]
            ):
                result[context] = ("success", run[2], True)
            else:
                result[context] = ("unknown", None, True)
        elif run is not None:
            result[context] = (run[1], run[2], False)
        else:
            assert status is not None
            result[context] = (status[1], status[2], True)
    return result


def _live_check_states(commit: Any) -> dict[str, str]:
    """Compatibility projection of the latest verified evidence states."""
    return {context: evidence[0] for context, evidence in _latest_evidence(commit)}


_REVIEW_THREAD_QUERY = """
query ($owner: String!, $name: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $cursor) {
        nodes { isResolved }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""


def _unresolved_review_threads(github_client: Any, repository: str, number: int) -> int:
    """Count every unresolved PR review thread from authenticated GraphQL pages.

    A partial, malformed or inaccessible result is never evidence of zero.
    GitHub's REST reviews/comments do not expose review-thread resolution.
    """
    owner, name = repository.split("/", 1)
    requester = github_client.requester
    cursor: str | None = None
    seen: set[str] = set()
    unresolved = 0
    for _ in range(50):
        _, response = requester.graphql_query(
            _REVIEW_THREAD_QUERY,
            {"owner": owner, "name": name, "number": number, "cursor": cursor},
        )
        if not isinstance(response, dict) or response.get("errors"):
            raise ValueError("review threads unavailable")
        item = response.get("data", {}).get("repository", {}).get("pullRequest", {})
        page = item.get("reviewThreads") if isinstance(item, dict) else None
        if not isinstance(page, dict) or not isinstance(page.get("nodes"), list):
            raise ValueError("review threads incomplete")
        nodes = page["nodes"]
        if len(nodes) > 100 or any(
            not isinstance(node, dict) or type(node.get("isResolved")) is not bool
            for node in nodes
        ):
            raise ValueError("review threads malformed")
        unresolved += sum(not node["isResolved"] for node in nodes)
        info = page.get("pageInfo")
        if not isinstance(info, dict) or type(info.get("hasNextPage")) is not bool:
            raise ValueError("review-thread pagination unavailable")
        if not info["hasNextPage"]:
            return unresolved
        next_cursor = info.get("endCursor")
        if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen:
            raise ValueError("review-thread cursor unavailable")
        seen.add(next_cursor)
        cursor = next_cursor
    raise ValueError("review-thread bounds exceeded")


def evaluate_merge_dispatch_applicability(
    transport: object, *,
    repository: str,
    github_client: Any,
    evaluated_at: str | None = None,
) -> dict[str, object]:
    """Full dispatch-time verification. Never authorizes a merge.

    Content admission and human-origin attestation are separate verdicts:
    this function can establish the first and never the second. A
    content-passing result therefore has status
    "awaiting-human-attestation" with merge_authorized False, never
    "applicable" with merge_authorized True.
    """
    now_text = evaluated_at or admission._utcnow()
    now = admission._parse_timestamp(now_text)
    base_kwargs = dict(
        repository=repository, pr_number=None, logical_trigger_id=None,
        expected_head_sha=None, expected_method=None, observed_head_sha=None,
        observed_base_sha=None, evaluated_at=now_text, authorization_id=None,
        authorization_revision=None, approval_id=None, approval_revision=None,
        dispatch_checks_passed=False, verified=[], reason_codes=[],
        missing_interfaces=[], lifecycle_mutation_authorization=None,
        lifecycle_snapshot_notes=[], human_origin_binding=None,
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
                           authorization_revision=record.authorization_revision,
                           authorization_expires_at=record.expires_at,
                           human_origin_binding={
                               "repository": repository,
                               "pr_number": pr.number,
                               "head_sha": base_kwargs["expected_head_sha"],
                               "base_branch": pr.base.ref,
                               "base_sha": pr.base.sha,
                               "merge_method": base_kwargs["expected_method"],
                               "authorization_id": record.authorization_id,
                               "authorization_revision": record.authorization_revision,
                               "changed_scope_fingerprint": record.binding.changed_scope_fingerprint,
                           })

        # Only native v1.2 merge records may authorize new dispatches.
        # Historical 1.1 records remain readable, but their planning-named
        # approvals cannot be promoted into current merge authority.
        if record.schema_version != MERGE_AUTHORIZATION_CURRENT_SCHEMA_VERSION:
            return _receipt(**{**base_kwargs, "reason_codes": ["version.unsupported-for-dispatch"]})
        if record.authorizer_id.casefold() != repo.owner.login.casefold():
            return _receipt(**{**base_kwargs, "reason_codes": ["authorization.owner-provenance-mismatch"]})
        verified.append("native-merge-record")

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
        # The fingerprint only proves the scope did not drift; it does not
        # establish that the *authorized* scope was safe in the first place.
        # Reuse the same forbidden-path matcher as Issue Acceptance.
        try:
            if any(
                forbidden_path_matches(normalize_declared_path(path), pattern)
                for path in paths for pattern in record.binding.forbidden_paths
            ):
                scope_failures.append("contract.forbidden-paths-changed")
        except (TypeError, ValueError):
            scope_failures.append("contract.forbidden-paths-changed")
        if scope_failures:
            return _receipt(**{**base_kwargs, "reason_codes": scope_failures})
        verified.append("file-scope")

        # Live checks for the exact head.
        from .merge_authorization import (
            AUTHORITATIVE_AGGREGATE_CONTEXT,
            AUTHORITATIVE_AGGREGATE_APP_IDENTITY,
        )
        live_checks = _latest_evidence(repo.get_commit(head))
        check_failures: list[str] = []
        required_contexts = [
            required.context for required in record.binding.required_check_evidence
        ]
        if required_contexts.count(AUTHORITATIVE_AGGREGATE_CONTEXT) != 1:
            check_failures.append("checks.authoritative-aggregate-missing")
        for required in record.binding.required_check_evidence:
            observation = live_checks.get(required.context)
            if observation is None:
                check_failures.append("checks.missing")
                continue
            state, publisher, is_commit_status = observation
            if state != "success":
                check_failures.append("checks.changed")
            elif publisher is None or publisher != required.app_identity:
                check_failures.append("checks.publisher-unverifiable")
            if required.context == AUTHORITATIVE_AGGREGATE_CONTEXT and (
                not is_commit_status
                or publisher != AUTHORITATIVE_AGGREGATE_APP_IDENTITY
            ):
                check_failures.append("checks.authoritative-aggregate-unverifiable")
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
        # Only the complete GraphQL review-thread connection can establish
        # that there are no unresolved conversations. A REST review list
        # alone cannot establish thread resolution.
        try:
            unresolved_threads = _unresolved_review_threads(github_client, repository, pr.number)
        except Exception:
            return _receipt(**{**base_kwargs, "reason_codes": ["review.threads-unverifiable"]})
        if unresolved_threads:
            return _receipt(**{**base_kwargs, "reason_codes": ["review.unresolved"]})
        if unresolved_threads != review_evidence.unresolved_conversation_count:
            return _receipt(**{**base_kwargs, "reason_codes": ["review.changed"]})
        verified.append("reviews")
        verified.append("review-threads")

        # Lifecycle-mutation admission binding the owner's instruction to the head.
        actor = transport.get("actor") if isinstance(transport, dict) else None
        if not isinstance(actor, str) or not actor:
            return _receipt(**{**base_kwargs, "reason_codes": ["lifecycle.actor-unknown"]})
        if actor.casefold() != repo.owner.login.casefold():
            return _receipt(**{**base_kwargs, "reason_codes": ["lifecycle.actor-not-owner"]})
        notes = [
            f"unresolved_threads={unresolved_threads}: verified through complete GitHub GraphQL review-thread readback.",
        ]
        try:
            decision = LifecycleOwnerDecision(
                repository=repository,
                issue_number=None,
                requested_mutations=("merge",),
                # The current owner-authored merge authorization is the
                # decision provenance, not an unauthenticated actor field.
                authorizer_id=repo.owner.login,
                decision_id=record.decision_id,
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
                unresolved_threads=unresolved_threads,
                lifecycle_labels=tuple(sorted(label.name for label in pr.get_labels())),
                observed_revision=head,
            )
            lifecycle_authorization = produce_lifecycle_mutation_authorization(decision, snapshot)
        except Exception:
            return _receipt(**{**base_kwargs, "reason_codes": ["lifecycle.admission-failed"]})
        verified.append("lifecycle-admission")

        # Compare live PR facts directly with the merge-specific record.
        # No task-planning ApprovalRecord, applicability result, execution
        # projection or reconstructed MergeProposal participates in dispatch.
        live_check_evidence = tuple(
            MergeCheckEvidence(
                context=required.context,
                app_identity=live_checks[required.context][1],
                tested_sha=head,
                evidence_id="",
                state=live_checks[required.context][0],
            )
            for required in record.binding.required_check_evidence
        )
        pr_evidence = PullRequestMergeEvidence(
            repository=repository,
            pull_request_number=pr.number,
            head_sha=head,
            base_branch=pr.base.ref,
            base_sha_or_evidence_id=pr.base.sha,
            draft=pr.draft,
            ready_for_review=not pr.draft,
            proposed_merge_method=base.get("expected_method"),
            changed_scope_fingerprint=live_scope,
            allowed_files=record.binding.allowed_files,
            forbidden_paths=record.binding.forbidden_paths,
            required_tests=record.binding.required_tests,
            required_checks=live_check_evidence,
            review_evidence=MergeReviewEvidence(
                blocking_review_present=blocking,
                unresolved_conversation_count=unresolved_threads,
                exact_head_reviewed=approved_at_head,
            ),
            evidence_id="",
            pr_title=pr.title or "",
            pr_body=pr.body or "",
            pr_metadata_sha256=pr_metadata_fingerprint(pr.title or "", pr.body or ""),
            closure_admissions=(),
        )
        canonical = evaluate_merge_authorization_applicability(
            record, pr_evidence, evaluated_at=now_text,
        )
        canonical_result = {
            "status": canonical.status,
            "authorization_id": canonical.authorization_id,
            "authorization_revision": canonical.authorization_revision,
            "current_pull_request_evidence_id": canonical.current_pull_request_evidence_id,
            "changed_bindings": list(canonical.changed_bindings),
            "reason_codes": list(canonical.reason_codes),
            "merge_authorized": canonical.merge_authorized,
        }
        verified.append("canonical-applicability")
        if canonical.status == "applicable" and canonical.merge_authorized:
            # Content admission passed. This is NOT merge authorization:
            # the merge-authorization record is an auditable representation
            # only, and human-origin attestation (a fresh runtime approval
            # card tap for exactly human_origin_binding) is still required
            # at the executor. No repository evaluation can supply it, so
            # merge_authorized stays False here by construction.
            return _receipt(
                **{**base_kwargs,
                   "dispatch_checks_passed": True,
                   "verified": verified,
                   "reason_codes": [HUMAN_ORIGIN_REASON],
                   "missing_interfaces": [],
                   "lifecycle_mutation_authorization": lifecycle_authorization.to_dict(),
                   "lifecycle_snapshot_notes": notes,
                   "status": "awaiting-human-attestation",
                   "merge_authorized": False,
                   "canonical_applicability_evaluated": True,
                   "canonical_applicability_result": canonical_result},
            )
        return _receipt(
            **{**base_kwargs,
               "dispatch_checks_passed": True,
               "verified": verified,
               "reason_codes": list(canonical.reason_codes),
               "missing_interfaces": [],
               "lifecycle_mutation_authorization": lifecycle_authorization.to_dict(),
               "lifecycle_snapshot_notes": notes,
               "canonical_applicability_evaluated": True,
               "canonical_applicability_result": canonical_result},
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
