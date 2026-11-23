"""Offline no-write worksheet content preview for governed lesson content (#3582).

The preview runs the real composition path a connected worksheet build uses
for lesson text -- authored YAML -> ``compose_lesson_content_result`` ->
``build_docs_replace_requests`` -- and reports the planned worksheet content
as a bounded, attributable receipt. It is enforceably offline: this module
imports no Drive/Docs/Slides client, credential loader, live builder, or
placement transport, and it writes nothing (the CLI may persist the receipt
to a local path).

The receipt is a *planned-content* preview, not a rendered document. It never
claims a native Google Docs identity or revision, never reports a worksheet
as final or classroom-ready, and grants no execution, production,
publication, or external-write authority. Connected builds keep their own
governed MaterialRequirement/current-curriculum, terminal-QA, and admission
gates unchanged.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .artifact_content_qa import normalize_text, scan_unresolved_tokens
from .content_spec import LessonContent
from .docs_requests import build_docs_replace_requests
from .lesson_content_result import (
    TOKEN_DAY,
    TOKEN_FOCUS,
    TOKEN_OBJECTIVE_SOURCE,
    TOKEN_RECORD_URL,
    TOKEN_TARGET,
    TOKEN_VOCABULARY,
    LessonContentResultError,
    LessonContentSelection,
    compose_lesson_content_result,
    lesson_content_result_from_evidence,
    verify_lesson_content_result,
)

PREVIEW_CONTRACT = "imc-lesson-worksheet-preview-v1"
PREVIEW = "preview"
BLOCKED = "blocked"


def preview_lesson_worksheet(
    content: LessonContent,
    lesson_content_evidence: object,
    selection: LessonContentSelection,
) -> dict[str, Any]:
    """Return a bounded offline worksheet-content preview receipt.

    ``status`` is ``preview`` only when the adapter accepts the evidence and
    every deterministic content check passes; otherwise it is ``blocked``
    with a closed-vocabulary ``reason_code`` and no planned content.
    """
    try:
        result = lesson_content_result_from_evidence(lesson_content_evidence)
        lesson = verify_lesson_content_result(result, selection)
        composed = compose_lesson_content_result(content, result, selection)
    except LessonContentResultError as exc:
        return _receipt(BLOCKED, selection, reason_code=exc.reason_code, detail=str(exc))

    requests = build_docs_replace_requests(composed)
    planned = [
        {
            "token": request["replaceAllText"]["containsText"]["text"][2:-2],
            "text": request["replaceAllText"]["replaceText"],
        }
        for request in requests
    ]
    planned_by_token = {item["token"]: item["text"] for item in planned}
    questions = list(content.worksheet_questions)
    unresolved = sorted({token for item in planned for token in scan_unresolved_tokens(item["text"])})
    checks = {
        "authored_questions_preserved": composed.worksheet_questions == questions
        and all(planned_by_token.get(f"question_{i}") == q for i, q in enumerate(questions, start=1)),
        "authored_slides_preserved": composed.slides == content.slides,
        "authored_title_preserved": planned_by_token.get("title") == content.title,
        "learning_target_planned": planned_by_token.get(TOKEN_TARGET) == lesson.daily_learning_target,
        "learning_target_in_objectives": normalize_text(lesson.daily_learning_target)
        in {normalize_text(item) for item in composed.objectives},
        "daily_focus_planned": planned_by_token.get(TOKEN_FOCUS) == lesson.daily_focus,
        "key_vocabulary_absent_when_unsourced": lesson.key_vocabulary is not None
        or TOKEN_VOCABULARY not in planned_by_token,
        "no_unresolved_tokens": not unresolved,
    }
    failed = sorted(name for name, passed in checks.items() if passed is not True)
    if failed:
        return _receipt(
            BLOCKED,
            selection,
            reason_code="preview-check-failed",
            detail="failed checks: " + ", ".join(failed),
            checks=checks,
        )

    worksheet = {
        "title": composed.title,
        "objectives": list(composed.objectives),
        "objective_source": planned_by_token[TOKEN_OBJECTIVE_SOURCE],
        "learning_target": lesson.daily_learning_target,
        "daily_focus": lesson.daily_focus,
        "key_vocabulary": lesson.key_vocabulary,
        "questions": questions,
        "planned_replacements": planned,
        "planned_content_sha256": _sha256(planned),
    }
    identity = {
        "request_id": lesson.request_id,
        "generated_at": lesson.generated_at,
        "logical_source": lesson.logical_source,
        "verification_state": lesson.verification_state,
        "canonical_unit_page_id": lesson.canonical_unit_page_id,
        "day_lesson_number": planned_by_token[TOKEN_DAY],
        "record_url": planned_by_token[TOKEN_RECORD_URL],
        "source_evidence": lesson.source_evidence,
    }
    return _receipt(PREVIEW, selection, lesson=identity, worksheet=worksheet, checks=checks)


def _receipt(
    status: str,
    selection: LessonContentSelection,
    *,
    reason_code: str | None = None,
    detail: str | None = None,
    lesson: dict[str, Any] | None = None,
    worksheet: dict[str, Any] | None = None,
    checks: dict[str, bool] | None = None,
) -> dict[str, Any]:
    bound = (
        {
            "request_id": selection.request_id,
            "canonical_unit_page_id": selection.canonical_unit_page_id,
            "day_lesson_number": selection.day_lesson_number,
            "generated_at": selection.generated_at,
        }
        if isinstance(selection, LessonContentSelection)
        else None
    )
    return {
        "contract_version": PREVIEW_CONTRACT,
        "status": status,
        "reason_code": reason_code,
        "detail": detail,
        "preview_kind": "planned-worksheet-content",
        # Not a rendered document and never a native Google Docs artifact.
        "rendered": False,
        "native_artifact": None,
        "classroom_ready": False,
        "selection": bound,
        "lesson": lesson,
        "worksheet": worksheet,
        "checks": checks,
        "side_effects": {
            "notion_writes_performed": False,
            "drive_writes_performed": False,
            "credentials_initialized": False,
            "native_artifact_created": False,
            "classroom_publication_performed": False,
        },
        "authority": {
            "execution_authorized": False,
            "external_write_authorized": False,
            "production_authorized": False,
            "publication_authorized": False,
        },
    }


def _sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = ["PREVIEW_CONTRACT", "preview_lesson_worksheet"]

