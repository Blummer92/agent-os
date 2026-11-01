"""Read-only, owner-operated schema-1.2 merge-authorization preparation.

This CLI never posts GitHub comments, approves a merge, mutates a PR, or
executes a merge. Only an owner operating GitHub's first-party web UI can
publish a record, and even that record is not host merge attestation.

Usage, from repository root:
  python -m scripts.agent_os_issue_acceptance.merge_authorization_owner_console prepare --policy policy.json --output pending.json
  python -m scripts.agent_os_issue_acceptance.merge_authorization_owner_console decide --pending pending.json --decision-id owner-20261101-pr3752 --confirm 'Blummer92/agent-os#3752@<SHA>:squash' --output decided.json
  python -m scripts.agent_os_issue_acceptance.merge_authorization_owner_console verify --decision decided.json --output verification.json

All commands need GITHUB_TOKEN for read-only GitHub retrieval. Neither this
script nor the GitHub token establishes positive human-origin provenance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .merge_authorization import (
    AUTHORITATIVE_AGGREGATE_APP_IDENTITY,
    AUTHORITATIVE_AGGREGATE_CONTEXT,
    MergeAuthorizationState,
    MergeCheckEvidence,
    MergeReviewEvidence,
    PullRequestMergeEvidence,
    _repository,
    _timestamp,
    build_merge_authorization_candidate_from_pr,
    changed_scope_fingerprint,
    evaluate_merge_authorization_applicability,
    record_merge_authorization_decision,
    reconstruct_merge_authorization_record,
)
from .merge_authorization_source import (
    MAX_COMMENT_BYTES,
    MergeAuthorizationSourceStatus,
    reacquire_merge_authorization_source,
    serialize_merge_authorization_comment,
)
from .merge_applicability import (
    _GitHubCommentSource,
    _latest_evidence,
    _unresolved_review_threads,
)
from .checks.forbidden_paths import _matches as forbidden_path_matches
from .path_contract import normalize_declared_path

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_REQUIRED_POLICY_KEYS = frozenset({
    "repository", "pr_number", "merge_method", "allowed_files",
    "forbidden_paths", "required_tests", "required_check_contexts",
    "decision_id", "expires_at",
})
_MAX_FILES = 256


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def strict_policy(data: Any) -> dict[str, Any]:
    if type(data) is not dict or set(data) != _REQUIRED_POLICY_KEYS:
        raise ValueError("policy fields missing or unexpected")
    _repository(data["repository"])
    if type(data["pr_number"]) is not int or data["pr_number"] < 1:
        raise ValueError("invalid PR number")
    if data["merge_method"] not in ("merge", "squash", "rebase"):
        raise ValueError("invalid merge method")
    for key in ("allowed_files", "required_tests", "required_check_contexts"):
        values = data[key]
        if type(values) is not list or not values or len(values) > _MAX_FILES or any(
            not isinstance(value, str) or not value.strip() for value in values
        ) or len(values) != len(set(values)):
            raise ValueError(f"{key} must be a nonempty, unique, bounded string list")
    # forbidden_paths may be empty (canonical evidence allows empty lists):
    # an empty exclusion list adds no restriction beyond allowed_files, so
    # forcing a nonempty list would only make owners invent a pattern.
    forbidden = data["forbidden_paths"]
    if type(forbidden) is not list or len(forbidden) > _MAX_FILES or any(
        not isinstance(value, str) or not value.strip() for value in forbidden
    ) or len(forbidden) != len(set(forbidden)):
        raise ValueError("forbidden_paths must be a unique, bounded string list")
    if AUTHORITATIVE_AGGREGATE_CONTEXT not in data["required_check_contexts"]:
        raise ValueError("authoritative aggregate must be required")
    if not isinstance(data["decision_id"], str) or not data["decision_id"].strip():
        raise ValueError("decision identity is missing")
    if data["decision_id"] == "PENDING-NO-OWNER-MERGE-DECISION":
        raise ValueError("template placeholder decision identity must be replaced")
    if not isinstance(data["expires_at"], str):
        raise ValueError("expiry is missing")
    if _timestamp(data["expires_at"], "expires_at") <= _timestamp(utcnow(), "now"):
        raise ValueError("expiry must be in the future")
    return data


def read_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_new_json(path: str, data: dict[str, Any]) -> None:
    # No overwrite; owner may retain the prior record for audit.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=True, indent=2, sort_keys=True)
        stream.write("\n")


def comment_to_record(comment: str) -> Any:
    from .merge_authorization_source import AUTHORIZATION_MARKER
    if not isinstance(comment, str) or not comment.startswith(AUTHORIZATION_MARKER + "\n"):
        raise ValueError("missing trusted marker")
    lines = comment.split("\n")
    if len(lines) != 2:
        raise ValueError("exactly two comment lines are required")
    record = reconstruct_merge_authorization_record(lines[1])
    if record.schema_version != "1.2":
        raise ValueError("only current schema-1.2 records are supported")
    if serialize_merge_authorization_comment(record) != comment:
        raise ValueError("noncanonical authorization comment")
    return record


def client_from_environment() -> Any:
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise ValueError("GITHUB_TOKEN is required for read-only PR evidence")
    from github import Github
    return Github(token)


def live_evidence(client: Any, *, repository: str, pr_number: int,
                  method: str, allowed_files: tuple[str, ...],
                  forbidden_paths: tuple[str, ...],
                  required_tests: tuple[str, ...],
                  required_contexts: tuple[str, ...]) -> tuple[PullRequestMergeEvidence, str]:
    """Reacquire live, bounded GitHub evidence; do not trust caller-supplied SHAs."""
    repo = client.get_repo(repository)
    if getattr(repo.owner, "type", None) != "User":
        raise ValueError("repository owner must be a verified User, not organization/bot")
    pr = repo.get_pull(pr_number)
    if pr.state != "open" or pr.merged or pr.draft:
        raise ValueError("PR must be open, unmerged and Ready")
    if pr.base.ref != repo.default_branch or pr.base.ref != "main":
        raise ValueError("target branch must be main")
    if not getattr(pr, "mergeable", False):
        raise ValueError("GitHub has not established mergeability")
    head, base = pr.head.sha, pr.base.sha
    if not _SHA40.fullmatch(head) or not _SHA40.fullmatch(base):
        raise ValueError("live head/base SHA missing")
    changed = tuple((item.filename, item.sha) for item in pr.get_files())
    if not changed or len(changed) > _MAX_FILES:
        raise ValueError("changed-file evidence is missing or unbounded")
    paths = [name for name, _ in changed]
    if len(paths) != len(set(paths)) or set(paths) - set(allowed_files):
        raise ValueError("live files fall outside explicit owner scope")
    if any(forbidden_path_matches(normalize_declared_path(path), pattern)
           for path in paths for pattern in forbidden_paths):
        raise ValueError("PR contains explicitly forbidden paths")
    observed = _latest_evidence(repo.get_commit(head))
    checks = []
    for context in required_contexts:
        item = observed.get(context)
        if item is None or item[0] != "success" or not item[1]:
            raise ValueError(f"missing/failed/unverifiable required check: {context}")
        # Publisher identity is verified by _latest_evidence either from
        # the commit-status creator or from the check-run app (github-actions
        # requires app id 15368 there). For the aggregate context the
        # producer additionally requires a real commit status (third tuple
        # element): the canonical evaluator accepts a publisher-verified
        # check-run-only aggregate, but the dispatch consumer refuses it
        # as checks.authoritative-aggregate-unverifiable, so accepting it
        # here would mint a binding that can never dispatch. The producer
        # is deliberately stricter than the evaluator and exactly aligned
        # with dispatch for the aggregate.
        if context == AUTHORITATIVE_AGGREGATE_CONTEXT and (
            item[1] != AUTHORITATIVE_AGGREGATE_APP_IDENTITY or not item[2]
        ):
            raise ValueError("authoritative aggregate publisher is unverified or not a commit status")
        checks.append(MergeCheckEvidence(context=context, app_identity=item[1],
                                         tested_sha=head, evidence_id="", state="success"))
    reviews = tuple(pr.get_reviews())
    blocking = any(review.state == "CHANGES_REQUESTED" for review in reviews)
    unresolved = _unresolved_review_threads(client, repository, pr_number)
    if blocking or unresolved:
        raise ValueError("blocking review or unresolved review threads")
    head_reviewed = any(review.state == "APPROVED" and review.commit_id == head for review in reviews)
    evidence = PullRequestMergeEvidence(
        repository=repository, pull_request_number=pr_number, head_sha=head,
        base_branch=pr.base.ref, base_sha_or_evidence_id=base,
        draft=False, ready_for_review=True, proposed_merge_method=method,
        changed_scope_fingerprint=changed_scope_fingerprint(changed),
        allowed_files=allowed_files, forbidden_paths=forbidden_paths,
        required_tests=required_tests, required_checks=tuple(checks),
        review_evidence=MergeReviewEvidence(
            blocking_review_present=False, unresolved_conversation_count=0,
            exact_head_reviewed=head_reviewed),
        pr_title=pr.title or "", pr_body=pr.body or "",
        pr_metadata_sha256="", closure_admissions=(), evidence_id="",
    )
    # Detect head/base drift while the evidence was collected.
    renewed = repo.get_pull(pr_number)
    if renewed.head.sha != head or renewed.base.sha != base or (renewed.title or "") != (pr.title or "") or (renewed.body or "") != (pr.body or ""):
        raise ValueError("PR changed during evidence collection")
    return evidence, repo.owner.login


def prepare(policy: dict[str, Any], client: Any) -> dict[str, Any]:
    policy = strict_policy(policy)
    evidence, owner = live_evidence(
        client, repository=policy["repository"], pr_number=policy["pr_number"],
        method=policy["merge_method"],
        allowed_files=tuple(policy["allowed_files"]),
        forbidden_paths=tuple(policy["forbidden_paths"]),
        required_tests=tuple(policy["required_tests"]),
        required_contexts=tuple(policy["required_check_contexts"]),
    )
    candidate = build_merge_authorization_candidate_from_pr(
        evidence, authorizer_id=owner, decision_id=policy["decision_id"],
        decision_at=utcnow(), expires_at=policy["expires_at"],
    )
    body = serialize_merge_authorization_comment(candidate)
    comment_to_record(body)
    if len(body.encode("utf-8")) > MAX_COMMENT_BYTES:
        raise ValueError("authorization comment exceeds trusted source bound")
    repo = client.get_repo(policy["repository"])
    existing = reacquire_merge_authorization_source(
        transport=_GitHubCommentSource(repo, repo.owner.login),
        repository=policy["repository"], pr_number=policy["pr_number"],
    )
    # A STALE chain (pending-only, rejected, expired, superseded, or
    # consumed) must also be reconciled before a new chain is prepared:
    # preparing alongside it would leave two authorization chains in one
    # PR conversation. Only a clean absence (BLOCKED/authorization.absent)
    # admits a fresh preparation.
    if existing.status in (MergeAuthorizationSourceStatus.CURRENT, MergeAuthorizationSourceStatus.NEEDS_DECISION, MergeAuthorizationSourceStatus.STALE):
        raise ValueError(f"existing trusted authorization must be reconciled first: {existing.reason_codes}")
    return {
        "status": "PENDING_OWNER_PUBLICATION", "merge_authorized": False,
        "side_effects_performed": False, "repository": policy["repository"],
        "pr_number": policy["pr_number"], "head_sha": evidence.head_sha,
        "base_sha": evidence.base_sha_or_evidence_id,
        "merge_method": policy["merge_method"],
        "scope_fingerprint": evidence.changed_scope_fingerprint,
        "authorization_id": candidate.authorization_id,
        "authorization_revision": candidate.authorization_revision,
        "pending_comment": body,
        "pending_comment_sha256": hashlib.sha256(body.encode()).hexdigest(),
        "notice": "Owner must directly publish this exact two-line PENDING comment on the PR Conversation. This file does not authenticate an owner or authorize a merge.",
    }


def decide(pending: dict[str, Any], client: Any, *, decision_id: str,
           confirmation: str) -> dict[str, Any]:
    if pending.get("status") != "PENDING_OWNER_PUBLICATION" or pending.get("merge_authorized") is not False:
        raise ValueError("expected an unapproved pending artifact")
    record = comment_to_record(pending["pending_comment"])
    if record.state is not MergeAuthorizationState.PENDING:
        raise ValueError("first revision is not pending")
    if record.authorization_id != pending.get("authorization_id") or record.authorization_revision != pending.get("authorization_revision"):
        raise ValueError("pending artifact identity mismatch")
    binding = record.binding
    expected = f"{binding.repository}#{binding.pull_request_number}@{binding.exact_head_sha}:{binding.permitted_merge_method}"
    if confirmation != expected:
        raise ValueError("explicit exact-binding owner confirmation does not match")
    # Refuse to produce an approved revision if the PR or admitted evidence moved.
    fresh, owner = live_evidence(
        client, repository=binding.repository, pr_number=binding.pull_request_number,
        method=binding.permitted_merge_method,
        allowed_files=binding.allowed_files,
        forbidden_paths=binding.forbidden_paths,
        required_tests=binding.required_tests,
        required_contexts=tuple(item.context for item in binding.required_check_evidence),
    )
    if owner.casefold() != record.authorizer_id.casefold():
        raise ValueError("repository owner changed")
    # A PENDING decision cannot be promoted until the owner has published
    # its exact two-line predecessor and the trusted source has read it.
    repo = client.get_repo(binding.repository)
    source = reacquire_merge_authorization_source(
        transport=_GitHubCommentSource(repo, repo.owner.login),
        repository=binding.repository, pr_number=binding.pull_request_number,
        expected_authorization_id=record.authorization_id,
    )
    if (source.status is not MergeAuthorizationSourceStatus.STALE
            or source.reason_codes != ("authorization.consumed-or-not-current",)
            or len(source.source_comment_ids) != 1):
        raise ValueError(f"owner-posted pending predecessor not verified: {source.reason_codes}")
    current = evaluate_merge_authorization_applicability(record, fresh, evaluated_at=utcnow())
    if current.status not in ("blocked",) or current.reason_codes != ("authorization.pending",):
        raise ValueError(f"pending record is stale or otherwise blocked: {current.reason_codes}")
    decided = record_merge_authorization_decision(
        record, state=MergeAuthorizationState.AUTHORIZED, decision_id=decision_id,
        authorizer_id=owner, decision_at=utcnow(),
    )
    body = serialize_merge_authorization_comment(decided)
    comment_to_record(body)
    if len(body.encode("utf-8")) > MAX_COMMENT_BYTES:
        raise ValueError("authorization comment exceeds trusted source bound")
    return {
        "status": "AWAITING_OWNER_PUBLICATION_AND_READBACK",
        "merge_authorized": False, "side_effects_performed": False,
        "repository": binding.repository, "pr_number": binding.pull_request_number,
        "authorization_id": decided.authorization_id,
        "authorization_revision": decided.authorization_revision,
        "pending_revision": record.authorization_revision,
        "pending_comment": pending["pending_comment"],
        "authorized_comment": body,
        "authorized_comment_sha256": hashlib.sha256(body.encode()).hexdigest(),
        "notice": "Not authorization until BOTH exact two-line revisions are personally posted by the owner in the PR Conversation and independently read back. Do not post via an agent, GitHub App, or bot. Separate runtime approval is required for any merge.",
    }


def verify(decision: dict[str, Any], client: Any) -> dict[str, Any]:
    if decision.get("status") != "AWAITING_OWNER_PUBLICATION_AND_READBACK":
        raise ValueError("unpublished decision artifact required")
    pending = comment_to_record(decision["pending_comment"])
    approved = comment_to_record(decision["authorized_comment"])
    if pending.authorization_id != approved.authorization_id or approved.previous_revision != pending.authorization_revision or approved.state is not MergeAuthorizationState.AUTHORIZED:
        raise ValueError("invalid owner decision revision chain")
    binding = approved.binding
    repo = client.get_repo(binding.repository)
    source = reacquire_merge_authorization_source(
        transport=_GitHubCommentSource(repo, repo.owner.login),
        repository=binding.repository, pr_number=binding.pull_request_number,
        expected_authorization_id=approved.authorization_id,
    )
    if source.status is not MergeAuthorizationSourceStatus.CURRENT or len(source.records) != 1:
        raise ValueError(f"trusted source not current: {source.reason_codes}")
    if len(source.source_comment_ids) != 2 or source.records[0].authorization_revision != approved.authorization_revision:
        raise ValueError("exact two-revision source chain not established")
    fresh, owner = live_evidence(
        client, repository=binding.repository, pr_number=binding.pull_request_number,
        method=binding.permitted_merge_method,
        allowed_files=binding.allowed_files,
        forbidden_paths=binding.forbidden_paths,
        required_tests=binding.required_tests,
        required_contexts=tuple(item.context for item in binding.required_check_evidence),
    )
    if owner.casefold() != approved.authorizer_id.casefold():
        raise ValueError("trusted author is not current repository owner")
    current = evaluate_merge_authorization_applicability(source.records[0], fresh, evaluated_at=utcnow())
    if current.status != "applicable" or not current.merge_authorized:
        raise ValueError(f"record stale or inapplicable: {current.reason_codes}")
    # A second source read narrows source-revision drift between evidence reads.
    final_source = reacquire_merge_authorization_source(
        transport=_GitHubCommentSource(repo, repo.owner.login),
        repository=binding.repository, pr_number=binding.pull_request_number,
        expected_authorization_id=approved.authorization_id,
    )
    if (final_source.status is not MergeAuthorizationSourceStatus.CURRENT
            or final_source.source_comment_ids != source.source_comment_ids
            or len(final_source.records) != 1
            or final_source.records[0].authorization_revision != approved.authorization_revision):
        raise ValueError("authorization source changed during verification")
    return {
        "status": "SOURCE_CURRENT_CONTENT_APPLICABLE", "merge_authorized": False,
        "side_effects_performed": False, "human_origin_attested": False,
        "repository": binding.repository, "pr_number": binding.pull_request_number,
        "head_sha": binding.exact_head_sha,
        "authorization_id": approved.authorization_id,
        "authorization_revision": approved.authorization_revision,
        "source_comment_ids": list(source.source_comment_ids),
        "reason_codes": ["human-origin-attestation-required"],
        "notice": "Trusted source and canonical content applicability verified. Runtime approval and governed merge execution are separate, unverified steps.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare")
    p.add_argument("--policy", required=True)
    p.add_argument("--output", required=True)
    d = commands.add_parser("decide")
    d.add_argument("--pending", required=True)
    d.add_argument("--decision-id", required=True)
    d.add_argument("--confirm", required=True)
    d.add_argument("--output", required=True)
    v = commands.add_parser("verify")
    v.add_argument("--decision", required=True)
    v.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        client = client_from_environment()
        if args.command == "prepare":
            payload = prepare(read_json(args.policy), client)
        elif args.command == "decide":
            payload = decide(read_json(args.pending), client, decision_id=args.decision_id,
                             confirmation=args.confirm)
        else:
            payload = verify(read_json(args.decision), client)
        write_new_json(args.output, payload)
        print(json.dumps({"status": payload["status"], "output": args.output,
                          "merge_authorized": False}, sort_keys=True))
        return 0
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # fail closed on client/network failures too
        print(f"BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
