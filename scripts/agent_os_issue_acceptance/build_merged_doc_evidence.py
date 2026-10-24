"""Build merged-documentation evidence for the acceptance workflow (#3719).

Read-only producer, run by ``agent-os-issue-acceptance-report.yml`` before
the checker. It never approves, merges, labels, closes, or mutates
anything: every ``gh`` call below is a REST read (``gh api`` GET).

Discovery, in order, for the evaluated issue:

1. Fetch the issue timeline and collect GitHub-generated cross-referenced
   PR numbers from this repository.
2. For each candidate PR other than the evaluated PR, fetch its merged
   state, merge commit, title, body, and file list (REST reads only).
3. Keep a candidate only when all of these hold:
   - it is merged (``merged_at`` present, merge commit SHA is 40 hex);
   - its merge commit is the merge-base of the evaluated PR's base and
     the base is not behind it (GitHub compare API), so the merged
     documentation is present in the evaluated tree;
   - its bare issue references (via the canonical ``parse_linked_issue_result``
     parser, not ad-hoc text search) contain exactly one distinct issue
     number, equal to the evaluated issue.
4. Emit one record per qualifying PR, with ``declared_required_docs`` set
   to the current issue's declarations (the checker's freshness gate).

A candidate whose reads fail is skipped. Any other failure, missing input,
or empty candidate set writes ``[]`` and exits 0: the checker then runs
with current-PR coverage only, so a producer failure degrades to a failing
docs check, never to a pass. The checker re-validates every record, so
this script's output is evidence, not a decision.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .merged_docs import ASSOCIATION_BASIS, SHA_RE
from .parse_issue import project_issue_metadata, scan_issue_metadata
from .parse_pr import parse_linked_issue_result

def cross_referenced_prs(timeline: object, repository: str) -> set[int]:
    """Return this repository's PR numbers cross-referenced on an issue timeline."""
    pr_numbers: set[int] = set()
    if not isinstance(timeline, list):
        return pr_numbers
    for event in timeline:
        if not isinstance(event, dict) or event.get("event") != "cross-referenced":
            continue
        source = event.get("source")
        issue = source.get("issue") if isinstance(source, dict) else None
        source_repository = issue.get("repository") if isinstance(issue, dict) else None
        if (
            isinstance(source_repository, dict)
            and source_repository.get("full_name") == repository
            and isinstance(issue.get("pull_request"), dict)
        ):
            number = issue.get("number")
            if isinstance(number, int) and number > 0:
                pr_numbers.add(number)
    return pr_numbers


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


class _Gh:
    """Read-only ``gh api`` (REST) reader; replaceable in tests."""

    def get(self, path: str) -> object:
        return self._run(["gh", "api", path])

    def get_all(self, path: str) -> list:
        """Every item of a paginated list endpoint (pages slurped, then flattened)."""
        pages = self._run(["gh", "api", path, "--paginate", "--slurp"])
        if not isinstance(pages, list) or not all(isinstance(page, list) for page in pages):
            raise RuntimeError(f"gh api {path} returned non-list pages")
        return [item for page in pages for item in page]

    @staticmethod
    def _run(command: list[str]) -> object:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"{' '.join(command[:3])} failed: {result.stderr.strip()[:200]}")
        return json.loads(result.stdout or "null")


def _candidate_record(
    *, gh: _Gh, repository: str, issue_number: int, pr_number: int, base_sha: str
) -> dict | None:
    pr = gh.get(f"repos/{repository}/pulls/{pr_number}")
    if not isinstance(pr, dict):
        return None
    merge_sha = pr.get("merge_commit_sha")
    if not pr.get("merged_at") or not isinstance(merge_sha, str) or not SHA_RE.fullmatch(merge_sha):
        return None
    if bare_issue_targets(pr.get("body") or "", pr.get("title") or "") != {issue_number}:
        return None
    if not is_merge_ancestor(gh.get(f"repos/{repository}/compare/{merge_sha}...{base_sha}?per_page=1"), merge_sha):
        return None
    paths = [item.get("filename") for item in gh.get_all(f"repos/{repository}/pulls/{pr_number}/files") if isinstance(item, dict)]
    if not paths or not all(isinstance(path, str) and path for path in paths):
        return None
    return {
        "source_pr_number": pr_number,
        "linked_issue_number": issue_number,
        "association_basis": ASSOCIATION_BASIS,
        "merge_commit_sha": merge_sha,
        "merged": True,
        "merge_commit_in_evaluated_base": True,
        "files": paths,
    }


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
    candidates = cross_referenced_prs(gh.get_all(f"repos/{repository}/issues/{issue_number}/timeline"), repository)
    records: list[dict] = []
    for pr_number in sorted(candidates - {current_pr_number}):
        try:
            record = _candidate_record(
                gh=gh, repository=repository, issue_number=issue_number, pr_number=pr_number, base_sha=base_sha
            )
        except Exception:  # unreadable or malformed candidate: no coverage from it
            continue
        if record is not None:
            records.append({**record, "declared_required_docs": list(required_docs)})
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
        records = build_records(
            gh=_Gh(),
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
