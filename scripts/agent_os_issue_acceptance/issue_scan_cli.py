from __future__ import annotations

import argparse
import json
import sys

from .github_issue_source import result_to_report, scan_repository_open_issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run report-only open issue scan.")
    parser.add_argument("--repository", required=True, help="Repository in owner/name form.")
    parser.add_argument("--token", default=None, help="Optional GitHub token for read-only access.")
    parser.add_argument("--per-page", type=int, default=100, help="GitHub API page size, 1-100.")
    args = parser.parse_args(argv)

    result = scan_repository_open_issues(args.repository, token=args.token, per_page=args.per_page)
    print(json.dumps(result_to_report(result), indent=2, sort_keys=True))
    return 0 if result.complete else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
