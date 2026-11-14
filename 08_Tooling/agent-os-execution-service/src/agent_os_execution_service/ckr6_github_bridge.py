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
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, TypedDict, cast

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
    # R07: a failed-repair result names the exact attempt it was produced
    # for, so a consumer can reject a result recorded for an earlier
    # attempt. Issue-start and learning results carry no attempt_id.
    "attempt_id",
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
    # Where the request comment lives: "issue" for an ordinary issue, "pr"
    # for a top-level PR Conversation comment. Set by envelope_from_event
    # from the event's issue record, never by the envelope JSON itself; the
    # result payload carries no target kind (RESULT_FIELDS is fixed).
    target_kind: str = "issue"


class _PreflightArgs(TypedDict):
    """Keyword arguments shared by the issue-start and failed-repair owners."""

    repository: str
    issue_number: int
    task_reference: str
    ecosystem_hints: tuple[str, ...]
    language_hints: tuple[str, ...]
    library_hints: tuple[str, ...]
    capability_keywords: tuple[str, ...]
    target_path_hints: tuple[str, ...]
    canonical_rule_refs: tuple[str, ...]
    known_knowledge_refs: tuple[str, ...]
    specialized_knowledge_required: bool | None


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
    # OPERATIONS holds only str values, so passing the membership check proves
    # the type. The check stays first so unhashable values keep their existing
    # rejection path.
    operation = cast(str, operation)
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
    # Hints are validated before the remaining fields, in this order, so a
    # multi-field rejection keeps reporting the same first error.
    ecosystem_hints = _hints(payload.get("ecosystem_hints", []), "ecosystem_hints")
    language_hints = _hints(payload.get("language_hints", []), "language_hints")
    library_hints = _hints(payload.get("library_hints", []), "library_hints")
    capability_keywords = _hints(payload.get("capability_keywords", []), "capability_keywords")
    target_path_hints = _hints(payload.get("target_path_hints", []), "target_path_hints")
    canonical_rule_refs = _hints(payload.get("canonical_rule_refs", []), "canonical_rule_refs")
    known_knowledge_refs = _hints(payload.get("known_knowledge_refs", []), "known_knowledge_refs")
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
        ecosystem_hints=ecosystem_hints,
        language_hints=language_hints,
        library_hints=library_hints,
        capability_keywords=capability_keywords,
        target_path_hints=target_path_hints,
        canonical_rule_refs=canonical_rule_refs,
        known_knowledge_refs=known_knowledge_refs,
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
    ("refinement receipt_refs", "refinement-receipt-refs-invalid"),
    ("refinement", "refinement-detail-invalid"),
    ("candidate", "candidate-detail-invalid"),
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
    if not isinstance(issue, Mapping):
        raise ValueError("CKR6 ingress accepts issue comments only")
    # A top-level PR Conversation comment arrives as an issue_comment event
    # whose issue record carries a "pull_request" mapping; the event issue
    # number is the PR number. Only a mapping counts: any other
    # "pull_request" value is a malformed event and keeps the old rejection
    # (and its "pull-request-comment" rejection code).
    pull_request = issue.get("pull_request")
    if pull_request is not None and not isinstance(pull_request, Mapping):
        raise ValueError("CKR6 ingress accepts issue comments only")
    target_kind = "pr" if isinstance(pull_request, Mapping) else "issue"
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
    return replace(envelope, target_kind=target_kind)


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
        unbound = {
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
        if envelope.operation == "failed-repair":
            # P1: the STOP result must still name the exact failed attempt so a
            # consumer can bind it (R07); reason codes are preserved unchanged.
            unbound["attempt_id"] = envelope.attempt_id
        return unbound
    reader = route.execute_read if route is not None else None
    if envelope.operation in LEARNING_OPERATIONS:
        return _execute_learning(envelope, reader)
    common: _PreflightArgs = {
        "repository": envelope.repository,
        "issue_number": envelope.issue_number,
        "task_reference": envelope.task_reference,
        "ecosystem_hints": envelope.ecosystem_hints,
        "language_hints": envelope.language_hints,
        "library_hints": envelope.library_hints,
        "capability_keywords": envelope.capability_keywords,
        "target_path_hints": envelope.target_path_hints,
        "canonical_rule_refs": envelope.canonical_rule_refs,
        "known_knowledge_refs": envelope.known_knowledge_refs,
        "specialized_knowledge_required": envelope.specialized_knowledge_required,
    }
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
    # parse_envelope sets all three for every failed-repair envelope. Narrow
    # explicitly, raising exactly what the downstream owner raises today.
    if envelope.attempt_id is None:
        raise ValueError("attempt_id must be non-empty exact text")
    if envelope.failed_hypothesis is None:
        raise TypeError("failed_hypothesis must be a string")
    if envelope.result_summary is None:
        raise TypeError("result_summary must be a string")
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
        # R07: carry the exact failed attempt through the bounded result
        # projection. Without it no consumer of the result comment could
        # prove the result was produced for the current attempt.
        "attempt_id": envelope.attempt_id,
        "execution_authorized": False,
        "github_writes_authorized": False,
        "merge_authorized": False,
        "closure_authorized": False,
        "side_effects_performed": False,
    }


def _execute_learning(envelope: Ckr6Envelope, reader) -> dict[str, object]:
    key = "lesson_proposal" if envelope.operation == "lesson-candidate" else "revision_proposal"
    try:
        detail = envelope.detail
        if detail is None:
            # Same rejection the candidate/refinement parsers raise first.
            raise ValueError(f"{LEARNING_OPERATIONS[envelope.operation]} must be a mapping")
        if envelope.operation == "lesson-candidate":
            outcome = capture_lesson_candidate(detail)
        else:
            outcome = propose_lesson_refinement(detail, reader)
    except (TypeError, ValueError) as exc:
        # Detail validation precedes any read. A malformed candidate or
        # refinement returns a bounded finite-code rejection, never a crash
        # into the generic ckr6-result-unavailable fallback.
        outcome = {"status": "rejected", "reason_codes": [rejection_reason(exc)], key: None}
        read = False
    else:
        read = envelope.operation == "lesson-refinement"
    extra = {key: outcome[key]}
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


# R07/P1: trusted, exact request/result consumption (#2425 / #2851).
#
# ``parse_ckr6_result_comment`` deliberately stays a pure syntax check: it
# proves neither who wrote a comment nor which request it answers. A host must
# consume through ``consume_ckr6_result_comment`` (one GitHub comment resource)
# or ``select_ckr6_result_comment`` (a bounded list of comment resources). Both
# take the GitHub issue-comment *record* (``id``, ``user``, ``created_at``,
# location) rather than a bare body, fail closed with ``ValueError``, and never
# authorize anything: a consumed result is evidence for the host's governed
# decision, never a repository write/merge/closure grant.
#
# Producer provenance boundary (documented limitation): the strongest check the
# GitHub comment record supports is the server-assigned author identity
# (login, numeric account id, Bot type, and the ``github-actions`` app when the
# REST record carries it) plus exact issue/repository location and creation
# order against the request. This proves the comment was posted by the GitHub
# Actions bot account; it does NOT prove WHICH workflow/job posted it. Any
# other workflow in this repository holding ``issues: write`` posts under the
# same identity, and the result carries no run identifier. Never describe this
# as per-workflow or cryptographic authentication.
CKR6_PRODUCER_LOGIN = "github-actions[bot]"
CKR6_PRODUCER_ACCOUNT_ID = 41898282
CKR6_PRODUCER_ACCOUNT_TYPE = "Bot"
CKR6_PRODUCER_APP_SLUG = "github-actions"

_AUTHORITY_FLAGS = (
    "execution_authorized",
    "github_writes_authorized",
    "merge_authorized",
    "closure_authorized",
    "side_effects_performed",
)
# Mirrors ISSUE_START_LESSON_PREFLIGHT.md "Admission signal".
_ISSUE_START_ADMITTING = frozenset({"not-needed", "sufficient", "unavailable-safe-fallback"})
# Mirrors RetryReentryOutcome admitting values (failed-repair-lesson-reentry.md).
_RETRY_ADMITTING = frozenset({"consumed", "not-material"})
# Canonical activate_repair_retry_lessons._retry_outcome mapping; preserve
# blocked results as STOP evidence, including early unbound manual-review.
_RETRY_OUTCOME_BY_STATUS = {
    "sufficient": "consumed",
    "not-needed": "not-material",
    "insufficient": "unavailable-or-failed",
    "manual-review": "unavailable-or-failed",
    "unavailable-safe-fallback": "unavailable-or-failed",
}
# Operation of the bridge's bounded infrastructure fallback (_fallback_result).
_FALLBACK_OPERATION = "unknown"
_FALLBACK_REASON = "ckr6-result-unavailable"


def _expected_id(value: object, name: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _utc(value: object, name: str) -> datetime:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from None
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must carry a UTC offset")
    return parsed


def _trusted_result_body(
    comment: object,
    *,
    expected_request_comment_id: int,
    expected_request_created_at: object,
    expected_issue_number: int,
    expected_repository: str,
    expected_target_kind: str = "issue",
) -> str:
    """Return the body of a comment only if its GitHub record is trusted.

    ``expected_target_kind`` is ``"issue"`` for an ordinary issue and
    ``"pr"`` for a top-level PR Conversation comment. The REST
    ``issue_url`` stays ``/issues/N`` for both kinds, while the HTML
    location is kind-exact: ``/issues/N`` for issues, ``/pull/N`` for PRs.
    A cross-target location is refused, never coerced.
    """
    if expected_target_kind not in ("issue", "pr"):
        raise ValueError("expected_target_kind must be issue or pr")
    if not isinstance(comment, Mapping):
        raise ValueError("CKR6 result comment record must be a mapping")
    comment_id = comment.get("id")
    if type(comment_id) is not int or isinstance(comment_id, bool) or comment_id < 1:
        raise ValueError("CKR6 result comment record is missing a valid id")
    body = comment.get("body")
    if type(body) is not str:
        raise ValueError("CKR6 result comment record is missing its body")
    user = comment.get("user")
    if not isinstance(user, Mapping):
        raise ValueError("CKR6 result comment record is missing its author")
    account_id = user.get("id")
    if (
        user.get("login") != CKR6_PRODUCER_LOGIN
        or type(account_id) is not int
        or isinstance(account_id, bool)
        or account_id != CKR6_PRODUCER_ACCOUNT_ID
    ):
        raise ValueError("CKR6 result comment was not produced by the trusted producer")
    if user.get("type") is not None and user.get("type") != CKR6_PRODUCER_ACCOUNT_TYPE:
        raise ValueError("CKR6 result comment author is not a Bot account")
    app = comment.get("performed_via_github_app")
    if app is not None and (
        not isinstance(app, Mapping) or app.get("slug") != CKR6_PRODUCER_APP_SLUG
    ):
        raise ValueError("CKR6 result comment was not posted via the GitHub Actions app")
    issue_url = comment.get("issue_url")
    html_url = comment.get("html_url")
    if issue_url is None and html_url is None:
        raise ValueError("CKR6 result comment record carries no issue location")
    if issue_url is not None and issue_url != (
        f"https://api.github.com/repos/{expected_repository}/issues/{expected_issue_number}"
    ):
        raise ValueError("CKR6 result comment location does not match the pending request")
    if html_url is not None:
        # GitHub's HTML location for a PR Conversation comment is
        # /pull/N#issuecomment-ID, while its REST issue_url stays /issues/N.
        # The expected form is exact per target kind; an /issues/N HTML
        # location never satisfies a PR target, nor /pull/N an issue target.
        if expected_target_kind == "pr":
            expected_html_url = (
                f"https://github.com/{expected_repository}/pull/{expected_issue_number}"
                f"#issuecomment-{comment_id}"
            )
        else:
            expected_html_url = (
                f"https://github.com/{expected_repository}/issues/{expected_issue_number}"
                f"#issuecomment-{comment_id}"
            )
        if html_url != expected_html_url:
            raise ValueError("CKR6 result comment location does not match the pending request")
    created = _utc(comment.get("created_at"), "created_at")
    if created < _utc(expected_request_created_at, "expected_request_created_at"):
        raise ValueError("CKR6 result comment predates the pending request")
    if comment_id <= expected_request_comment_id:
        raise ValueError("CKR6 result comment predates the pending request")
    updated = comment.get("updated_at")
    if updated is not None and _utc(updated, "updated_at") != created:
        raise ValueError("CKR6 result comment was edited after creation")
    return body


def _check_admission_semantics(payload: Mapping[str, object], operation: str) -> None:
    status = payload.get("status")
    admissible = payload.get("substantial_hypothesis_admissible")
    mutation = payload.get("mutation_admissible")
    if operation == "issue-start":
        if type(admissible) is not bool:
            raise ValueError("CKR6 result admission flag must be a boolean")
        if mutation not in (None, False):
            raise ValueError("issue-start result must not claim mutation admission")
        if admissible != (status in _ISSUE_START_ADMITTING):
            raise ValueError("CKR6 result status contradicts its admission flag")
    elif operation == "failed-repair":
        if admissible not in (None, False):
            raise ValueError("failed-repair result must not claim first-hypothesis admission")
        if type(mutation) is not bool:
            raise ValueError("CKR6 result admission flag must be a boolean")
        if type(status) is not str or status not in _RETRY_OUTCOME_BY_STATUS:
            raise ValueError("CKR6 result status contradicts its admission flag")
        outcome = payload.get("retry_reentry_outcome")
        # An unbound read route emits manual-review without a retry outcome;
        # that explicit blocked result is still valid STOP evidence.
        unbound_stop = (
            status == "manual-review" and outcome is None and mutation is False
        )
        if outcome != _RETRY_OUTCOME_BY_STATUS[status] and not unbound_stop:
            raise ValueError("CKR6 result status contradicts its admission flag")
        if mutation and outcome not in _RETRY_ADMITTING:
            raise ValueError("CKR6 result status contradicts its admission flag")
    else:
        if admissible not in (None, False) or mutation not in (None, False):
            raise ValueError("learning result must not claim admission")


def consume_ckr6_result_comment(
    comment: object,
    *,
    expected_request_comment_id: int,
    expected_request_created_at: str,
    expected_issue_number: int,
    expected_repository: str,
    expected_operation: str,
    expected_attempt_id: str | None = None,
    expected_target_kind: str = "issue",
) -> dict[str, object]:
    """Consume one trusted CKR6 result comment as the answer to a pending request.

    ``comment`` is the GitHub issue-comment record. The producer must be the
    GitHub Actions bot account (see the provenance boundary above), located in
    the pending request's issue and created after the request. The payload must
    use only ``RESULT_FIELDS`` plus ``request_comment_id``, match the expected
    operation, carry five explicit false authority flags, keep status and
    admission flags consistent, and (failed-repair) name the exact current
    attempt. A valid blocked result is returned as STOP evidence, not rejected;
    ``ckr6_result_admits_boundary`` turns it into a decision. Raises
    ``ValueError`` otherwise. ``expected_target_kind`` is ``"issue"`` for an
    ordinary issue and ``"pr"`` for a top-level PR Conversation comment; the
    HTML location must match that kind exactly.
    """
    expected_request_comment_id = _expected_id(
        expected_request_comment_id, "expected_request_comment_id"
    )
    expected_issue_number = _expected_id(expected_issue_number, "expected_issue_number")
    if type(expected_repository) is not str or not expected_repository.strip():
        raise ValueError("expected_repository must be non-empty exact text")
    if type(expected_operation) is not str or expected_operation not in OPERATIONS:
        raise ValueError("expected_operation must be a supported CKR6 operation")
    if expected_target_kind not in ("issue", "pr"):
        raise ValueError("expected_target_kind must be issue or pr")
    if expected_attempt_id is not None and (
        type(expected_attempt_id) is not str or not expected_attempt_id.strip()
    ):
        raise ValueError("expected_attempt_id must be non-empty exact text")

    body = _trusted_result_body(
        comment,
        expected_request_comment_id=expected_request_comment_id,
        expected_request_created_at=expected_request_created_at,
        expected_issue_number=expected_issue_number,
        expected_repository=expected_repository,
        expected_target_kind=expected_target_kind,
    )
    payload = parse_ckr6_result_comment(body)
    unknown = set(payload) - RESULT_FIELDS - {"request_comment_id"}
    if unknown:
        raise ValueError("CKR6 result carries unexpected fields")

    request_comment_id = payload.get("request_comment_id")
    if type(request_comment_id) is not int or isinstance(request_comment_id, bool):
        raise ValueError("CKR6 result is missing request_comment_id")
    if request_comment_id != expected_request_comment_id:
        raise ValueError(
            "CKR6 result request_comment_id does not match the pending request"
        )
    if payload.get("issue_number") != expected_issue_number:
        raise ValueError("CKR6 result issue_number does not match the pending request")
    if payload.get("repository") != expected_repository:
        raise ValueError("CKR6 result repository does not match the pending request")
    for flag in _AUTHORITY_FLAGS:
        if payload.get(flag) is not False:
            raise ValueError("CKR6 result carries forbidden authority")

    operation = payload.get("operation")
    if operation == _FALLBACK_OPERATION:
        # The generic fallback has no attempt_id. It cannot satisfy a
        # failed-repair retry boundary, even as STOP evidence for that attempt.
        if expected_operation == "failed-repair":
            raise ValueError("CKR6 fallback cannot satisfy a failed-repair attempt")
        # For issue-start (and non-retry learning operations), a valid
        # infrastructure fallback remains explicit STOP evidence.
        if (
            payload.get("status") != "manual-review"
            or payload.get("reason_codes") != [_FALLBACK_REASON]
            or payload.get("substantial_hypothesis_admissible") is not False
            or payload.get("mutation_admissible") is not False
            or payload.get("selected_lesson_ids") != []
        ):
            raise ValueError("CKR6 fallback result is not a valid blocked result")
        return payload
    if type(operation) is not str or operation not in OPERATIONS:
        raise ValueError("CKR6 result operation is unsupported")
    if operation != expected_operation:
        raise ValueError("CKR6 result operation does not match the pending request")
    if operation == "failed-repair":
        if expected_attempt_id is None:
            raise ValueError("failed-repair result requires expected_attempt_id")
        attempt_id = payload.get("attempt_id")
        if type(attempt_id) is not str or not attempt_id.strip():
            raise ValueError("CKR6 result is missing attempt_id for the failed-repair request")
        if attempt_id != expected_attempt_id:
            raise ValueError(
                "CKR6 result attempt_id does not match the current failed attempt"
            )
    _check_admission_semantics(payload, operation)
    return payload


def select_ckr6_result_comment(
    comments: object,
    *,
    expected_request_comment_id: int,
    expected_request_created_at: str,
    expected_issue_number: int,
    expected_repository: str,
    expected_operation: str,
    expected_attempt_id: str | None = None,
    expected_target_kind: str = "issue",
) -> dict[str, object]:
    """Select the exactly-one trusted CKR6 result answering a pending request.

    Scans a bounded iterable of GitHub issue-comment records. Non-result
    comments are ignored. Candidates whose record is untrusted (wrong producer,
    location, timing, or malformed metadata) or unparsable are discarded
    BEFORE deduplication, so a forged comment can neither satisfy the request
    nor force an ambiguity. Fails closed when no trusted result answers the
    request (``result-not-returned``) or when two distinct trusted payloads
    claim it. Identical duplicates collapse to one. The selection is then bound
    through ``consume_ckr6_result_comment``. ``expected_target_kind`` is
    ``"issue"`` for an ordinary issue and ``"pr"`` for a top-level PR
    Conversation comment; the HTML location must match that kind exactly.
    """
    if comments is None or isinstance(comments, (str, bytes, Mapping)):
        raise TypeError("comments must be an iterable of comment records")
    expected_request_comment_id = _expected_id(
        expected_request_comment_id, "expected_request_comment_id"
    )
    expected_issue_number = _expected_id(expected_issue_number, "expected_issue_number")
    if expected_target_kind not in ("issue", "pr"):
        raise ValueError("expected_target_kind must be issue or pr")
    distinct: dict[str, Mapping[str, object]] = {}
    for comment in comments:
        if not isinstance(comment, Mapping):
            continue
        body = comment.get("body")
        if type(body) is not str or not body.startswith(CKR6_RESULT_MARKER + "\n"):
            continue
        try:
            _trusted_result_body(
                comment,
                expected_request_comment_id=expected_request_comment_id,
                expected_request_created_at=expected_request_created_at,
                expected_issue_number=expected_issue_number,
                expected_repository=expected_repository,
                expected_target_kind=expected_target_kind,
            )
            parsed = parse_ckr6_result_comment(body)
        except (TypeError, ValueError):
            continue
        if parsed.get("request_comment_id") != expected_request_comment_id:
            continue
        distinct[_canonical_result_json(parsed)] = comment
    if not distinct:
        raise ValueError("CKR6 result not returned for the pending request")
    if len(distinct) > 1:
        raise ValueError("ambiguous CKR6 result for the pending request")
    return consume_ckr6_result_comment(
        next(iter(distinct.values())),
        expected_request_comment_id=expected_request_comment_id,
        expected_request_created_at=expected_request_created_at,
        expected_issue_number=expected_issue_number,
        expected_repository=expected_repository,
        expected_operation=expected_operation,
        expected_attempt_id=expected_attempt_id,
        expected_target_kind=expected_target_kind,
    )


def ckr6_result_admits_boundary(payload: Mapping[str, object]) -> bool:
    """Return True only if a CONSUMED result admits its own boundary.

    issue-start: first-hypothesis admission. failed-repair: retry mutation
    admission. Everything else (blocked, fallback, learning results) is STOP.
    This is an execution-order decision only; it grants no repository write,
    merge, or closure authority. Call it only on ``consume``/``select`` output.

    A ``sufficient`` issue-start result additionally requires a non-empty
    ``selected_lesson_ids`` list of non-blank, unique strings (T11/Q1). The
    real producer can never emit sufficient-with-empty or with duplicates --
    select_coding_knowledge returns SUFFICIENT only from a non-empty best
    bucket (an empty ranked set is INSUFFICIENT) and deduplicates identities
    before selection -- so this changes no real-traffic behavior; it closes
    the consumer gap where a forged sufficient-with-empty record admitted.
    ``not-needed`` and ``unavailable-safe-fallback`` legitimately carry empty
    selections and are unchanged.
    """
    if payload.get("operation") == "issue-start":
        if payload.get("status") == "sufficient":
            selected = payload.get("selected_lesson_ids")
            if (
                not isinstance(selected, list)
                or not selected
                or any(type(item) is not str or not item.strip() for item in selected)
                or len(set(selected)) != len(selected)
            ):
                return False
        return payload.get("substantial_hypothesis_admissible") is True
    if payload.get("operation") == "failed-repair":
        return payload.get("mutation_admissible") is True
    return False


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


# --- #3951 post-merge live failure: sanitized transport diagnostics ------
# Run 43340181423 (2026-11-13, first PR-conversation CKR6 request) failed
# both postback paths with a bare ``HTTP Error 403: Forbidden``: the
# transports swallowed the HTTPError body and headers, so the refusal could
# not be attributed (missing scope vs target state vs platform policy).
# Surface a bounded, sanitized diagnostic instead: status, the GitHub
# ``message`` field, and the ``X-Accepted-GitHub-Permissions`` /
# ``X-GitHub-Request-Id`` headers. Never the token, the request headers, or
# an unbounded response body.
MAX_DIAGNOSTIC_MESSAGE_CHARS = 200
_MAX_DIAGNOSTIC_BODY_BYTES = 8192
# GitHub authors the surfaced fields, but a reflected response could still
# echo caller-supplied text, so redact token-shaped substrings and strip
# control characters before anything reaches the log.
_DIAGNOSTIC_SECRET_PATTERNS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{16,}"),
)


def _sanitize_diagnostic_text(value: str, *, token: str, ascii_only: bool = False) -> str:
    if ascii_only:
        text = "".join(ch if 32 <= ord(ch) <= 126 else " " for ch in value)
    else:
        text = "".join(ch if ch.isprintable() else " " for ch in value)
    # Redact the exact credential first: a reflecting server could echo it
    # verbatim inside an otherwise ordinary message field.
    if token:
        text = text.replace(token, "[redacted]")
    for pattern in _DIAGNOSTIC_SECRET_PATTERNS:
        text = pattern.sub("[redacted]", text)
    return text


def _http_failure_diagnostics(exc: BaseException, *, token: str = "") -> str:
    """Bounded, sanitized description of a GitHub transport failure."""
    import urllib.error

    if type(exc) is not urllib.error.HTTPError:
        return type(exc).__name__
    parts = [f"HTTP {exc.code}"]
    try:
        # Bounded read: at most limit+1 bytes are consumed, and an oversized
        # body is never parsed at all.
        body = exc.read(_MAX_DIAGNOSTIC_BODY_BYTES + 1)
    except Exception:
        body = b""
    message = ""
    if isinstance(body, (bytes, bytearray)) and 0 < len(body) <= _MAX_DIAGNOSTIC_BODY_BYTES:
        try:
            payload = json.loads(bytes(body).decode("utf-8"))
        except Exception:
            payload = None
        if isinstance(payload, Mapping) and type(payload.get("message")) is str:
            message = payload["message"]
    if message:
        parts.append(
            f"message={_sanitize_diagnostic_text(message, token=token)[:MAX_DIAGNOSTIC_MESSAGE_CHARS]!r}"
        )
    headers = getattr(exc, "headers", None)
    if headers is not None:
        for name in ("X-Accepted-GitHub-Permissions", "X-GitHub-Request-Id"):
            value = headers.get(name)
            if type(value) is str and value:
                parts.append(
                    f"{name.lower()}={_sanitize_diagnostic_text(value, token=token, ascii_only=True)[:MAX_DIAGNOSTIC_MESSAGE_CHARS]!r}"
                )
    return "; ".join(parts)


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
    except Exception as exc:
        # Lookup failure is still not evidence of absence of work: the
        # caller posts, preferring a duplicate receipt over silence. But
        # record the bounded diagnostic so a live refusal shows whether
        # the dedupe GET and the POST fail independently.
        import sys

        print(
            "CKR6 result dedupe lookup failed: "
            + _http_failure_diagnostics(exc, token=token),
            file=sys.stderr,
        )
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
        raise RuntimeError(
            "CKR6 result postback failed: " + _http_failure_diagnostics(exc, token=token)
        ) from exc
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
        result = rejection_result(event, args.repository, rejection_reason(exc))
    else:
        # Errors raised below are deliberately outside the except above.
        if args.phase == "classify":
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
