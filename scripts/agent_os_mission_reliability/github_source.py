"""Acquire complete frozen records via an injected JSON reader; never print or read credentials."""

import re
from collections.abc import Callable, Mapping
from typing import Any

from scripts.agent_os_issue_acceptance.parse_pr import parse_linked_issue

from .errors import ReadError, ValidationError
from .http_client import JsonPage
from .inputs import DEFAULT_PR_PAGES, Population, freeze_population, positive_issue

ReadJson = Callable[[str, Mapping[str, Any] | None], Any]
_SCHEMA_VERSION = "2766-mission-records.v1"
_PR_PAGE_SIZE = 100


def _unpack(value):
    """Separate real HTTP pagination metadata from compatibility fixture values."""
    return (value.value, value.has_next) if isinstance(value, JsonPage) else (value, None)


def _identified_detail(read_json, path, number):
    """Read one exact object and reject absent, drifting, or paginated identity."""
    item, has_next = _unpack(read_json(path, None))
    if has_next or not isinstance(item, Mapping) or (
        not positive_issue(item.get("number")) or item["number"] != number
    ):
        raise ReadError("identity_mismatch", "GitHub detail did not match the requested identity.", "github")
    if "/issues/" in path and "pull_request" in item:
        raise ReadError("not_an_issue", "Frozen issue number identifies a PR, not an issue.", "issues")
    return item


def _linked_issue(pr):
    """Use the canonical closing parser, then the documented branch heuristic."""
    body = pr.get("body") if type(pr.get("body")) is str else ""
    title = pr.get("title") if type(pr.get("title")) is str else ""
    try:
        target = parse_linked_issue(body, title)
    except (TypeError, ValueError, OverflowError):
        raise ReadError("invalid_linkage", "GitHub PR linkage could not be read.", "github") from None
    if target is not None:
        return target
    head = pr.get("head")
    ref = head.get("ref") if isinstance(head, Mapping) else None
    match = re.fullmatch(r"agent/([0-9]{1,10})-[a-z0-9-]+", ref) if type(ref) is str else None
    number = int(match.group(1)) if match else None
    return number if positive_issue(number) else None


def _pr_pages(read_json, population):
    """Yield valid complete PR pages or fail rather than silently truncate."""
    for page in range(1, population.max_pr_pages + 1):
        raw = read_json(f"/repos/{population.repository}/pulls", {
            "state": "all", "per_page": _PR_PAGE_SIZE, "page": page,
            "sort": "created", "direction": "desc",
        })
        values, has_next = _unpack(raw)
        if not isinstance(values, list) or len(values) > _PR_PAGE_SIZE or (has_next and not values):
            raise ReadError("invalid_pr_page", "GitHub returned an invalid PR page.", "github")
        yield values
        # Direct callers may still supply arrays instead of HTTP envelopes.
        if has_next is False or (has_next is None and len(values) < _PR_PAGE_SIZE):
            return
    raise ReadError("incomplete_pr_population", "PR pagination exceeds the frozen read limit.", "github")


def _linked_prs(read_json, population):
    """Collect only requested issues' PRs and reject duplicate page identities."""
    linked = {n: [] for n in population.issues}
    seen = set()
    for page in _pr_pages(read_json, population):
        for pr in page:
            if not isinstance(pr, Mapping) or not positive_issue(pr.get("number")):
                raise ReadError("invalid_pr_identity", "GitHub PR entry has no valid number.", "github")
            number = pr["number"]
            if number in seen:
                raise ReadError("duplicate_pr", "GitHub PR pagination repeated a number.", "github")
            seen.add(number)
            target = _linked_issue(pr)
            if target in linked:
                linked[target].append(pr)
    return linked


def _optional_text(value):
    """Keep immutable strings, never retaining unexpected provider containers."""
    return value if type(value) is str else None


def _pr_record(pr, repair):
    """Project immutable scalar PR evidence without guessing merge status."""
    if type(pr.get("merged")) is not bool:
        raise ReadError("invalid_pr_detail", "GitHub PR detail has no boolean merge status.", "github")
    head = pr.get("head")
    return {
        "number": pr["number"], "created_at": _optional_text(pr.get("created_at")),
        "merged": pr["merged"], "merged_at": _optional_text(pr.get("merged_at")),
        "repair": repair, "first_terminal_validation_at": None,
        "head_ref": _optional_text(head.get("ref")) if isinstance(head, Mapping) else None,
    }


def _issue_record(issue, prs, admitted_at):
    """Build one detached, evidence-honest mission record."""
    state = issue.get("state")
    return {
        "issue_number": issue["number"], "admitted": admitted_at is not None,
        "admitted_at": admitted_at, "issue_state": state if state in ("open", "closed") else "unknown",
        "issue_closed_at": _optional_text(issue.get("closed_at")),
        "implementation_prs": prs, "requested_items": None, "delivered_items": None,
        "terminal_state": "unknown", "user_interventions": None, "continuation_prompts": None,
        "bug_family": None, "prior_completed_fix_issue": None, "finding_issue": None, "retest_at": None,
    }


def _details(read_json, path, prs):
    """Read linked PR detail oldest-first and mark later records as repairs."""
    order = sorted(prs, key=lambda p: (_optional_text(p.get("created_at")) or "", p["number"]))
    return [
        _pr_record(_identified_detail(read_json, f"{path}/pulls/{pr['number']}", pr["number"]), i > 0)
        for i, pr in enumerate(order)
    ]


def acquire_frozen_records(read_json: ReadJson, population: Population):
    """Acquire an exact complete snapshot from already validated frozen input."""
    if not callable(read_json):
        raise ValidationError("invalid_reader", "Expected a callable read-only reader.", "github")
    linked = _linked_prs(read_json, population)
    path = f"/repos/{population.repository}"
    admitted = dict(population.admitted)
    records = [
        _issue_record(_identified_detail(read_json, f"{path}/issues/{number}", number),
                      _details(read_json, path, linked[number]), admitted.get(number))
        for number in population.issues
    ]
    return {"schema_version": _SCHEMA_VERSION, "repository": population.repository,
            "frozen_issue_numbers": list(population.issues), "records": records}


def acquire_mission_records(
    read_json: ReadJson, *, owner: str, repository: str, issue_numbers,
    admitted_map=None, max_pr_pages: int = DEFAULT_PR_PAGES,
):
    """Compatibility entrypoint: freeze exactly the caller's inputs, then read them."""
    return acquire_frozen_records(
        read_json, freeze_population(owner, repository, issue_numbers, admitted_map, max_pr_pages),
    )
