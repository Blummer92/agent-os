"""Select authoritative exact-current-main aggregate evidence (#3461).

The ``Project exact-current main health`` workflow step queries the check-runs
attached to the current main SHA and must choose the check that is genuine
main-health evidence.  A bare name+SHA match is not enough: failed wrong-ref
``final-candidate`` workflow_dispatch runs can attach ``Run aggregate
validation`` checks to the main SHA, and the newest-by-start-time selection
would then pick one of them, poisoning main-health admission for unrelated
PRs (#3461).

A candidate check run is authoritative main-health evidence only when its
originating workflow run is:

* a ``push`` to main, or
* a ``workflow_dispatch`` diagnostic issued by the validation workflow itself
  (``github-actions[bot]``) bound to the exact main SHA — the sanctioned
  "Recover missing exact-current main aggregate evidence" path.

Everything else (human-dispatched runs, runs bound to a different SHA,
unresolvable provenance) is excluded fail-closed: the selector then reports
no evidence and the caller keeps its existing missing-evidence behavior.
A genuine failing main aggregate is never hidden — a failed ``push`` check
is authoritative and is still selected.

Reads the ``/commits/{sha}/check-runs`` API payload from stdin.  Prints the
selected check as JSON in the shape the workflow consumes
(``{status, conclusion, details_url, started_at, completed_at}``) or ``{}``
when no authoritative check exists.  With ``--count`` prints the number of
authoritative candidates instead (used by the recovery step).

Environment:
  MAIN_HEALTH_SHA     exact current main SHA the evidence must be bound to
  GITHUB_REPOSITORY   owner/repo, used to resolve check -> workflow run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any

CHECK_NAME = "Run aggregate validation"
OUTPUT_FIELDS = ("status", "conclusion", "details_url", "started_at", "completed_at")

_RUN_ID_RE = re.compile(r"actions/runs/(\d+)")

# The only sanctioned non-push origin of main-health evidence: a diagnostic
# dispatch issued by the validation workflow itself via its GITHUB_TOKEN.
SANCTIONED_DISPATCH_ACTOR = "github-actions[bot]"


def extract_run_id(details_url: object) -> str | None:
    """Return the workflow run id embedded in a check's details_url, if any."""
    if not isinstance(details_url, str):
        return None
    match = _RUN_ID_RE.search(details_url)
    return match.group(1) if match else None


def fetch_run_provenance(repo: str, run_id: str) -> Mapping[str, Any] | None:
    """Resolve one workflow run's event/head_sha/actor via the GitHub API.

    Returns None when the run cannot be resolved — the caller treats that
    candidate as non-authoritative (fail-closed), never as evidence.
    """
    try:
        completed = subprocess.run(
            [
                "gh",
                "api",
                f"/repos/{repo}/actions/runs/{run_id}",
                "--jq",
                "{event, head_sha, actor: .triggering_actor.login}",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def is_authoritative(
    provenance: Mapping[str, Any] | None, main_sha: str
) -> bool:
    """Decide whether a resolved workflow run is authoritative main evidence."""
    if not isinstance(provenance, Mapping):
        return False
    if provenance.get("head_sha") != main_sha:
        return False
    event = provenance.get("event")
    if event == "push":
        return True
    if event == "workflow_dispatch" and provenance.get("actor") == SANCTIONED_DISPATCH_ACTOR:
        return True
    return False


def authoritative_checks(
    check_runs: Sequence[Mapping[str, Any]],
    main_sha: str,
    resolve_run: Callable[[str], Mapping[str, Any] | None],
) -> list[Mapping[str, Any]]:
    """Return every candidate check run that is authoritative main evidence."""
    authoritative: list[Mapping[str, Any]] = []
    provenance_cache: dict[str, Mapping[str, Any] | None] = {}
    for check in check_runs:
        if not isinstance(check, Mapping):
            continue
        if check.get("name") != CHECK_NAME:
            continue
        run_id = extract_run_id(check.get("details_url"))
        if run_id is None:
            continue
        if run_id not in provenance_cache:
            provenance_cache[run_id] = resolve_run(run_id)
        if not is_authoritative(provenance_cache[run_id], main_sha):
            continue
        authoritative.append(check)
    return authoritative


def select_authoritative_check(
    check_runs: Sequence[Mapping[str, Any]],
    main_sha: str,
    resolve_run: Callable[[str], Mapping[str, Any] | None],
) -> Mapping[str, Any] | None:
    """Select the newest authoritative check run, or None when there is none.

    ``resolve_run`` maps a workflow run id to its provenance mapping (as
    returned by :func:`fetch_run_provenance`); it is a parameter so the pure
    selection logic stays testable without subprocesses.
    """
    candidates = authoritative_checks(check_runs, main_sha, resolve_run)
    if not candidates:
        return None
    # Same ordering as the previous inline jq: ascending by started_at, take last.
    newest = sorted(candidates, key=lambda c: str(c.get("started_at") or ""))[-1]
    return {field: newest.get(field) for field in OUTPUT_FIELDS}


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Select authoritative exact-current-main aggregate evidence (#3461)."
    )
    parser.add_argument(
        "--count",
        action="store_true",
        help="Print the number of authoritative candidates instead of the selected check.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    main_sha = os.environ.get("MAIN_HEALTH_SHA", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"main_health_check_selector: invalid JSON on stdin: {exc}", file=sys.stderr)
        return 2
    check_runs = payload.get("check_runs", [])
    if not isinstance(check_runs, list):
        print("main_health_check_selector: expected a check-runs payload", file=sys.stderr)
        return 2
    if not main_sha or not repo:
        # Without the binding inputs no candidate can be proven authoritative.
        print(
            "main_health_check_selector: MAIN_HEALTH_SHA/GITHUB_REPOSITORY unset; "
            "reporting no evidence (fail-closed)",
            file=sys.stderr,
        )
        selected: Mapping[str, Any] | None = None
        authoritative_total = 0
    else:

        def resolve_run(run_id: str) -> Mapping[str, Any] | None:
            return fetch_run_provenance(repo, run_id)

        authoritative = authoritative_checks(check_runs, main_sha, resolve_run)
        authoritative_total = len(authoritative)
        selected = select_authoritative_check(check_runs, main_sha, resolve_run)
    if args.count:
        print(authoritative_total)
    else:
        print(json.dumps(dict(selected) if selected is not None else {}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
