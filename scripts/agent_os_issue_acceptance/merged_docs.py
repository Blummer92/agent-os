"""Cumulative required-documentation evidence (#3724).

The per-PR required-docs contract is preserved: a declaration is satisfied
by a file changed in the currently evaluated PR, exactly as before. A
declaration may *also* be satisfied by a merged PR, but only through a
verified record that passes every gate below. No single gate is sufficient
on its own, and neither PR prose nor a GitHub cross-reference alone is ever
sufficient:

1. ``merged`` is exactly ``True`` (GitHub API ``merged_at``).
2. ``association_basis`` is ``timeline-cross-reference``: the producer found
   the merged PR as a same-repository cross-reference on the evaluated
   issue's timeline *and* the canonical linked-issue parser associates the
   PR's own title and body unambiguously with that issue.
3. The record's ``linked_issue_number`` equals the evaluated issue number
   (the report-only association for the current PR, see ``policy``).
4. ``merge_commit_in_evaluated_base`` is exactly ``True``: the producer
   verified via the GitHub compare API that the merge commit is the
   merge-base of the evaluated PR's base and that the base is not behind it.
5. ``declared_required_docs`` equals the current issue's ``required_docs``
   list exactly, so evidence recorded against an older declaration set
   cannot satisfy a changed issue (freshness).
6. ``files`` lists only the source PR's documentation files that match a
   current declaration and whose blob at the evaluated base is identical to
   the blob at the merge commit (producer-verified), so documentation edited,
   reverted, or deleted after the merge never counts. A declaration is
   covered when one of these files matches it under the canonical
   ``declared_path_matches`` contract (applied by the required-docs check).

An invalid record simply does not count: it never broadens coverage, never
turns a failure into a pass, and never turns a pass into a failure on its
own. Its stable reason code is reported alongside a failing docs check.
This module is offline and pure: it validates the record the workflow
producer built; it performs no GitHub or git access. The producer lives in
``build_merged_doc_evidence.py``.
"""
from __future__ import annotations

import re

ASSOCIATION_BASIS = "timeline-cross-reference"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_KNOWN_KEYS = frozenset(
    {
        "source_pr_number",
        "linked_issue_number",
        "association_basis",
        "merge_commit_sha",
        "merged",
        "merge_commit_in_evaluated_base",
        "declared_required_docs",
        "files",
    }
)


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_str_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def validate_record(
    record: object, *, linked_issue: int | None, required_docs: list[str]
) -> str | None:
    """Return ``None`` for a valid record, otherwise a stable reason code.

    ``linked_issue`` is ``None`` when the current PR has no unambiguous
    report-only association; merged evidence can never satisfy docs then.
    """
    if not isinstance(record, dict):
        return "not-a-dict"
    if set(record) != _KNOWN_KEYS:
        return "unexpected-keys"
    if not _is_positive_int(record["source_pr_number"]):
        return "bad-source-pr"
    if not _is_positive_int(record["linked_issue_number"]):
        return "bad-linked-issue"
    if linked_issue is None or record["linked_issue_number"] != linked_issue:
        return "linked-issue-mismatch"
    if record["association_basis"] != ASSOCIATION_BASIS:
        return "bad-association-basis"
    merge_sha = record["merge_commit_sha"]
    if not isinstance(merge_sha, str) or not SHA_RE.fullmatch(merge_sha):
        return "bad-merge-sha"
    if record["merged"] is not True:
        return "not-merged"
    if record["merge_commit_in_evaluated_base"] is not True:
        return "merge-not-in-base"
    declared = record["declared_required_docs"]
    if not _is_str_list(declared) or declared != list(required_docs):
        return "stale-declarations"
    files = record["files"]
    if not _is_str_list(files) or not files or not all(files):
        return "bad-files"
    return None


def valid_records(
    records: object, *, linked_issue: int | None, required_docs: list[str]
) -> tuple[list[dict], list[str]]:
    """Split raw records into valid records and sorted stable invalid reasons."""
    if not isinstance(records, (list, tuple)):
        return [], ["merged-docs-evidence-not-a-list"]
    valid: list[dict] = []
    reasons: set[str] = set()
    for record in records:
        reason = validate_record(record, linked_issue=linked_issue, required_docs=required_docs)
        if reason is None:
            valid.append(record)
        else:
            reasons.add(f"merged-docs-evidence-invalid:{reason}")
    return valid, sorted(reasons)
