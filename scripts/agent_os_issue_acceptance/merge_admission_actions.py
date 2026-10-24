"""Read-only fixed merge-admission ingress consumer (#3463).

Reacquires the live PR and complete trusted PR-conversation authorization source,
then reconciles every canonically recomputable ``MergeAuthorizationBinding``
field of each trusted AUTHORIZED record against live GitHub evidence.

It deliberately does not synthesize approval records and never invokes the
GitHub merge API. Fields the consumer cannot recompute from live reads
(approval/projection identities, file-scope contract, check/review evidence,
closure admissions) are carried from the record's own trusted binding and are
reported as not independently verified: the canonical applicability evaluator
(``evaluate_merge_authorization_applicability``) needs separately acquired
typed approval/projection/currentness evidence, not guesses from green CI or
prose. A positive source record is therefore a *candidate*, never merge
admission. ``merge_authorized`` is always ``False`` in every receipt this
module emits. The positive-admission consumer is separate:
``merge_applicability.evaluate_merge_dispatch_applicability`` takes this
module's candidate receipt, additionally verifies the approval triple,
live scope, checks, reviews, and lifecycle admission, and then delegates
to the canonical evaluator with a typed ``MergeProposal``; only that
consumer can emit an applicable receipt. In production, the
``merge_admission`` job in ``agent-os-governed-invocation.yml`` runs that
consumer immediately after this module, with the same fixed transport.
This module's front-door role and its hard-coded ``False`` are unchanged
by that delegation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import fields as _dataclass_fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .merge_authorization import (
    MergeAuthorizationBinding,
    MergeAuthorizationRecord,
    pr_metadata_fingerprint,
)
from .merge_authorization_source import (
    MergeAuthorizationCommentSnapshot,
    MergeAuthorizationSourceSnapshot,
    reacquire_merge_authorization_source,
)

_SHA40 = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_ALLOWED_METHODS = frozenset({"merge", "squash", "rebase"})
_TRANSPORT_REASON = "accepted-merge-admission-envelope"

# Binding fields the consumer can recompute from live GitHub PR reads. Every
# other MergeAuthorizationBinding field is decision-time trusted evidence the
# consumer must not fabricate; those fields are reported as not independently
# verified (see _NON_RECOMPUTABLE_BINDING_FIELDS).
_LIVE_BINDING_FIELDS = (
    "repository",
    "pull_request_number",
    "exact_head_sha",
    "target_base_branch",
    "base_sha_or_evidence_id",
    "permitted_merge_method",
    "pr_metadata_sha256",
    "draft_ready_state",
)
_NON_RECOMPUTABLE_BINDING_FIELDS = (
    "approval_id",
    "approval_revision",
    "approval_applicability_identity",
    "approval_expires_at",
    "approved_execution_projection_id",
    "changed_scope_fingerprint",
    "allowed_files",
    "forbidden_paths",
    "required_tests",
    "required_check_evidence",
    "review_evidence",
    "closure_admission_ids",
)
# Canonical changed-field -> reason-code mapping. Must stay identical to
# merge_authorization._binding_reasons for the live-comparable fields; pinned
# by test_merge_admission_actions.test_binding_reason_mapping_matches_canonical.
_BINDING_FIELD_REASONS = {
    "repository": "pull-request.identity-changed",
    "pull_request_number": "pull-request.identity-changed",
    "exact_head_sha": "pull-request.head-changed",
    "target_base_branch": "pull-request.base-changed",
    "base_sha_or_evidence_id": "pull-request.base-changed",
    "permitted_merge_method": "merge.method-changed",
    "pr_metadata_sha256": "pull-request.metadata-changed",
    "draft_ready_state": "pull-request.ready-state-changed",
}


def _check_binding_contract() -> None:
    """Fail fast if the canonical binding contract drifts from this consumer."""
    declared = {field.name for field in _dataclass_fields(MergeAuthorizationBinding)}
    covered = set(_LIVE_BINDING_FIELDS) | set(_NON_RECOMPUTABLE_BINDING_FIELDS)
    if covered != declared:
        raise ValueError(
            "merge-admission binding coverage drifted from MergeAuthorizationBinding: "
            f"missing={sorted(declared - covered)} extra={sorted(covered - declared)}"
        )
    if set(_BINDING_FIELD_REASONS) != set(_LIVE_BINDING_FIELDS):
        raise ValueError("binding reason mapping must cover exactly the live fields")


_check_binding_contract()

_HOST_DISPATCH_CONTRACT = {
    "schema_version": "1.0",
    "consumer": "chatgpt-github-connector (issue #2340 owns the mutation-dispatch seam)",
    "merge_dispatch_allowed_only_when_all_true": [
        "receipt.status == 'applicable'",
        "receipt.merge_authorized is true",
        "receipt.authorization_id names a trusted owner-authored "
        "agent-os-merge-authorization/v1 record still current at dispatch time",
        "receipt.expected_head_sha equals the live PR head SHA reacquired at dispatch time",
        "receipt.authorization_expires_at is in the future at dispatch time",
        "the native merge call carries expected_head_sha == receipt.expected_head_sha",
    ],
    "forbidden": [
        "treating a 'blocked' receipt, or any receipt with reason codes, as authorization",
        "merging when receipt.observed_head_sha != receipt.expected_head_sha",
        "reusing a receipt after its authorization_expires_at",
        "reusing a receipt whose authorization record was consumed, superseded, "
        "revoked, or invalidated after the receipt was produced",
    ],
    "note": "This consumer never emits merge_authorized=true. A host-dispatchable "
    "applicable receipt is produced by merge_applicability.py, which "
    "delegates to the canonical evaluator with a typed MergeProposal "
    "(see the #3463 change request for issue #2340).",
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or _TIMESTAMP_RE.fullmatch(value) is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _receipt(transport: object, repository: str, reasons: list[str], *,
             head: str | None = None, body_sha: str | None = None,
             source_status: str | None = None, source_comments: int = 0,
             record_count: int = 0, evaluated_at: str | None = None,
             authorization_id: str | None = None,
             authorization_revision: str | None = None,
             authorization_expires_at: str | None = None,
             binding_changed_fields: tuple[str, ...] = (),
             candidate_records: tuple[dict[str, object], ...] = (),
             emergency_override_present: bool = False) -> dict[str, object]:
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
        "authorization_record_count": record_count,
        "evaluated_at": evaluated_at,
        "authorization_id": authorization_id,
        "authorization_revision": authorization_revision,
        "authorization_expires_at": authorization_expires_at,
        "binding_fields_verified": list(_LIVE_BINDING_FIELDS),
        "binding_fields_not_independently_verified": list(_NON_RECOMPUTABLE_BINDING_FIELDS),
        "binding_changed_fields": list(binding_changed_fields),
        "candidate_records": list(candidate_records),
        "emergency_override_present": emergency_override_present,
        "status": "blocked",
        "reason_codes": sorted(set(reasons)),
        "canonical_applicability_evaluated": False,
        "merge_authorized": False,
        "issue_closure_authorized": False,
        "workflow_authorized": False,
        "production_authorized": False,
        "external_system_write_authorized": False,
        "side_effects_performed": False,
        "host_dispatch_contract": _HOST_DISPATCH_CONTRACT,
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
    """Bounded canonical GitHub PR comments; never trusts request-supplied records.

    Comment-count and byte bounds are enforced by the canonical
    ``reacquire_merge_authorization_source`` contract (512 comments / 256 KiB
    total); this transport must not invent a stricter local bound that would
    misreport available evidence as unavailable.
    """

    def __init__(self, repo: Any, owner_login: str):
        self.repo = repo
        self.owner_login = owner_login

    def read_merge_authorization_source(self, repository: str, pr_number: int):
        comments: list[MergeAuthorizationCommentSnapshot] = []
        for comment in self.repo.get_issue(pr_number).get_comments():
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


def _live_binding_values(repository: str, pr_number: int, method: str,
                         head: str, base_ref: str, base_sha: str,
                         title: str, body: str, draft: bool) -> dict[str, object]:
    return {
        "repository": repository,
        "pull_request_number": pr_number,
        "exact_head_sha": head,
        "target_base_branch": base_ref,
        "base_sha_or_evidence_id": base_sha,
        "permitted_merge_method": method,
        "pr_metadata_sha256": pr_metadata_fingerprint(title, body),
        "draft_ready_state": "draft" if draft else "ready",
    }


def _evaluate_record(record: MergeAuthorizationRecord, live: dict[str, object],
                     evaluated_at: datetime) -> tuple[bool, list[str], list[str]]:
    """Reconcile one trusted record against live evidence.

    Returns (fully_matching, reason_codes, changed_fields). Never authorizes.
    """
    reasons: list[str] = []
    changed = [
        name for name in _LIVE_BINDING_FIELDS
        if getattr(record.binding, name) != live[name]
    ]
    for name in changed:
        reasons.append(_BINDING_FIELD_REASONS[name])
    expires_at = _parse_timestamp(record.expires_at)
    if expires_at is None or evaluated_at >= expires_at:
        reasons.append("authorization.expired")
    return (not reasons, sorted(set(reasons)), changed)


def evaluate_merge_admission_transport(
    transport: object, *,
    repository: str,
    github_client: Any,
    evaluated_at: str | None = None,
) -> dict[str, object]:
    """Read-only bridge. Never return merge authorization without full applicability."""
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
            return _receipt(parsed, repository, failures, head=head, body_sha=body,
                            evaluated_at=now_text)
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
                record_count=len(source.records), evaluated_at=now_text,
            )
        live = _live_binding_values(
            repository, pr.number, parsed["merge_admission_method_or_none"],
            head, pr.base.ref, pr.base.sha, pr.title or "", pr.body or "", pr.draft,
        )
        candidates: list[dict[str, object]] = []
        passing: dict[str, object] | None = None
        for record in source.records:
            ok, record_reasons, changed = _evaluate_record(record, live, now)
            candidates.append({
                "authorization_id": record.authorization_id,
                "authorization_revision": record.authorization_revision,
                "expires_at": record.expires_at,
                "fully_matching": ok,
                "changed_fields": changed,
                "reason_codes": record_reasons,
                "emergency_override_present": record.emergency_override_reason is not None,
            })
            if ok and passing is None:
                passing = candidates[-1]
        if passing is not None:
            # All recomputable bindings match a trusted, unexpired AUTHORIZED
            # record — but canonical approval/projection applicability is not
            # wired, so this stays a non-authorizing candidate receipt.
            return _receipt(
                parsed, repository,
                ["approval-and-applicability-evidence-not-wired"],
                head=head, body_sha=body, source_status=source.status.value,
                source_comments=len(source.source_comment_ids),
                record_count=len(source.records), evaluated_at=now_text,
                authorization_id=passing["authorization_id"],
                authorization_revision=passing["authorization_revision"],
                authorization_expires_at=passing["expires_at"],
                candidate_records=tuple(candidates),
                emergency_override_present=bool(passing["emergency_override_present"]),
            )
        reasons = {"authorization.binding-mismatch"}
        for candidate in candidates:
            reasons.update(candidate["reason_codes"])
        return _receipt(
            parsed, repository, sorted(reasons),
            head=head, body_sha=body, source_status=source.status.value,
            source_comments=len(source.source_comment_ids),
            record_count=len(source.records), evaluated_at=now_text,
            candidate_records=tuple(candidates),
            emergency_override_present=any(
                candidate["emergency_override_present"] for candidate in candidates
            ),
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
        receipt = evaluate_merge_admission_transport(transport, repository=args.repository, github_client=client)
    except Exception:
        receipt = _receipt(transport, args.repository, ["canonical-github-evidence-unavailable"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
