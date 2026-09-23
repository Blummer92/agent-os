"""Finite GitHub issue-comment bridge to the existing CKR6 owners (#2851).

The transport owns only low-trust envelope validation and bounded result
projection. CKR2/CKR6 materiality, lesson selection, failed-repair semantics,
and Notion reads remain with their existing owners.
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from agent_memory_context_manager.coding_knowledge_selection import CodingKnowledgeRequest
from agent_memory_context_manager.lesson_preflight import RepairContext, plan_lesson_preflight

from .issue_start_lesson_preflight import activate_issue_start_lesson_preflight
from .lesson_reader_composition import resolve_lesson_read_route
from .mcp_facade import activate_agent_os_failed_repair

COMMAND_PREFIX = "/agent-os ckr6 "
MAX_COMMENT_BYTES = 16 * 1024
MAX_HINTS = 20
MAX_TEXT = 512
OPERATIONS = frozenset({"issue-start", "failed-repair"})
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


def parse_envelope(payload: Mapping[str, object]) -> Ckr6Envelope:
    if not isinstance(payload, Mapping):
        raise TypeError("CKR6 envelope must be a mapping")
    operation = payload.get("operation")
    if operation not in OPERATIONS:
        raise ValueError("operation must be issue-start or failed-repair")
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
        repair_context=_text(payload.get("repair_context", "failed-pr-repair"), "repair_context") if failed else "failed-pr-repair",
        **kwargs,
    )


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
    try:
        payload = json.loads(body[len(COMMAND_PREFIX):])
    except json.JSONDecodeError as exc:
        raise ValueError("CKR6 command payload must be one JSON object") from exc
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
        return {
            "operation": envelope.operation,
            "repository": envelope.repository,
            "issue_number": envelope.issue_number,
            "status": "manual-review",
            "reason_codes": [route.reason_code if route is not None else "lesson-read-route-unavailable"],
            "selected_lesson_ids": [],
            "canonical_github_refs": [],
            "mutation_admissible": False,
            "execution_authorized": False,
            "github_writes_authorized": False,
            "merge_authorized": False,
            "closure_authorized": False,
            "side_effects_performed": False,
        }
    reader = route.execute_read if route is not None else None
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
        return {
            "operation": envelope.operation,
            "repository": envelope.repository,
            "issue_number": envelope.issue_number,
            "status": raw["lesson_retrieval_status"],
            "reason_codes": raw["selection_reason_codes"],
            "selected_lesson_ids": raw["selected_lesson_ids"],
            "canonical_github_refs": raw["canonical_github_refs"],
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
        "reason_codes": raw["reason_codes"],
        "selected_lesson_ids": raw["selected_lesson_ids"],
        "canonical_github_refs": raw["canonical_github_refs"],
        "mutation_admissible": raw["mutation_admissible"],
        "blocking_attempt_id": raw["blocking_attempt_id"],
        "execution_authorized": False,
        "github_writes_authorized": False,
        "merge_authorized": False,
        "closure_authorized": False,
        "side_effects_performed": False,
    }


def _load_event(path: str) -> Mapping[str, object]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError("event payload must be an object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("classify", "execute"), required=True)
    parser.add_argument("--event", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--allowed-actor", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--retrieval-required", choices=("true", "false"))
    args = parser.parse_args()

    envelope = envelope_from_event(
        _load_event(args.event),
        expected_repository=args.repository,
        allowed_actor=args.allowed_actor,
    )
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
