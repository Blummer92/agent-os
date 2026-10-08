"""Read-only Lessons Learned lifecycle metrics from durable GitHub evidence (#3418).

Sources are only the existing bounded marker comments on issues: CKR6 result
comments (`<!-- agent-os-ckr6-result:v1 -->`, posted by the ingress workflow)
and lesson application receipts (`<!-- agent-os-lesson-receipt:v1 -->`).
No database, telemetry store, Notion read or write, score, or promotion
authority is created. Unknown stays unknown; causality is never inferred.

Run: ``python -m agent_os_execution_service.lesson_learning_metrics
--repository Blummer92/agent-os --issues 3417,3418`` (HTTP GET only;
``GITHUB_TOKEN`` optional).
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
import re
from typing import Iterable, Mapping

from agent_memory_context_manager.lesson_activation_accountability import (
    load_lesson_accountability_catalog,
)

from .ckr6_github_bridge import parse_ckr6_result_comment
from .lesson_learning_loop import (
    REFINEMENT_SIGNAL_REASONS,
    parse_receipt_comment,
    receipt_key,
    verify_receipt_against_result,
)

MAX_ISSUES = 50
MAX_PAGES_PER_ISSUE = 10
_NUMBER = re.compile(r"(?:[A-Za-z][A-Za-z0-9_]*-)?([0-9]{1,9})")


def _lesson_number(lesson_id: str) -> int | None:
    match = _NUMBER.fullmatch(lesson_id)
    return int(match.group(1)) if match else None


def _accountability_by_number() -> dict[int, str]:
    """Reuse CKR12 bookkeeping keyed by lesson number.

    The checked-in CKR12 snapshot names lessons ``lesson-N`` while live
    normalization renders ``LL-N``; matching by number avoids reporting every
    lesson as drift. The prefix mismatch itself is reported, not repaired here.
    """
    result = {}
    for entry in load_lesson_accountability_catalog():
        number = _lesson_number(entry.lesson_id)
        if number is not None:
            result[number] = f"{entry.activation_class}/{entry.activation_readiness}"
    return result


def derive_lesson_metrics(comments_by_issue: Mapping[int, Iterable[Mapping[str, object]]]) -> dict[str, object]:
    """Pure derivation over already-acquired issue comments."""
    results: dict[int, dict[str, object]] = {}
    receipts: list[tuple[int, dict[str, object]]] = []
    malformed = Counter()
    for issue, comments in comments_by_issue.items():
        for comment in comments:
            body, comment_id = comment.get("body"), comment.get("id")
            if type(body) is not str or type(comment_id) is not int:
                continue
            if body.startswith("<!-- agent-os-ckr6-result:v1 -->"):
                try:
                    results[comment_id] = parse_ckr6_result_comment(body)
                except (TypeError, ValueError):
                    malformed["ckr6-result"] += 1
            elif body.startswith("<!-- agent-os-lesson-receipt:v1 -->"):
                try:
                    receipts.append((issue, parse_receipt_comment(body)))
                except (TypeError, ValueError):
                    malformed["receipt"] += 1

    by_status = Counter()
    materiality = Counter()
    rejections = Counter()
    eligibility_blocks = Counter()
    candidates = Counter()
    candidate_core = Counter()
    refinements = Counter()
    selected: dict[tuple[str, str], int] = {}
    reads = 0
    for result in results.values():
        operation, status = result.get("operation"), result.get("status")
        by_status[f"{operation}:{status}"] += 1
        if result.get("materiality_source"):
            materiality[str(result["materiality_source"])] += 1
        if result.get("notion_read_performed") or status in {"sufficient", "insufficient"}:
            reads += 1
        if status == "rejected":
            for code in result.get("reason_codes", []):
                rejections[str(code)] += 1
        for item in result.get("rejected_candidate_provenance", []) or []:
            eligibility_blocks[f"{item.get('currentness')}:{item.get('provenance')}"] += 1
        for item in result.get("selected_lessons", []) or []:
            key = (item.get("lesson_id"), item.get("source_revision"))
            selected[key] = selected.get(key, 0) + 1
        if operation == "lesson-candidate":
            candidates[str(status)] += 1
            proposal = result.get("lesson_proposal") or {}
            if proposal.get("core_identity"):
                candidate_core[proposal["core_identity"]] += 1
        if operation == "lesson-refinement":
            refinements[str(status)] += 1

    valid: dict[tuple[object, ...], dict[str, object]] = {}
    invalid = Counter()
    duplicates = 0
    conflicting = 0
    for _issue, receipt in receipts:
        result = results.get(receipt["ckr6_result_comment_id"])
        if result is None:
            invalid["receipt-result-not-found"] += 1
            continue
        reason = verify_receipt_against_result(
            receipt, result, result_comment_id=receipt["ckr6_result_comment_id"]
        )
        if reason is not None:
            invalid[reason] += 1
            continue
        key = receipt_key(receipt)
        prior = valid.get(key)
        if prior is None:
            valid[key] = receipt
        elif (prior["disposition"], prior["reason_code"]) == (receipt["disposition"], receipt["reason_code"]):
            duplicates += 1  # idempotent: never double-counted
        else:
            conflicting += 1  # first valid receipt stands; conflict is reported

    applied = Counter(r["reason_code"] for r in valid.values() if r["disposition"] == "applied")
    skipped = Counter(r["reason_code"] for r in valid.values() if r["disposition"] == "skipped")
    used = {(r["lesson_id"], r["source_revision"]) for r in valid.values()}
    refinement_signals = sorted({
        r["lesson_id"] for r in valid.values()
        if r["disposition"] == "skipped" and r["reason_code"] in REFINEMENT_SIGNAL_REASONS
    })
    accountability = _accountability_by_number()
    lesson_ids = sorted({lesson_id for lesson_id, _ in selected} | {r["lesson_id"] for r in valid.values()})
    return {
        "ckr6_results": dict(sorted(by_status.items())),
        "materiality_source": dict(sorted(materiality.items())),
        "notion_retrievals": reads,
        "rejected_requests": dict(sorted(rejections.items())),
        "eligibility_blocks": dict(sorted(eligibility_blocks.items())),
        "lessons_selected": len(selected),
        "selection_events": sum(selected.values()),
        "receipts": {
            "valid": len(valid),
            "applied": dict(sorted(applied.items())),
            "skipped": dict(sorted(skipped.items())),
            "invalid": dict(sorted(invalid.items())),
            "duplicates_ignored": duplicates,
            "conflicting": conflicting,
        },
        "selected_without_receipt": sorted(
            f"{lesson_id}@{revision}" for (lesson_id, revision) in selected if (lesson_id, revision) not in used
        ),
        "lesson_candidates": dict(sorted(candidates.items())),
        "candidate_recurrences": sum(1 for count in candidate_core.values() if count > 1),
        "refinement_proposals": dict(sorted(refinements.items())),
        "refinement_signals": refinement_signals,
        "accountability": {
            lesson_id: accountability.get(_lesson_number(lesson_id) or -1, "not-in-accountability-catalog")
            for lesson_id in lesson_ids
        },
        "malformed_markers": dict(sorted(malformed.items())),
        "causality_inferred": False,
        "authority_created": False,
    }


def acquire_issue_comments(repository: str, issues: Iterable[int], *, token: str = "") -> dict[int, list[dict]]:
    """Bounded read-only GET of issue comments. Never writes."""
    import urllib.request

    numbers = list(issues)
    if len(numbers) > MAX_ISSUES or any(type(n) is not int or n < 1 for n in numbers):
        raise ValueError("issues must be a bounded list of positive integers")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "agent-os-lesson-metrics"}
    if token:
        headers["Authorization"] = "Bearer " + token
    acquired: dict[int, list[dict]] = {}
    for number in numbers:
        comments: list[dict] = []
        for page in range(1, MAX_PAGES_PER_ISSUE + 1):
            url = f"https://api.github.com/repos/{repository}/issues/{number}/comments?per_page=100&page={page}"
            request = urllib.request.Request(url, method="GET", headers=headers)
            with urllib.request.urlopen(request, timeout=30) as response:
                batch = json.loads(response.read().decode("utf-8"))
            if type(batch) is not list:
                raise ValueError("unexpected comments payload")
            comments.extend(item for item in batch if isinstance(item, dict))
            if len(batch) < 100:
                break
        acquired[number] = comments
    return acquired


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default="Blummer92/agent-os")
    parser.add_argument("--issues", required=True)
    args = parser.parse_args()
    issues = [int(value) for value in args.issues.split(",") if value.strip()]
    comments = acquire_issue_comments(args.repository, issues, token=os.environ.get("GITHUB_TOKEN", ""))
    print(json.dumps(derive_lesson_metrics(comments), sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
