"""Read-only GitHub acquisition for the #2766 mission-reliability measurement.

This module freezes a bounded mission population and normalizes it into the
mission records consumed by ``derive.derive_mission_reliability``. It is
read-only by construction: the caller injects a ``read_json(path, params)``
callable that performs HTTP GET, and this module contains no write path, no
mutation helper, and no credential handling.

Issue<->PR linkage reuses the canonical parser from
``scripts.agent_os_issue_acceptance.parse_pr`` (``parse_linked_issue``) plus
the repository's ``agent/<issue>-<slug>`` branch convention; no closing-keyword
grammar is redefined here.

Fields that have no durable GitHub evidence (user interventions,
cross-chat continuations, persisted requested/delivered counts, truthful
terminal state, exact-head terminal validation timestamps) are left as
``None``/``"unknown"`` so that derivation reports them as unknown rather
than estimating them. Exact terminal truthfulness, CI/build/validation timing
(#520), Code Mode host lifecycle (#2753), and conversational-test metadata
(#2744) remain with their owners.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.agent_os_issue_acceptance.parse_pr import parse_linked_issue  # noqa: E402

ReadJson = Callable[[str, Mapping[str, Any] | None], Any]

_SCHEMA_VERSION = "2766-mission-records.v1"
_DEFAULT_MAX_PR_PAGES = 10
_DEFAULT_PR_PER_PAGE = 100


def _agent_branch_issue(head_ref: object, repository: str, owner: str) -> int | None:
    """Recover an issue number from an ``agent/<issue>-<slug>`` branch name."""
    import re

    if type(head_ref) is not str:
        return None
    match = re.fullmatch(r"agent/(\d+)-[a-z0-9-]+", head_ref)
    if not match:
        return None
    return int(match.group(1))


def _pr_to_record(pr: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "number": pr.get("number"),
        "created_at": pr.get("created_at"),
        "merged": pr.get("merged") is True,
        "merged_at": pr.get("merged_at"),
        "repair": False,
        "first_terminal_validation_at": None,
        "head_ref": (pr.get("head") or {}).get("ref") if isinstance(pr.get("head"), Mapping) else None,
    }


def acquire_mission_records(
    read_json: ReadJson,
    *,
    owner: str,
    repository: str,
    issue_numbers: Sequence[int],
    admitted_map: Mapping[int, Mapping[str, Any]] | None = None,
    max_pr_pages: int = _DEFAULT_MAX_PR_PAGES,
) -> dict[str, Any]:
    """Freeze and normalize a bounded mission population read-only.

    ``issue_numbers`` is the exact frozen population (per the #2766 handoff).
    ``admitted_map`` optionally carries caller-frozen admission evidence per
    issue: ``{issue_number: {"admitted": bool, "admitted_at": iso}}``.
    """
    if not callable(read_json):
        raise TypeError("read_json must be a callable")
    if type(owner) is not str or not owner:
        raise TypeError("owner must be a non-empty string")
    if type(repository) is not str or not repository:
        raise TypeError("repository must be a non-empty string")
    numbers = list(dict.fromkeys(issue_numbers))
    for number in numbers:
        if type(number) is not int:
            raise TypeError("issue_numbers must contain ints")

    repo_path = f"/repos/{owner}/{repository}"

    # Bounded read of the PR universe; linkage is derived, never mutated.
    pull_requests: list[Mapping[str, Any]] = []
    page = 1
    while page <= max_pr_pages:
        prs = read_json(
            f"{repo_path}/pulls",
            {"state": "all", "per_page": _DEFAULT_PR_PER_PAGE, "page": page,
             # Newest first: the bounded window covers recent PRs; the
             # population is frozen by issue, so linkage needs the recent
             # PR universe, not the oldest thousand.
             "sort": "created", "direction": "desc"},
        )
        if not isinstance(prs, list):
            raise TypeError("GitHub /pulls response must be a JSON array")
        pull_requests.extend(prs)
        if len(prs) < _DEFAULT_PR_PER_PAGE:
            break
        page += 1

    linked: dict[int, list[Mapping[str, Any]]] = {n: [] for n in numbers}
    for pr in pull_requests:
        if not isinstance(pr, Mapping):
            continue
        body = pr.get("body") if type(pr.get("body")) is str else ""
        title = pr.get("title") if type(pr.get("title")) is str else ""
        target = parse_linked_issue(body, title)
        if target is None and isinstance(pr.get("head"), Mapping):
            target = _agent_branch_issue(pr["head"].get("ref"), repository, owner)
        if target in linked:
            linked[target].append(pr)

    records: list[dict[str, Any]] = []
    for number in numbers:
        issue = read_json(f"{repo_path}/issues/{number}", None)
        if not isinstance(issue, Mapping):
            raise TypeError(f"GitHub issue {number} response must be a JSON object")
        # The /pulls list view does not carry merged/merged_at; resolve the
        # detail only for PRs linked to the frozen population (bounded).
        prs: list[Mapping[str, Any]] = []
        for pr in sorted(
            linked[number],
            key=lambda p: (p.get("created_at") or "", p.get("number") or 0),
        ):
            detail = read_json(f"{repo_path}/pulls/{pr.get('number')}", None)
            prs.append(detail if isinstance(detail, Mapping) else pr)
        pr_records = [_pr_to_record(pr) for pr in prs]
        for follow_up in pr_records[1:]:
            follow_up["repair"] = True
        admission = (admitted_map or {}).get(number) or {}
        records.append(
            {
                "issue_number": number,
                "admitted": admission.get("admitted") is True,
                "admitted_at": admission.get("admitted_at"),
                "issue_state": issue.get("state") if issue.get("state") in ("open", "closed") else "unknown",
                "issue_closed_at": issue.get("closed_at"),
                "implementation_prs": pr_records,
                "requested_items": None,
                "delivered_items": None,
                "terminal_state": "unknown",
                "user_interventions": None,
                "continuation_prompts": None,
                "bug_family": None,
                "prior_completed_fix_issue": None,
                "finding_issue": None,
                "retest_at": None,
            }
        )

    return {
        "schema_version": _SCHEMA_VERSION,
        "repository": f"{owner}/{repository}",
        "frozen_issue_numbers": numbers,
        "records": records,
    }
