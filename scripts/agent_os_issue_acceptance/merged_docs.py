"""Cumulative required-documentation evidence (#3719).

The per-PR required-docs contract is preserved: a declaration is satisfied
by a file changed in the currently evaluated PR, exactly as before. A
declaration may *also* be satisfied by a merged PR, but only through a
verified record that passes every gate below. No single gate is sufficient
on its own, and PR prose or a cross-reference alone is never sufficient:

1. ``merged`` is exactly ``True`` (GitHub API ``mergedAt`` / ``merged``).
2. ``association_basis`` is a GitHub-timeline association, not a free-text
   claim: ``timeline-cross-reference`` (the merged PR appears as a
   cross-referenced PR on the evaluated issue's timeline) or
   ``timeline-referenced-merge-commit`` (its merge commit appears as a
   referenced commit on that timeline).
3. The record's ``linked_issue_number`` equals the evaluated issue number
   (the report-only association for the current PR, see ``policy``).
4. ``merge_commit_in_evaluated_base`` is exactly ``True``: the producer
   verified via the GitHub compare API that the merge commit is the
   merge-base of the evaluated PR's base and that the base is not behind
   it, so the merged documentation is actually present in the evaluated
   tree.
5. ``declared_required_docs`` equals the current issue's ``required_docs``
   list exactly, so evidence recorded against an older declaration set
   cannot satisfy a changed issue (freshness).
6. At least one file in ``files`` matches the declaration under the
   canonical ``declared_path_matches`` contract.

An invalid record simply does not count: it never broadens coverage, never
turns a failure into a pass, and never turns a pass into a failure on its
own. A declaration with no current-PR match and no valid merged match
remains ``unmatched``. This module is offline and pure: it validates the
record the workflow producer built; it performs no GitHub or git access.
The producer lives in ``build_merged_doc_evidence.py``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .path_contract import DeclaredPathError, declared_path_matches

_ASSOCIATION_BASES = frozenset(
    {
        "timeline-cross-reference",
        "timeline-referenced-merge-commit",
    }
)
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
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


@dataclass(frozen=True)
class MergedDocEvidence:
    """A fully validated merged-documentation evidence record."""

    source_pr_number: int
    linked_issue_number: int
    association_basis: str
    merge_commit_sha: str
    files: tuple[str, ...]
    declared_required_docs: tuple[str, ...]


def validate_record(
    record: object, *, linked_issue: int | None, required_docs: list[str]
) -> tuple[MergedDocEvidence | None, str | None]:
    """Validate one raw record against the evaluated issue, or fail closed.

    Returns ``(evidence, None)`` on success and ``(None, reason_code)`` on
    any failure. ``linked_issue`` is ``None`` when the current PR has no
    unambiguous report-only association; merged evidence can never satisfy
    docs in that case.
    """
    if not isinstance(record, dict):
        return None, "not-a-dict"
    if set(record) != _KNOWN_KEYS:
        return None, "unexpected-keys"
    source_pr = record["source_pr_number"]
    if not isinstance(source_pr, int) or isinstance(source_pr, bool) or source_pr <= 0:
        return None, "bad-source-pr"
    issue_number = record["linked_issue_number"]
    if not isinstance(issue_number, int) or isinstance(issue_number, bool):
        return None, "bad-linked-issue"
    if linked_issue is None or issue_number != linked_issue:
        return None, "linked-issue-mismatch"
    if record["association_basis"] not in _ASSOCIATION_BASES:
        return None, "bad-association-basis"
    merge_sha = record["merge_commit_sha"]
    if not isinstance(merge_sha, str) or not _SHA_RE.fullmatch(merge_sha):
        return None, "bad-merge-sha"
    if record["merged"] is not True:
        return None, "not-merged"
    if record["merge_commit_in_evaluated_base"] is not True:
        return None, "merge-not-in-base"
    declared = record["declared_required_docs"]
    if (
        not isinstance(declared, list)
        or not all(isinstance(item, str) for item in declared)
        or list(declared) != list(required_docs)
    ):
        return None, "stale-declarations"
    files = record["files"]
    if (
        not isinstance(files, list)
        or not files
        or not all(isinstance(item, str) and item for item in files)
    ):
        return None, "bad-files"
    return (
        MergedDocEvidence(
            source_pr_number=source_pr,
            linked_issue_number=issue_number,
            association_basis=str(record["association_basis"]),
            merge_commit_sha=merge_sha,
            files=tuple(files),
            declared_required_docs=tuple(declared),
        ),
        None,
    )


def valid_records(
    records: object, *, linked_issue: int | None, required_docs: list[str]
) -> tuple[list[MergedDocEvidence], list[str]]:
    """Split raw records into valid evidence and stable invalid reasons."""
    valid: list[MergedDocEvidence] = []
    reasons: list[str] = []
    if not isinstance(records, (list, tuple)):
        return valid, ["merged-docs-evidence-not-a-list"]
    for record in records:
        evidence, reason = validate_record(
            record, linked_issue=linked_issue, required_docs=required_docs
        )
        if evidence is not None:
            valid.append(evidence)
        elif reason is not None:
            reasons.append(f"merged-docs-evidence-invalid:{reason}")
    return valid, sorted(set(reasons))


def merged_source_for(
    declaration: str, records: list[MergedDocEvidence]
) -> MergedDocEvidence | None:
    """Return the first valid record covering ``declaration``, if any."""
    for record in records:
        for path in record.files:
            try:
                if declared_path_matches(path, declaration):
                    return record
            except DeclaredPathError:
                continue
    return None
