"""Read-only fixed merge-admission ingress consumer (#3463).

Reacquires the live PR and complete trusted PR-conversation authorization source.
It deliberately does not synthesize approval records or invoke the GitHub merge
API. The canonical applicability evaluator needs separately acquired typed
approval/projection/currentness evidence, not guesses from green CI or prose.
A positive source record is therefore a *candidate*, never merge admission.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from .merge_authorization import pr_metadata_fingerprint
from .merge_authorization_source import (
    MergeAuthorizationCommentSnapshot,
    MergeAuthorizationSourceSnapshot,
    reacquire_merge_authorization_source,
)

_SHA40 = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_ALLOWED_METHODS = frozenset({"merge", "squash", "rebase"})
_TRANSPORT_REASON = "accepted-merge-admission-envelope"
_MAX_COMMENTS = 256


def _receipt(transport: object, repository: str, reasons: list[str], *,
             head: str | None = None, body_sha: str | None = None,
             source_status: str | None = None, source_comments: int = 0) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "operation": "merge-admit",
        "repository": repository,
        "pr_number": transport.get("merge_admission_pr_number_or_none") if isinstance(transport, dict) else None,
        "logical_trigger_id": transport.get("logical_trigger_id_or_none") if isinstance(transport, dict) else None,
        "expected_head_sha": transport.get("merge_admission_head_sha_or_none") if isinstance(transport, dict) else None,
        "expected_body_sha256": transport.get("merge_admission_body_sha256_or_none") if isinstance(transport, dict) else None,
        "expected_method": transport.get("merge_admission_method_or_none") if isinstance(transport, dict) else None,
        "observed_head_sha": head,
        "observed_body_sha256": body_sha,
        "authorization_source_status": source_status,
        "authorization_source_comment_count": source_comments,
        "status": "blocked",
        "reason_codes": sorted(set(reasons)),
        "canonical_applicability_evaluated": False,
        "merge_authorized": False,
        "issue_closure_authorized": False,
        "workflow_authorized": False,
        "production_authorized": False,
        "external_system_write_authorized": False,
        "side_effects_performed": False,
    }
    ident = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    payload["receipt_id"] = "merge-admission-transport:" + ident
    return payload


def _parse(transport: object, repository: str) -> tuple[dict[str, Any] | None, str | None]:
    if type(transport) is not dict:
        return None, "transport-malformed"
    if transport.get("status") != "accepted" or transport.get("reason") != _TRANSPORT_REASON:
        return None, "transport-not-merge-admission"
    if transport.get("repository") != repository:
        return None, "transport-repository-mismatch"
    pr = transport.get("merge_admission_pr_number_or_none")
    head = transport.get("merge_admission_head_sha_or_none")
    body = transport.get("merge_admission_body_sha256_or_none")
    method = transport.get("merge_admission_method_or_none")
    if (type(pr) is not int or not 1 <= pr <= 999_999_999
            or type(head) is not str or _SHA40.fullmatch(head) is None
            or type(body) is not str or _SHA256.fullmatch(body) is None
            or type(method) is not str or method not in _ALLOWED_METHODS
            or type(transport.get("comment_id")) is not int
            or type(transport.get("issue_number")) is not int
            or type(transport.get("logical_trigger_id_or_none")) is not str):
        return None, "transport-malformed"
    return transport, None


class _GitHubSource:
    """Bounded canonical GitHub PR comments; never trusts request-supplied records."""

    def __init__(self, repo: Any, owner_login: str):
        self.repo = repo
        self.owner_login = owner_login

    def read_merge_authorization_source(self, repository: str, pr_number: int) -> MergeAuthorizationSourceSnapshot:
        comments: list[MergeAuthorizationCommentSnapshot] = []
        for comment in self.repo.get_issue(pr_number).get_comments():
            if len(comments) >= _MAX_COMMENTS:
                raise ValueError("authorization source exceeds comment bound")
            comments.append(MergeAuthorizationCommentSnapshot(
                comment_id=comment.id,
                author_login=comment.user.login,
                created_at=comment.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                body=comment.body or "",
            ))
        return MergeAuthorizationSourceSnapshot(
            repository=repository,
            pr_number=pr_number,
            owner_login=self.owner_login,
            owner_type=self.repo.owner.type,
            comments_complete=True,
            comments=tuple(comments),
        )


def evaluate_merge_admission_transport(
    transport: object, *,
    repository: str,
    github_client: Any,
) -> dict[str, object]:
    """Read-only bridge. Never return merge authorization without full applicability."""
    parsed, reason = _parse(transport, repository)
    if parsed is None:
        return _receipt(transport, repository, [reason or "transport-malformed"])
    try:
        repo = github_client.get_repo(repository)
        pr = repo.get_pull(parsed["merge_admission_pr_number_or_none"])
        head = pr.head.sha
        body = hashlib.sha256((pr.body or "").encode("utf-8")).hexdigest()
        failures: list[str] = []
        if pr.state != "open" or pr.draft or pr.merged:
            failures.append("pr-not-ready")
        if head != parsed["merge_admission_head_sha_or_none"]:
            failures.append("stale-head")
        if body != parsed["merge_admission_body_sha256_or_none"]:
            failures.append("stale-body")
        if pr.mergeable is not True:
            failures.append("pr-mergeability-not-clean")
        if pr.base.ref != "main":
            failures.append("base-not-main")
        if failures:
            return _receipt(parsed, repository, failures, head=head, body_sha=body)
        source = reacquire_merge_authorization_source(
            transport=_GitHubSource(repo, repo.owner.login),
            repository=repository,
            pr_number=pr.number,
        )
        if source.status.value != "current":
            return _receipt(
                parsed, repository, list(source.reason_codes),
                head=head, body_sha=body, source_status=source.status.value,
                source_comments=len(source.source_comment_ids),
            )
        matching = [
            record for record in source.records
            if record.binding.exact_head_sha == head
            and record.binding.target_base_branch == pr.base.ref
            and record.binding.base_sha_or_evidence_id == pr.base.sha
            and record.binding.permitted_merge_method == parsed["merge_admission_method_or_none"]
            and record.binding.pr_metadata_sha256
            == pr_metadata_fingerprint(pr.title or "", pr.body or "")
        ]
        return _receipt(
            parsed, repository,
            ["approval-and-applicability-evidence-not-wired"] if matching else ["authorization.binding-mismatch"],
            head=head, body_sha=body, source_status=source.status.value,
            source_comments=len(source.source_comment_ids),
        )
    except Exception:
        return _receipt(parsed, repository, ["canonical-github-evidence-unavailable"])


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
        receipt = evaluate_merge_admission_transport(transport, repository=args.repository, github_client=client)
    except Exception:
        receipt = _receipt(transport, args.repository, ["canonical-github-evidence-unavailable"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
