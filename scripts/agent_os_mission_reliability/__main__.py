"""Read-only CLI: freeze a bounded issue population, acquire records, print metrics.

Usage (from the repository root):

    python -m scripts.agent_os_mission_reliability --owner Blummer92 \\
        --repo agent-os --issues 2775,2776 --admitted 2775:2026-09-21T19:56:33Z

Only HTTP GET requests are issued. Authentication is optional: set
``GITHUB_TOKEN`` in the environment to raise the API rate limit; the token
is sent only as an ``Authorization`` header and never logged or persisted.

``--issues`` is the exact frozen population (per the #2766 handoff: freeze
the population before measuring). ``--admitted`` optionally carries
``<issue>:<admitted_at ISO>`` admission evidence for issues that were
admitted missions in the window; issues not listed are recorded as
non-admitted.

Output is a single JSON object: ``{"records": ..., "report": ...}``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.agent_os_mission_reliability.derive import derive_mission_reliability
from scripts.agent_os_mission_reliability.github_source import acquire_mission_records

_API_BASE = "https://api.github.com"


class _ReadError(RuntimeError):
    """A read-only GitHub GET failed; no mutation was attempted."""


def _read_json(path: str, params: Mapping[str, Any] | None) -> Any:
    """Perform one authenticated-or-anonymous HTTP GET against api.github.com."""
    query = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
    url = _API_BASE + path + (("?" + query) if query else "")
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise _ReadError(f"GET {path} failed with HTTP {exc.code}") from exc


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument(
        "--issues",
        required=True,
        help="comma-separated frozen issue population, e.g. 2775,2776",
    )
    parser.add_argument(
        "--admitted",
        default="",
        help="comma-separated <issue>:<admitted_at ISO> admission evidence",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    issue_numbers = [int(part) for part in args.issues.split(",") if part.strip()]
    admitted_map: dict[int, dict[str, Any]] = {}
    for part in (p for p in args.admitted.split(",") if p.strip()):
        number_text, _, admitted_at = part.partition(":")
        admitted_map[int(number_text)] = {"admitted": True, "admitted_at": admitted_at or None}
    frozen = acquire_mission_records(
        _read_json,
        owner=args.owner,
        repository=args.repo,
        issue_numbers=issue_numbers,
        admitted_map=admitted_map,
    )
    window = (
        f"{args.owner}/{args.repo} frozen issues {','.join(str(n) for n in frozen['frozen_issue_numbers'])}"
    )
    report = derive_mission_reliability(frozen["records"], window=window)
    json.dump({"records": frozen, "report": report}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
