"""Authorizing merge-admission consumer (#3463).

Extends the read-only ingress pipeline in merge_admission_actions.py with the
trusted approval root and QA gates required before a host may dispatch a merge.

Trust model (fail-closed throughout):
- The merge authorization record is trusted only from the canonical
  conversation source (reacquire_merge_authorization_source): owner-authored,
  AUTHORIZED state, unexpired, binding matches live PR.
- The owner approval is trusted only from the canonical approval source
  (reacquire_approval_source): owner-authored, APPROVED state, unexpired, and
  its approval_id/approval_revision match the authorization binding.
- QA gates are read live: check runs + commit statuses for the exact head must
  show no failures ("missing QA" blocks); no CHANGES_REQUESTED reviews
  ("unresolved reviews" block); PR body/title closing keywords without a
  trusted lifecycle closure admission block ("unauthorized issue-closing
  references").
- The changed file scope is fingerprinted canonically and must match the
  authorization binding ("scope.changed" blocks).

Only when every gate passes does this module emit a dispatchable receipt with
merge_authorized=true. Every other outcome emits the standard non-authorizing
receipt with precise reason codes. This module never calls the GitHub merge
API; dispatch remains the host's responsibility under the host_dispatch_contract.

Note: this consumer verifies currentness of a decision-time authorization. It
does not re-run the planning-domain applicability evaluator
(evaluate_merge_authorization_applicability), which requires proposal,
issue-plan, and repository-state evidence that cannot be faithfully built from
PR reads; canonical_applicability_evaluated stays False in every receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .approval_records import ApprovalState
from .approval_source import (
    ApprovalCommentSnapshot,
    ApprovalSourceSnapshot,
    reacquire_approval_source,
)
from .merge_admission_actions import (
    _evaluate_record,
    _GitHubSource,
    _live_binding_values,
    _parse,
    _parse_timestamp,
    _receipt,
    _utcnow,
)
from .merge_authorization import (
    MergeAuthorizationRecord,
    MergeAuthorizationState,
    changed_scope_fingerprint,
)
from .merge_authorization_source import reacquire_merge_authorization_source

_CLOSING_KEYWORDS_RE = re.compile(
    r"\b(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)\s+#\d+",
    re.IGNORECASE,
)


class _GitHubApprovalSource:
    """Bounded canonical GitHub PR comments for approval records."""

    def __init__(self, repo: Any, owner_login: str):
        self.repo = repo
        self.owner_login = owner_login

    def read_approval_source(self, repository: str, pr_number: int):
        comments: list[ApprovalCommentSnapshot] = []
        for comment in self.repo.get_issue(pr_number).get_comments():
            comments.append(ApprovalCommentSnapshot(
                comment_id=comment.id,
                author_login=comment.user.login,
                created_at=comment.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                body=comment.body or "",
            ))
        return ApprovalSourceSnapshot(
            repository=repository,
            pr_number=pr_number,
            owner_login=self.owner_login,
            owner_type=self.repo.owner.type,
            comments_complete=True,
            comments=tuple(comments),
        )


def _read_check_runs(repo: Any, head: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (check_runs, statuses) for the exact head. Fail-closed on error."""
    check_runs: list[dict[str, object]] = []
    statuses: list[dict[str, object]] = []
    commit = repo.get_commit(head)
    for run in commit.get_check_runs():
        check_runs.append({
            "name": run.name,
            "status": run.status,
            "conclusion": run.conclusion,
        })
    for status in commit.get_statuses():
        statuses.append({
            "context": status.context,
            "state": status.state,
        })
    return check_runs, statuses


def _qa_reason_codes(check_runs: list[dict[str, Any]], statuses: list[dict[str, Any]]) -> list[str]:
    reasons: list[str] = []
    if not check_runs and not statuses:
        return ["qa.no-check-evidence"]
    for run in check_runs:
        if run.get("conclusion") == "failure":
            reasons.append("qa.checks-failing")
            break
    for status in statuses:
        if status.get("state") == "failure":
            reasons.append("qa.checks-failing")
            break
    return sorted(set(reasons))


def _review_reason_codes(pr: Any) -> list[str]:
    """Block on any CHANGES_REQUESTED review (unresolved blocking review)."""
    for review in pr.get_reviews():
        if review.state == "CHANGES_REQUESTED":
            return ["review.changes-requested"]
    return []


def _closure_reason_codes(title: str, body: str) -> list[str]:
    """Block unauthorized issue-closing references.

    Closing keywords in the PR title/body without a trusted lifecycle closure
    admission are unauthorized. No lifecycle admission source exists yet, so
    any closing keyword blocks (fail-closed).
    """
    text = f"{title or ''}\n{body or ''}"
    if _CLOSING_KEYWORDS_RE.search(text):
        return ["closure.unauthorized-reference"]
    return []


def _approval_reason_codes(
    approval: Any,
    auth_record: MergeAuthorizationRecord,
    now: datetime,
) -> list[str]:
    """Verify the trusted approval against the authorization binding."""
    reasons: list[str] = []
    if approval.state is not ApprovalState.APPROVED:
        reasons.append("approval.not-approved")
    if (
        approval.approval_id != auth_record.binding.approval_id
        or approval.approval_revision != auth_record.binding.approval_revision
    ):
        reasons.append("approval.mismatch")
    expires_at = _parse_timestamp(approval.expires_at)
    if expires_at is None or now >= expires_at:
        reasons.append("approval.expired")
    return sorted(set(reasons))


def evaluate_merge_admission_applicability(
    transport: object, *,
    repository: str,
    github_client: Any,
    evaluated_at: str | None = None,
) -> dict[str, object]:
    """Evaluate full merge-admission applicability. Emits authorizing receipt only on full pass."""
    parsed, reason = _parse(transport, repository)
    if parsed is None:
        return _receipt(transport, repository, [reason or "transport-malformed"])
    now_text = evaluated_at or _utcnow()
    now = _parse_timestamp(now_text)
    if now is None:
        return _receipt(parsed, repository, ["evaluator-clock-malformed"], evaluated_at=now_text)
    try:
        repo = github_client.get_repo(repository)
        pr = repo.get_pull(parsed["merge_admission_pr_number_or_none"])
        head = pr.head.sha
        body_sha = hashlib.sha256((pr.body or "").encode("utf-8")).hexdigest()
        failures: list[str] = []
        if pr.state != "open" or pr.draft or pr.merged:
            failures.append("pr-not-ready")
        if head != parsed["merge_admission_head_sha_or_none"]:
            failures.append("stale-head")
        if body_sha != parsed["merge_admission_body_sha256_or_none"]:
            failures.append("stale-body")
        if pr.mergeable is not True:
            failures.append("pr-mergeability-not-clean")
        if pr.base.ref != "main":
            failures.append("base-not-main")
        failures.extend(_closure_reason_codes(pr.title, pr.body))
        if failures:
            return _receipt(parsed, repository, failures, head=head, body_sha=body_sha,
                            evaluated_at=now_text)

        owner_login = repo.owner.login
        auth_source = reacquire_merge_authorization_source(
            transport=_GitHubSource(repo, owner_login),
            repository=repository,
            pr_number=pr.number,
        )
        if auth_source.status.value != "current":
            return _receipt(
                parsed, repository, list(auth_source.reason_codes),
                head=head, body_sha=body_sha, source_status=auth_source.status.value,
                source_comments=len(auth_source.source_comment_ids),
                record_count=len(auth_source.records), evaluated_at=now_text,
            )
        live = _live_binding_values(
            repository, pr.number, parsed["merge_admission_method_or_none"],
            head, pr.base.ref, pr.base.sha, pr.title or "", pr.body or "", pr.draft,
        )
        passing_record: MergeAuthorizationRecord | None = None
        candidate_records: list[dict[str, object]] = []
        for record in auth_source.records:
            ok, record_reasons, changed = _evaluate_record(record, live, now)
            candidate_records.append({
                "authorization_id": record.authorization_id,
                "authorization_revision": record.authorization_revision,
                "expires_at": record.expires_at,
                "fully_matching": ok,
                "changed_fields": changed,
                "reason_codes": record_reasons,
            })
            if ok and passing_record is None:
                passing_record = record
        if passing_record is None:
            reasons = {"authorization.binding-mismatch"}
            for candidate in candidate_records:
                reasons.update(candidate["reason_codes"])
            return _receipt(
                parsed, repository, sorted(reasons),
                head=head, body_sha=body_sha, source_status=auth_source.status.value,
                source_comments=len(auth_source.source_comment_ids),
                record_count=len(auth_source.records), evaluated_at=now_text,
                candidate_records=tuple(candidate_records),
            )

        approval_source = reacquire_approval_source(
            transport=_GitHubApprovalSource(repo, owner_login),
            repository=repository,
            pr_number=pr.number,
            expected_approval_id=passing_record.binding.approval_id,
        )
        if approval_source.status.value != "current":
            return _receipt(
                parsed, repository, list(approval_source.reason_codes),
                head=head, body_sha=body_sha, source_status=auth_source.status.value,
                source_comments=len(auth_source.source_comment_ids),
                record_count=len(auth_source.records), evaluated_at=now_text,
                authorization_id=passing_record.authorization_id,
                authorization_revision=passing_record.authorization_revision,
                authorization_expires_at=passing_record.expires_at,
                candidate_records=tuple(candidate_records),
            )
        approval = approval_source.records[0]
        approval_reasons = _approval_reason_codes(approval, passing_record, now)
        if approval_reasons:
            return _receipt(
                parsed, repository, approval_reasons,
                head=head, body_sha=body_sha, source_status=auth_source.status.value,
                source_comments=len(auth_source.source_comment_ids),
                record_count=len(auth_source.records), evaluated_at=now_text,
                authorization_id=passing_record.authorization_id,
                authorization_revision=passing_record.authorization_revision,
                authorization_expires_at=passing_record.expires_at,
                candidate_records=tuple(candidate_records),
            )

        try:
            check_runs, statuses = _read_check_runs(repo, head)
        except Exception:
            return _receipt(
                parsed, repository, ["qa.evidence-unavailable"],
                head=head, body_sha=body_sha, evaluated_at=now_text,
                authorization_id=passing_record.authorization_id,
                authorization_revision=passing_record.authorization_revision,
                authorization_expires_at=passing_record.expires_at,
            )
        qa_reasons = _qa_reason_codes(check_runs, statuses)
        qa_reasons.extend(_review_reason_codes(pr))
        if qa_reasons:
            return _receipt(
                parsed, repository, qa_reasons,
                head=head, body_sha=body_sha, evaluated_at=now_text,
                authorization_id=passing_record.authorization_id,
                authorization_revision=passing_record.authorization_revision,
                authorization_expires_at=passing_record.expires_at,
                candidate_records=tuple(candidate_records),
            )

        try:
            files = [(f.filename, f.sha) for f in pr.get_files()]
            scope = changed_scope_fingerprint(files)
        except (TypeError, ValueError):
            return _receipt(
                parsed, repository, ["scope.evidence-malformed"],
                head=head, body_sha=body_sha, evaluated_at=now_text,
                authorization_id=passing_record.authorization_id,
                authorization_revision=passing_record.authorization_revision,
                authorization_expires_at=passing_record.expires_at,
            )
        except Exception:
            return _receipt(
                parsed, repository, ["scope.evidence-unavailable"],
                head=head, body_sha=body_sha, evaluated_at=now_text,
                authorization_id=passing_record.authorization_id,
                authorization_revision=passing_record.authorization_revision,
                authorization_expires_at=passing_record.expires_at,
            )
        if scope != passing_record.binding.changed_scope_fingerprint:
            return _receipt(
                parsed, repository, ["scope.changed"],
                head=head, body_sha=body_sha, evaluated_at=now_text,
                authorization_id=passing_record.authorization_id,
                authorization_revision=passing_record.authorization_revision,
                authorization_expires_at=passing_record.expires_at,
                candidate_records=tuple(candidate_records),
            )

        return _receipt(
            parsed, repository, [],
            head=head, body_sha=body_sha, source_status=auth_source.status.value,
            source_comments=len(auth_source.source_comment_ids),
            record_count=len(auth_source.records), evaluated_at=now_text,
            authorization_id=passing_record.authorization_id,
            authorization_revision=passing_record.authorization_revision,
            authorization_expires_at=passing_record.expires_at,
            candidate_records=tuple(candidate_records),
            merge_authorized=True,
        )
    except Exception:
        return _receipt(parsed, repository, ["canonical-github-evidence-unavailable"],
                        evaluated_at=now_text)


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
        client = build_token_client(dict(os.environ), user_agent="agent-os-merge-admission/1")
        receipt = evaluate_merge_admission_applicability(transport, repository=args.repository, github_client=client)
    except Exception:
        receipt = _receipt(transport, args.repository, ["canonical-github-evidence-unavailable"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
