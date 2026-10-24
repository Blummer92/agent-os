"""Build merged-documentation evidence for the acceptance workflow (#3719).

Read-only producer, run by ``agent-os-issue-acceptance-report.yml`` before
the checker. It never approves, merges, labels, closes, or mutates
anything: every ``gh`` call below is a read (``gh api`` GET, ``gh pr view``).

Discovery, in order, for the evaluated issue:

1. Fetch the issue timeline and collect GitHub-generated associations:
   cross-referenced PR numbers, and referenced commit SHAs.
2. For each candidate PR other than the evaluated PR, fetch its merged
   state, merge commit, file list, title, and body via ``gh pr view``.
3. Keep a candidate only when all of these hold:
   - it is merged (``mergedAt`` present, merge commit SHA is 40 hex);
   - its merge commit is the merge-base of the evaluated PR's base and
     the base is not behind it (GitHub compare API), so the merged
     documentation is present in the evaluated tree;
   - its bare issue references (via the canonical ``parse_linked_issue_result``
     parser, not ad-hoc text search) contain exactly one distinct issue
     number, equal to the evaluated issue;
   - its timeline association is a cross-reference to that PR or a
     referenced merge commit -- prose or a cross-reference alone is not
     enough, and neither is a merge alone.
4. Emit one record per qualifying PR, with ``declared_required_docs`` set
   to the current issue's declarations (the checker's freshness gate).

Any API failure, missing input, or empty candidate set writes ``[]`` and
exits 0: the checker then runs with current-PR coverage only, so a
producer failure degrades to a failing docs check, never to a pass.
The checker re-validates every record, so this script's output is
evidence, not a decision.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from .parse_issue import project_issue_metadata, scan_issue_metadata
from .parse_pr import parse_linked_issue_result

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def timeline_associations(timeline: object) -> tuple[set[int], set[str]]:
    """Return (cross-referenced PR numbers, referenced commit SHAs)."""
    pr_numbers: set[int] = set()
    commit_shas: set[str] = set()
    if not isinstance(timeline, list):
        return pr_numbers, commit_shas
    for event in timeline:
        if not isinstance(event, dict):
            continue
        kind = event.get("event")
        if kind == "cross-referenced":
            source = event.get("source")
            if isinstance(source, dict):
                issue = source.get("issue")
                if isinstance(issue, dict) and isinstance(issue.get("pull_request"), dict):
                    number = issue.get("number")
                    if isinstance(number, int) and number > 0:
                        pr_numbers.add(number)
        elif kind == "referenced":
            commit_id = event.get("commit_id")
            if isinstance(commit_id, str) and _SHA_RE.fullmatch(commit_id):
                commit_shas.add(commit_id)
    return pr_numbers, commit_shas


def is_merge_ancestor(compare: object, merge_sha: str) -> bool:
    """True when ``merge_sha`` is the merge-base and the base is not behind it."""
    if not isinstance(compare, dict):
        return False
    merge_base = compare.get("merge_base_commit")
    base_sha = merge_base.get("sha") if isinstance(merge_base, dict) else None
    behind = compare.get("behind_by")
    return base_sha == merge_sha and behind == 0


def bare_issue_targets(pr_body: str, pr_title: str) -> set[int]:
    """Distinct bare issue numbers from the canonical linked-issue parser."""
    result = parse_linked_issue_result(pr_body or "", pr_title or "")
    return {
        candidate.issue_number
        for candidate in result.bare_references
        if candidate.repository is None
    }


def association_basis(
    *, pr_number: int, merge_sha: str, cross_referenced: set[int], referenced: set[str]
) -> str | None:
    if pr_number in cross_referenced:
        return "timeline-cross-reference"
    if merge_sha in referenced:
        return "timeline-referenced-merge-commit"
    return None


class _Gh:
    """Thin ``gh`` wrapper; replaceable in tests."""

    def __init__(self, repository: str):
        self.repository = repository

    def api(self, path: str) -> object:
        result = subprocess.run(
            ["gh", "api", path, "--paginate"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"gh api {path} failed: {result.stderr.strip()[:200]}")
        return json.loads(result.stdout or "null")

    def pr_view(self, pr_number: int) -> dict:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "view",
                str(pr_number),
                "--repo",
                self.repository,
                "--json",
                "number,mergedAt,mergeCommit,files,body,title",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"gh pr view {pr_number} failed: {result.stderr.strip()[:200]}")
        data = json.loads(result.stdout or "{}")
        if not isinstance(data, dict):
            raise RuntimeError(f"gh pr view {pr_number} returned non-object")
        return data


def build_records(
    *,
    gh: _Gh,
    repository: str,
    issue_number: int,
    current_pr_number: int,
    base_sha: str,
    required_docs: list[str],
) -> list[dict]:
    if not required_docs:
        return []
    timeline = gh.api(f"repos/{repository}/issues/{issue_number}/timeline")
    cross_referenced, referenced = timeline_associations(timeline)
    # This producer discovers candidates from cross-references; the checker
    # also accepts the timeline-referenced-merge-commit basis for producers
    # that can discover a PR by its merge commit.
    records: list[dict] = []
    for candidate in sorted(cross_referenced | set()):
        if candidate == current_pr_number:
            continue
        pr = gh.pr_view(candidate)
        merged_at = pr.get("mergedAt")
        merge_commit = pr.get("mergeCommit") or {}
        merge_sha = merge_commit.get("oid") if isinstance(merge_commit, dict) else None
        if not merged_at or not isinstance(merge_sha, str) or not _SHA_RE.fullmatch(merge_sha):
            continue
        basis = association_basis(
            pr_number=candidate,
            merge_sha=merge_sha,
            cross_referenced=cross_referenced,
            referenced=referenced,
        )
        if basis is None:
            continue
        if bare_issue_targets(pr.get("body") or "", pr.get("title") or "") != {issue_number}:
            continue
        try:
            compare = gh.api(f"repos/{repository}/compare/{merge_sha}...{base_sha}")
        except RuntimeError:
            continue
        if not is_merge_ancestor(compare, merge_sha):
            continue
        files = pr.get("files") or []
        paths = [item.get("path") for item in files if isinstance(item, dict)]
        if not all(isinstance(path, str) and path for path in paths) or not paths:
            continue
        records.append(
            {
                "source_pr_number": candidate,
                "linked_issue_number": issue_number,
                "association_basis": basis,
                "merge_commit_sha": merge_sha,
                "merged": True,
                "merge_commit_in_evaluated_base": True,
                "declared_required_docs": list(required_docs),
                "files": paths,
            }
        )
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build merged-docs evidence JSON (#3719).")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--issue-number", type=int, required=True)
    parser.add_argument("--current-pr-number", type=int, required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--issue-body-file", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    def _write_empty() -> int:
        Path(args.output).write_text("[]\n", encoding="utf-8")
        return 0

    try:
        issue_body = Path(args.issue_body_file).read_text(encoding="utf-8")
        metadata = project_issue_metadata(scan_issue_metadata(issue_body))
        if not metadata.present or not metadata.required_docs:
            return _write_empty()
        records = build_records(
            gh=_Gh(args.repository),
            repository=args.repository,
            issue_number=args.issue_number,
            current_pr_number=args.current_pr_number,
            base_sha=args.base_sha,
            required_docs=list(metadata.required_docs),
        )
    except Exception as error:  # fail closed: no merged coverage on any failure
        print(f"merged-docs producer failed (fail closed, no coverage): {error}", file=sys.stderr)
        return _write_empty()
    Path(args.output).write_text(json.dumps(records, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
