from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Literal

DRAFT_PR_MATERIALIZATION_SCHEMA_VERSION = "1.0"

Disposition = Literal[
    "create-primary-pr",
    "allow-canonical-no-diff",
    "block-empty-diff",
    "block-out-of-scope-diff",
    "block-invalid-evidence",
]


@dataclass(frozen=True, slots=True, kw_only=True)
class DraftPrMaterializationAdmission:
    schema_version: str = DRAFT_PR_MATERIALIZATION_SCHEMA_VERSION
    result_id: str
    repository: str
    issue_number: int
    base_sha: str
    head_sha: str
    changed_files: int
    in_scope_changed_files: int
    canonical_no_diff_permitted: bool
    post_create_readback: bool
    disposition: Disposition
    admitted: bool
    reason_codes: tuple[str, ...]
    execution_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    issue_closure_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)


def evaluate_draft_pr_materialization(
    *,
    repository: object,
    issue_number: object,
    base_sha: object,
    head_sha: object,
    changed_files: object,
    in_scope_changed_files: object,
    canonical_no_diff_permitted: object = False,
    post_create_readback: object = False,
) -> DraftPrMaterializationAdmission:
    """Fail closed unless current evidence proves a legitimate implementation diff.

    The guard intentionally evaluates the net branch/base diff rather than commit
    history.  A changed head SHA, temporary probe commits, or a create/delete pair
    therefore cannot satisfy ordinary implementation delivery when GitHub reports
    zero changed files relative to the base.

    ``canonical_no_diff_permitted`` is an explicit exception input owned by a
    pre-existing canonical workflow contract.  This module does not infer that
    exception from issue prose, commit messages, branch names, or caller intent.
    """

    if not _valid_repository(repository):
        return _result(
            repository="unavailable",
            issue_number=0,
            base_sha="unavailable",
            head_sha="unavailable",
            changed_files=0,
            in_scope_changed_files=0,
            canonical_no_diff_permitted=False,
            post_create_readback=False,
            disposition="block-invalid-evidence",
            admitted=False,
            reasons=("draft-pr-materialization.repository-invalid",),
        )
    if not _positive_int(issue_number):
        return _invalid(repository, issue_number, base_sha, head_sha, changed_files, in_scope_changed_files,
                        canonical_no_diff_permitted, post_create_readback,
                        "draft-pr-materialization.issue-invalid")
    if not _sha(base_sha) or not _sha(head_sha):
        return _invalid(repository, issue_number, base_sha, head_sha, changed_files, in_scope_changed_files,
                        canonical_no_diff_permitted, post_create_readback,
                        "draft-pr-materialization.sha-invalid")
    if not _nonnegative_int(changed_files) or not _nonnegative_int(in_scope_changed_files):
        return _invalid(repository, issue_number, base_sha, head_sha, changed_files, in_scope_changed_files,
                        canonical_no_diff_permitted, post_create_readback,
                        "draft-pr-materialization.diff-count-invalid")
    if in_scope_changed_files > changed_files:
        return _invalid(repository, issue_number, base_sha, head_sha, changed_files, in_scope_changed_files,
                        canonical_no_diff_permitted, post_create_readback,
                        "draft-pr-materialization.scope-count-invalid")
    if not isinstance(canonical_no_diff_permitted, bool) or not isinstance(post_create_readback, bool):
        return _invalid(repository, issue_number, base_sha, head_sha, changed_files, in_scope_changed_files,
                        False, False,
                        "draft-pr-materialization.flag-invalid")

    if changed_files == 0:
        if canonical_no_diff_permitted:
            return _result(
                repository=repository,
                issue_number=issue_number,
                base_sha=base_sha,
                head_sha=head_sha,
                changed_files=0,
                in_scope_changed_files=0,
                canonical_no_diff_permitted=True,
                post_create_readback=post_create_readback,
                disposition="allow-canonical-no-diff",
                admitted=True,
                reasons=("draft-pr-materialization.canonical-no-diff",),
            )
        reason = (
            "draft-pr-materialization.post-create-empty-diff"
            if post_create_readback
            else "draft-pr-materialization.empty-diff"
        )
        return _result(
            repository=repository,
            issue_number=issue_number,
            base_sha=base_sha,
            head_sha=head_sha,
            changed_files=0,
            in_scope_changed_files=0,
            canonical_no_diff_permitted=False,
            post_create_readback=post_create_readback,
            disposition="block-empty-diff",
            admitted=False,
            reasons=(reason,),
        )

    if in_scope_changed_files == 0:
        return _result(
            repository=repository,
            issue_number=issue_number,
            base_sha=base_sha,
            head_sha=head_sha,
            changed_files=changed_files,
            in_scope_changed_files=0,
            canonical_no_diff_permitted=canonical_no_diff_permitted,
            post_create_readback=post_create_readback,
            disposition="block-out-of-scope-diff",
            admitted=False,
            reasons=("draft-pr-materialization.no-in-scope-diff",),
        )

    return _result(
        repository=repository,
        issue_number=issue_number,
        base_sha=base_sha,
        head_sha=head_sha,
        changed_files=changed_files,
        in_scope_changed_files=in_scope_changed_files,
        canonical_no_diff_permitted=canonical_no_diff_permitted,
        post_create_readback=post_create_readback,
        disposition="create-primary-pr",
        admitted=True,
        reasons=("draft-pr-materialization.in-scope-diff-present",),
    )


def _invalid(
    repository: object,
    issue_number: object,
    base_sha: object,
    head_sha: object,
    changed_files: object,
    in_scope_changed_files: object,
    canonical_no_diff_permitted: object,
    post_create_readback: object,
    reason: str,
) -> DraftPrMaterializationAdmission:
    return _result(
        repository=repository if _valid_repository(repository) else "unavailable",
        issue_number=issue_number if _positive_int(issue_number) else 0,
        base_sha=base_sha if _sha(base_sha) else "unavailable",
        head_sha=head_sha if _sha(head_sha) else "unavailable",
        changed_files=changed_files if _nonnegative_int(changed_files) else 0,
        in_scope_changed_files=in_scope_changed_files if _nonnegative_int(in_scope_changed_files) else 0,
        canonical_no_diff_permitted=canonical_no_diff_permitted if isinstance(canonical_no_diff_permitted, bool) else False,
        post_create_readback=post_create_readback if isinstance(post_create_readback, bool) else False,
        disposition="block-invalid-evidence",
        admitted=False,
        reasons=(reason,),
    )


def _result(
    *,
    repository: str,
    issue_number: int,
    base_sha: str,
    head_sha: str,
    changed_files: int,
    in_scope_changed_files: int,
    canonical_no_diff_permitted: bool,
    post_create_readback: bool,
    disposition: Disposition,
    admitted: bool,
    reasons: tuple[str, ...],
) -> DraftPrMaterializationAdmission:
    preliminary = DraftPrMaterializationAdmission(
        result_id="",
        repository=repository,
        issue_number=issue_number,
        base_sha=base_sha,
        head_sha=head_sha,
        changed_files=changed_files,
        in_scope_changed_files=in_scope_changed_files,
        canonical_no_diff_permitted=canonical_no_diff_permitted,
        post_create_readback=post_create_readback,
        disposition=disposition,
        admitted=admitted,
        reason_codes=tuple(sorted(set(reasons))),
    )
    payload = _payload(preliminary)
    return replace(
        preliminary,
        result_id="draft-pr-materialization:" + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    )


def _payload(result: DraftPrMaterializationAdmission) -> dict[str, object]:
    return {
        "schema_version": result.schema_version,
        "repository": result.repository,
        "issue_number": result.issue_number,
        "base_sha": result.base_sha,
        "head_sha": result.head_sha,
        "changed_files": result.changed_files,
        "in_scope_changed_files": result.in_scope_changed_files,
        "canonical_no_diff_permitted": result.canonical_no_diff_permitted,
        "post_create_readback": result.post_create_readback,
        "disposition": result.disposition,
        "admitted": result.admitted,
        "reason_codes": list(result.reason_codes),
        "execution_authorized": False,
        "merge_authorized": False,
        "issue_closure_authorized": False,
        "side_effects_performed": False,
    }


def _valid_repository(value: object) -> bool:
    return isinstance(value, str) and value.count("/") == 1 and all(value.split("/")) and len(value) <= 256


def _positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def _nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _sha(value: object) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(ch in "0123456789abcdef" for ch in value)
