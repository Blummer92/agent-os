"""Finite GitHub issue-comment bridge to the existing CKR6 owners (#2851).

The transport owns only low-trust envelope validation and bounded result
projection. CKR2/CKR6 materiality, lesson selection, failed-repair semantics,
and Notion reads remain with their existing owners.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from agent_memory_context_manager.coding_knowledge_selection import CodingKnowledgeRequest
from agent_memory_context_manager.lesson_preflight import RepairContext, plan_lesson_preflight

from .issue_start_lesson_preflight import activate_issue_start_lesson_preflight
from .lesson_learning_loop import capture_lesson_candidate, propose_lesson_refinement
from .lesson_reader_composition import resolve_lesson_read_route
from .mcp_facade import activate_agent_os_failed_repair

COMMAND_PREFIX = "/agent-os ckr6 "
MAX_COMMENT_BYTES = 16 * 1024
MAX_HINTS = 20
MAX_TEXT = 512
# #3418: lesson-candidate (CKR5 capture) and lesson-refinement (CKR7) reuse
# this ingress. Both return authority-false proposals; neither writes Notion.
OPERATIONS = frozenset({"issue-start", "failed-repair", "lesson-candidate", "lesson-refinement"})
LEARNING_OPERATIONS = {"lesson-candidate": "candidate", "lesson-refinement": "refinement"}
# Marker for the bounded CKR6 result comment posted back to the issue (#2851).
# The marker is an HTML comment (invisible in rendered view) and deliberately
# does NOT start with COMMAND_PREFIX, so the postback can never retrigger the
# ingress workflow.
CKR6_RESULT_MARKER = "<!-- agent-os-ckr6-result:v1 -->"
MAX_RESULT_COMMENT_BYTES = 16 * 1024
# Exact result-envelope fields the postback transport may carry. The CKR6
# projection stays fixed; transport metadata is added only at serialization.
RESULT_FIELDS = frozenset({
    "operation",
    "repository",
    "issue_number",
    "status",
    "retry_reentry_outcome",
    "lesson_disposition",
    "reason_codes",
    "selected_lesson_ids",
    "selected_lessons",
    "materiality_source",
    "lesson_proposal",
    "revision_proposal",
    "canonical_github_refs",
    "rejected_candidate_provenance",
    "handoff_projection",
    "substantial_hypothesis_admissible",
    "mutation_admissible",
    "blocking_attempt_id",
    "execution_authorized",
    "github_writes_authorized",
    "merge_authorized",
    "closure_authorized",
    "side_effects_performed",
    "notion_read_performed",
    "retrieval_required",
    "recommended_escalation",
})
COMMON_FIELDS = frozenset({
    "operation", "repository", "issue_number", "task_reference",
    "ecosystem_hints", "language_hints", "library_hints",
    "capability_keywords", "target_path_hints", "canonical_rule_refs",
    "known_knowledge_refs", "specialized_knowledge_required",
})
FAILED_REPAIR_FIELDS = frozenset({
    "attempt_id", "failed_hypothesis", "result_summary", "repair_context",
})


@dataclass(frozen=True, slots=True)
class Ckr6Envelope:
    operation: str
    repository: str
    issue_number: int
    task_reference: str
    ecosystem_hints: tuple[str, ...] = ()
    language_hints: tuple[str, ...] = ()
    library_hints: tuple[str, ...] = ()
    capability_keywords: tuple[str, ...] = ()
    target_path_hints: tuple[str, ...] = ()
    canonical_rule_refs: tuple[str, ...] = ()
    known_knowledge_refs: tuple[str, ...] = ()
    specialized_knowledge_required: bool | None = None
    attempt_id: str | None = None
    failed_hypothesis: str | None = None
    result_summary: str | None = None
    repair_context: str = "failed-pr-repair"
    detail: Mapping[str, object] | None = None


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be non-empty exact text")
    if len(value) > MAX_TEXT:
        raise ValueError(f"{name} is oversized")
    return value


def _hints(value: object, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if type(value) is not list or len(value) > MAX_HINTS:
        raise ValueError(f"{name} must be a bounded list")
    return tuple(_text(item, name) for item in value)


def _specialized(value: object) -> bool | None:
    if value is None or type(value) is bool:
        return value
    raise ValueError("specialized_knowledge_required must be true, false, or null")



def _repair_context(value: object) -> str:
    context = _text(value, "repair_context")
    try:
        parsed = RepairContext(context)
    except ValueError as exc:
        raise ValueError("repair_context must be failed-pr-repair or ci-diagnosis") from exc
    if parsed is RepairContext.NONE:
        raise ValueError("failed-repair must use a repair or CI diagnosis context")
    return parsed.value


def _parse_learning_envelope(payload: Mapping[str, object], operation: str) -> Ckr6Envelope:
    key = LEARNING_OPERATIONS[operation]
    allowed = {"operation", "repository", "issue_number", "task_reference", key}
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"unsupported CKR6 envelope fields: {sorted(unknown)}")
    repository = _text(payload.get("repository"), "repository")
    if repository.count("/") != 1:
        raise ValueError("repository must use owner/name syntax")
    issue_number = payload.get("issue_number")
    if type(issue_number) is not int or issue_number < 1:
        raise ValueError("issue_number must be a positive integer")
    detail = payload.get(key)
    if not isinstance(detail, Mapping):
        raise ValueError(f"{key} must be a mapping")
    return Ckr6Envelope(
        operation=operation,
        repository=repository,
        issue_number=issue_number,
        task_reference=_text(payload.get("task_reference"), "task_reference"),
        detail=detail,
    )


def parse_envelope(payload: Mapping[str, object]) -> Ckr6Envelope:
    if not isinstance(payload, Mapping):
        raise TypeError("CKR6 envelope must be a mapping")
    operation = payload.get("operation")
    if operation not in OPERATIONS:
        raise ValueError("operation must be issue-start or failed-repair")
    if operation in LEARNING_OPERATIONS:
        return _parse_learning_envelope(payload, operation)
    allowed = COMMON_FIELDS | (FAILED_REPAIR_FIELDS if operation == "failed-repair" else frozenset())
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"unsupported CKR6 envelope fields: {sorted(unknown)}")
    repository = _text(payload.get("repository"), "repository")
    if repository.count("/") != 1:
        raise ValueError("repository must use owner/name syntax")
    issue_number = payload.get("issue_number")
    if type(issue_number) is not int or issue_number < 1:
        raise ValueError("issue_number must be a positive integer")
    kwargs = {
        name: _hints(payload.get(name, []), name)
        for name in (
            "ecosystem_hints", "language_hints", "library_hints",
            "capability_keywords", "target_path_hints", "canonical_rule_refs",
            "known_knowledge_refs",
        )
    }
    failed = operation == "failed-repair"
    return Ckr6Envelope(
        operation=operation,
        repository=repository,
        issue_number=issue_number,
        task_reference=_text(payload.get("task_reference"), "task_reference"),
        specialized_knowledge_required=_specialized(payload.get("specialized_knowledge_required")),
        attempt_id=_text(payload.get("attempt_id"), "attempt_id") if failed else None,
        failed_hypothesis=_text(payload.get("failed_hypothesis"), "failed_hypothesis") if failed else None,
        result_summary=_text(payload.get("result_summary"), "result_summary") if failed else None,
        repair_context=_repair_context(payload.get("repair_context", "failed-pr-repair")) if failed else "failed-pr-repair",
        **kwargs,
    )


# #2851: some GitHub write hosts (Claude Code cloud sessions) append exactly
# this attribution footer to every comment they author. It is the only
# trailing text tolerated after the JSON object; anything else still fails
# closed, so strict single-object parsing is preserved.
ATTRIBUTION_TRAILER = re.compile(
    r"\s*\n---\n_Generated by \[Claude Code\]\(https://claude\.ai/code\)_\s*"
)


def _command_payload(text: str) -> object:
    """Decode exactly one JSON object, tolerating only the known host trailer."""
    stripped = text.lstrip()
    try:
        payload, end = json.JSONDecoder().raw_decode(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError("CKR6 command payload must be one JSON object") from exc
    remainder = stripped[end:]
    if remainder.strip() and ATTRIBUTION_TRAILER.fullmatch(remainder) is None:
        raise ValueError("CKR6 command payload must be one JSON object")
    return payload


# Finite, input-free rejection codes. A rejected owner request receives a
# bounded diagnostic receipt instead of silence (#2851); the receipt never
# echoes request text.
_REJECTION_CODES = (
    ("event must be a mapping", "event-malformed"),
    ("event repository identity mismatch", "repository-mismatch"),
    ("CKR6 ingress accepts issue comments only", "pull-request-comment"),
    ("comment evidence missing", "comment-missing"),
    ("comment actor is not authorized", "actor-not-authorized"),
    ("comment body missing or oversized", "comment-oversized"),
    ("comment does not use the CKR6 command envelope", "command-prefix-missing"),
    ("CKR6 command payload must be one JSON object", "payload-not-one-json-object"),
    ("CKR6 envelope must be a mapping", "payload-not-one-json-object"),
    ("operation must be", "operation-unsupported"),
    ("unsupported CKR6 envelope fields", "envelope-field-unsupported"),
    ("repository must use", "repository-invalid"),
    ("envelope repository does not match", "repository-mismatch"),
    ("issue_number must be", "issue-number-invalid"),
    ("envelope issue_number does not match", "issue-number-mismatch"),
    ("specialized_knowledge_required must be", "materiality-invalid"),
    ("repair_context must be", "repair-context-invalid"),
    ("failed-repair must use", "repair-context-invalid"),
)


def rejection_reason(exc: BaseException) -> str:
    message = str(exc)
    for prefix, code in _REJECTION_CODES:
        if message.startswith(prefix):
            return "envelope-rejected:" + code
    if "oversized" in message:
        return "envelope-rejected:field-oversized"
    if "must be" in message:
        return "envelope-rejected:field-invalid"
    return "envelope-rejected:invalid"


def rejection_result(event: Mapping[str, object], repository: str, reason: str) -> dict[str, object]:
    """Bounded terminal result for a request the ingress could not admit."""
    issue = event.get("issue") if isinstance(event, Mapping) else None
    number = issue.get("number") if isinstance(issue, Mapping) else None
    return {
        "operation": "unknown",
        "repository": repository,
        "issue_number": number if type(number) is int and number > 0 else 0,
        "status": "rejected",
        "reason_codes": [reason],
        "selected_lesson_ids": [],
        "canonical_github_refs": [],
        "handoff_projection": {
            "known_facts": ["coding-knowledge-sufficiency:rejected"],
            "prior_decisions": [],
            "allowed_inspect_first": [],
            "stop_conditions": ["coding-knowledge:" + reason],
        },
        "retrieval_required": False,
        "notion_read_performed": False,
        "substantial_hypothesis_admissible": False,
        "mutation_admissible": False,
        "execution_authorized": False,
        "github_writes_authorized": False,
        "merge_authorized": False,
        "closure_authorized": False,
        "side_effects_performed": False,
    }


def envelope_from_event(
    event: Mapping[str, object], *, expected_repository: str, allowed_actor: str
) -> Ckr6Envelope:
    if not isinstance(event, Mapping):
        raise TypeError("event must be a mapping")
    repository = event.get("repository")
    issue = event.get("issue")
    comment = event.get("comment")
    if not isinstance(repository, Mapping) or repository.get("full_name") != expected_repository:
        raise ValueError("event repository identity mismatch")
    if not isinstance(issue, Mapping) or "pull_request" in issue:
        raise ValueError("CKR6 ingress accepts issue comments only")
    if not isinstance(comment, Mapping):
        raise ValueError("comment evidence missing")
    user = comment.get("user")
    if not isinstance(user, Mapping) or user.get("login") != allowed_actor:
        raise ValueError("comment actor is not authorized for CKR6 ingress")
    body = comment.get("body")
    if type(body) is not str or len(body.encode("utf-8")) > MAX_COMMENT_BYTES:
        raise ValueError("comment body missing or oversized")
    if not body.startswith(COMMAND_PREFIX):
        raise ValueError("comment does not use the CKR6 command envelope")
    payload = _command_payload(body[len(COMMAND_PREFIX):])
    if type(payload) is not dict:
        raise ValueError("CKR6 command payload must be one JSON object")
    envelope = parse_envelope(payload)
    if envelope.repository != expected_repository:
        raise ValueError("envelope repository does not match event repository")
    if envelope.issue_number != issue.get("number"):
        raise ValueError("envelope issue_number does not match event issue")
    return envelope


def _request(envelope: Ckr6Envelope) -> CodingKnowledgeRequest:
    return CodingKnowledgeRequest(
        task_reference=envelope.task_reference,
        ecosystem_hints=envelope.ecosystem_hints,
        language_hints=envelope.language_hints,
        library_hints=envelope.library_hints,
        capability_keywords=envelope.capability_keywords,
        target_path_hints=envelope.target_path_hints,
        canonical_rule_refs=envelope.canonical_rule_refs,
        known_knowledge_refs=envelope.known_knowledge_refs,
        specialized_knowledge_required=envelope.specialized_knowledge_required,
    )


def classify_envelope(envelope: Ckr6Envelope) -> dict[str, object]:
    if envelope.operation in LEARNING_OPERATIONS:
        # Capture never reads; refinement reads exactly the named lesson.
        return {
            "operation": envelope.operation,
            "repository": envelope.repository,
            "issue_number": envelope.issue_number,
            "retrieval_required": envelope.operation == "lesson-refinement",
            "reason_codes": ["learning-operation:" + envelope.operation],
            "recommended_escalation": "known-reference" if envelope.operation == "lesson-refinement" else "none",
            "notion_read_performed": False,
            "execution_authorized": False,
            "github_writes_authorized": False,
            "merge_authorized": False,
            "closure_authorized": False,
            "side_effects_performed": False,
        }
    context = (
        RepairContext(envelope.repair_context)
        if envelope.operation == "failed-repair"
        else RepairContext.NONE
    )
    if envelope.operation == "failed-repair" and context is RepairContext.NONE:
        raise ValueError("failed-repair must use a repair or CI diagnosis context")
    plan = plan_lesson_preflight(_request(envelope), repair_context=context)
    return {
        "operation": envelope.operation,
        "repository": envelope.repository,
        "issue_number": envelope.issue_number,
        "retrieval_required": plan.retrieval_required,
        "reason_codes": list(plan.reason_codes),
        "recommended_escalation": plan.recommended_escalation.value,
        "notion_read_performed": False,
        "execution_authorized": False,
        "github_writes_authorized": False,
        "merge_authorized": False,
        "closure_authorized": False,
        "side_effects_performed": False,
    }


def execute_envelope(envelope: Ckr6Envelope, *, retrieval_required: bool) -> dict[str, object]:
    route = resolve_lesson_read_route() if retrieval_required else None
    if retrieval_required and (route is None or route.execute_read is None):
        route_reason = route.reason_code if route is not None else "lesson-read-route-unavailable"
        return {
            "operation": envelope.operation,
            "repository": envelope.repository,
            "issue_number": envelope.issue_number,
            "status": "manual-review",
            "reason_codes": [route_reason],
            "selected_lesson_ids": [],
            "canonical_github_refs": [],
            # The host consumes stop_conditions to know WHY it must stop; the
            # shape mirrors the canonical CKR6 fallback handoff projection.
            "handoff_projection": {
                "known_facts": ["coding-knowledge-sufficiency:manual-review"],
                "prior_decisions": [],
                "allowed_inspect_first": [],
                "stop_conditions": ["coding-knowledge:" + route_reason],
            },
            "substantial_hypothesis_admissible": False,
            "mutation_admissible": False,
            "execution_authorized": False,
            "github_writes_authorized": False,
            "merge_authorized": False,
            "closure_authorized": False,
            "side_effects_performed": False,
        }
    reader = route.execute_read if route is not None else None
    if envelope.operation in LEARNING_OPERATIONS:
        return _execute_learning(envelope, reader)
    common = dict(
        repository=envelope.repository,
        issue_number=envelope.issue_number,
        task_reference=envelope.task_reference,
        ecosystem_hints=envelope.ecosystem_hints,
        language_hints=envelope.language_hints,
        library_hints=envelope.library_hints,
        capability_keywords=envelope.capability_keywords,
        target_path_hints=envelope.target_path_hints,
        canonical_rule_refs=envelope.canonical_rule_refs,
        known_knowledge_refs=envelope.known_knowledge_refs,
        specialized_knowledge_required=envelope.specialized_knowledge_required,
    )
    if envelope.operation == "issue-start":
        raw = activate_issue_start_lesson_preflight(**common, execute_read=reader)
        # The handoff_projection is the host-consumable unit: the overlay
        # instructs the host to put exactly this projection into its governed
        # context packet. It was previously computed and dropped, which left
        # the GitHub-ingress result without a consumable lesson payload.
        handoff = raw["handoff_projection"]
        if type(handoff) is not dict:
            raise TypeError("handoff_projection must be a dict")
        return {
            "operation": envelope.operation,
            "repository": envelope.repository,
            "issue_number": envelope.issue_number,
            "status": raw["lesson_retrieval_status"],
            "reason_codes": raw["selection_reason_codes"],
            "selected_lesson_ids": raw["selected_lesson_ids"],
            "selected_lessons": raw["selected_lessons"],
            "materiality_source": raw["materiality_source"],
            "canonical_github_refs": raw["canonical_github_refs"],
            "rejected_candidate_provenance": raw["rejected_candidate_provenance"],
            "handoff_projection": handoff,
            "substantial_hypothesis_admissible": raw["substantial_hypothesis_admissible"],
            "mutation_admissible": False,
            "execution_authorized": False,
            "github_writes_authorized": False,
            "merge_authorized": False,
            "closure_authorized": False,
            "side_effects_performed": False,
        }
    raw = activate_agent_os_failed_repair(
        **common,
        attempt_id=envelope.attempt_id,
        failed_hypothesis=envelope.failed_hypothesis,
        result_summary=envelope.result_summary,
        repair_context=envelope.repair_context,
        execute_read=reader,
    )
    return {
        "operation": envelope.operation,
        "repository": envelope.repository,
        "issue_number": envelope.issue_number,
        "status": raw["lesson_retrieval_status"],
        "retry_reentry_outcome": raw["retry_reentry_outcome"],
        "lesson_disposition": raw["lesson_disposition"],
        "reason_codes": raw["reason_codes"],
        "selected_lesson_ids": raw["selected_lesson_ids"],
        "selected_lessons": raw["selected_lessons"],
        "canonical_github_refs": raw["canonical_github_refs"],
        "mutation_admissible": raw["mutation_admissible"],
        "blocking_attempt_id": raw["blocking_attempt_id"],
        "execution_authorized": False,
        "github_writes_authorized": False,
        "merge_authorized": False,
        "closure_authorized": False,
        "side_effects_performed": False,
    }


def _execute_learning(envelope: Ckr6Envelope, reader) -> dict[str, object]:
    if envelope.operation == "lesson-candidate":
        outcome = capture_lesson_candidate(envelope.detail)
        extra = {"lesson_proposal": outcome["lesson_proposal"]}
        read = False
    else:
        outcome = propose_lesson_refinement(envelope.detail, reader)
        extra = {"revision_proposal": outcome["revision_proposal"]}
        read = True
    return {
        "operation": envelope.operation,
        "repository": envelope.repository,
        "issue_number": envelope.issue_number,
        "status": outcome["status"],
        "reason_codes": outcome["reason_codes"],
        "selected_lesson_ids": [],
        "canonical_github_refs": [],
        **extra,
        "notion_read_performed": read,
        "substantial_hypothesis_admissible": False,
        "mutation_admissible": False,
        "execution_authorized": False,
        "github_writes_authorized": False,
        "merge_authorized": False,
        "closure_authorized": False,
        "side_effects_performed": False,
    }


def _canonical_result_json(payload: Mapping[str, object]) -> str:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def serialize_ckr6_result_comment(
    result: Mapping[str, object], *, request_comment_id: int
) -> str:
    """Serialize one bounded CKR6 result as a host-consumable issue comment.

    The comment is the machine-consumable ChatGPT boundary for the finite
    GitHub ingress (#2851): marker line + canonical compact JSON, following
    the existing receipt pattern. It never starts with COMMAND_PREFIX, so the
    postback cannot retrigger the ingress workflow. Only RESULT_FIELDS are
    carried; anything else fails closed instead of being passed through.
    """
    if type(result) is not dict:
        raise TypeError("result must be a dict")
    if type(request_comment_id) is not int or request_comment_id < 1:
        raise ValueError("request_comment_id must be a positive integer")
    unknown = set(result) - RESULT_FIELDS
    if unknown:
        raise ValueError(f"result carries unexpected fields: {sorted(unknown)}")
    payload = {**result, "request_comment_id": request_comment_id}
    body = CKR6_RESULT_MARKER + "\n" + _canonical_result_json(payload)
    if len(body.encode("utf-8")) > MAX_RESULT_COMMENT_BYTES:
        raise ValueError("serialized CKR6 result exceeds the bounded comment size")
    return body


def parse_ckr6_result_comment(body: object) -> dict[str, object]:
    """Parse one CKR6 result comment back into its bounded payload.

    This is the consumption-side contract for the host: strict marker + exactly
    two lines + canonical compact JSON. A missing result comment is
    ``result-not-returned`` evidence, never an admission.
    """
    if type(body) is not str:
        raise TypeError("comment body must be str")
    prefix = CKR6_RESULT_MARKER + "\n"
    if not body.startswith(prefix):
        raise ValueError("comment is not a CKR6 result comment")
    if body.count("\n") != 1:
        raise ValueError("CKR6 result comment must contain exactly two lines")
    serialized = body[len(prefix):]
    payload = json.loads(serialized)
    if type(payload) is not dict or _canonical_result_json(payload) != serialized:
        raise ValueError("CKR6 result payload must be canonical compact JSON")
    return payload


def _fallback_result(repository: str, issue_number: int) -> dict[str, object]:
    """Bounded manual-review result when no CKR6 result evidence exists.

    The host must receive an explicit terminal signal rather than silence:
    silence would be indistinguishable from a lost result.
    """
    return {
        "operation": "unknown",
        "repository": repository,
        "issue_number": issue_number,
        "status": "manual-review",
        "reason_codes": ["ckr6-result-unavailable"],
        "selected_lesson_ids": [],
        "canonical_github_refs": [],
        "substantial_hypothesis_admissible": False,
        "mutation_admissible": False,
        "execution_authorized": False,
        "github_writes_authorized": False,
        "merge_authorized": False,
        "closure_authorized": False,
        "side_effects_performed": False,
    }


def _load_result(path: str) -> dict[str, object] | None:
    text = Path(path).read_text(encoding="utf-8")
    payload = json.loads(text)
    if type(payload) is not dict:
        raise ValueError("CKR6 result payload must be one JSON object")
    unknown = set(payload) - RESULT_FIELDS
    if unknown:
        raise ValueError(f"CKR6 result carries unexpected fields: {sorted(unknown)}")
    return payload


def _existing_result_comment(
    target: str, since: object, request_comment_id: int, token: str
) -> int | None:
    """Return an already-posted result comment id for this request, if any.

    Bounded to one page of comments created since the request. Lookup failure
    is not evidence of absence of work: the caller still posts, preferring a
    duplicate receipt over silence.
    """
    if type(since) is not str or not since:
        return None
    import urllib.parse
    import urllib.request

    query = urllib.parse.urlencode({"since": since, "per_page": 100})
    request = urllib.request.Request(
        f"{target}?{query}",
        method="GET",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + token,
            "User-Agent": "agent-os-ckr6-bridge",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            comments = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    if type(comments) is not list:
        return None
    for item in comments:
        if not isinstance(item, Mapping) or type(item.get("id")) is not int:
            continue
        try:
            parsed = parse_ckr6_result_comment(item.get("body"))
        except (TypeError, ValueError):
            continue
        if parsed.get("request_comment_id") == request_comment_id:
            return item["id"]
    return None


def postback_result_comment(
    *,
    event: Mapping[str, object],
    repository: str,
    result: dict[str, object] | None,
    api_url: str,
    token: str,
) -> dict[str, object]:
    """Post the bounded CKR6 result comment to the originating issue.

    This closes the ``result-not-returned`` seam: the host's GitHub MCP surface
    can read issue comments, but not workflow step summaries or artifacts.
    Fail-closed: transport errors raise instead of reporting a posted result.
    The token is never logged or embedded in returned evidence.
    """
    if not isinstance(event, Mapping):
        raise TypeError("event must be a mapping")
    if type(repository) is not str or "/" not in repository or not repository.strip():
        raise ValueError("repository must use bounded owner/name syntax")
    issue = event.get("issue")
    comment = event.get("comment")
    if not isinstance(issue, Mapping) or type(issue.get("number")) is not int:
        raise ValueError("event issue number missing")
    if not isinstance(comment, Mapping) or type(comment.get("id")) is not int:
        raise ValueError("event request comment id missing")
    if type(api_url) is not str or not api_url.startswith("https://"):
        raise ValueError("api_url must be an https URL")
    if type(token) is not str or not token:
        raise ValueError("GitHub token is required for result postback")

    issue_number: int = issue["number"]
    request_comment_id: int = comment["id"]
    payload = result if result is not None else _fallback_result(repository, issue_number)
    body = serialize_ckr6_result_comment(payload, request_comment_id=request_comment_id)

    import urllib.request

    target = f"{api_url.rstrip('/')}/repos/{repository}/issues/{issue_number}/comments"
    existing = _existing_result_comment(
        target, comment.get("created_at"), request_comment_id, token
    )
    if existing is not None:
        # A rerun of the same request must not post a second receipt.
        return {
            "issue_number": issue_number,
            "request_comment_id": request_comment_id,
            "posted_comment_id": existing,
            "result_status": payload["status"],
            "deduplicated": True,
        }
    request = urllib.request.Request(
        target,
        data=json.dumps({"body": body}).encode("utf-8"),
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "User-Agent": "agent-os-ckr6-bridge",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            posted = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"CKR6 result postback failed: {type(exc).__name__}") from exc
    if not isinstance(posted, Mapping) or type(posted.get("id")) is not int:
        raise RuntimeError("CKR6 result postback returned an unexpected response")
    return {
        "issue_number": issue_number,
        "request_comment_id": request_comment_id,
        "posted_comment_id": posted["id"],
        "result_status": payload["status"],
    }


def _load_event(path: str) -> Mapping[str, object]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError("event payload must be an object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("classify", "execute", "postback"), required=True)
    parser.add_argument("--event", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--allowed-actor", required=False, default="Blummer92")
    parser.add_argument("--output", required=False)
    parser.add_argument("--retrieval-required", choices=("true", "false"))
    parser.add_argument("--result", required=False)
    parser.add_argument("--api-url", required=False, default="https://api.github.com")
    args = parser.parse_args()

    event = _load_event(args.event)
    if args.phase == "postback":
        # The workflow job gate already admitted this event; postback needs no
        # actor re-check, only the issue/comment identity for correlation.
        result = _load_result(args.result) if args.result and Path(args.result).exists() else None
        token = os.environ.get("GITHUB_TOKEN", "")
        posted = postback_result_comment(
            event=event,
            repository=args.repository,
            result=result,
            api_url=args.api_url,
            token=token,
        )
        print(json.dumps(posted, sort_keys=True))
        return 0

    if not args.allowed_actor or not args.output:
        raise ValueError("--allowed-actor and --output are required for classify/execute")
    try:
        envelope = envelope_from_event(
            event,
            expected_repository=args.repository,
            allowed_actor=args.allowed_actor,
        )
    except (TypeError, ValueError) as exc:
        # #2851: never fail silently. Classification succeeds with zero
        # retrieval, and execute writes the bounded rejection result that the
        # always-run postback returns to the originating issue.
        envelope = None
        result = rejection_result(event, args.repository, rejection_reason(exc))
    if envelope is None:
        pass
    elif args.phase == "classify":
        result = classify_envelope(envelope)
    else:
        if args.retrieval_required is None:
            raise ValueError("--retrieval-required is required for execute")
        result = execute_envelope(
            envelope,
            retrieval_required=args.retrieval_required == "true",
        )
    Path(args.output).write_text(
        json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
