"""Offline no-write A/B slide preview for governed lesson content (#3509).

The 2026-10-09 / 2026-10-20 #3509 incidents shared one shape: a teacher asked
for fresh slides from an existing Notion lesson, and the host composed from
something else -- historical Drive decks first, then a synthetic invented
lesson -- because no repository-owned executable consumer enforced the
Notion-first source order for *slides*. The governed lesson-content adapter
(#3580/#3582, ``lesson_content_result``) already proves a lesson's identity
fail-closed, and ``worksheet_preview`` already consumes it offline -- but
only for worksheets. There was no slide equivalent, and no A/B pairing that
keeps two variants bound to the same verified lesson.

This module is that slide consumer. It is enforceably offline: it imports no
Notion, Drive, Slides, or Docs client, no credential loader, no live builder,
and no placement transport, and it writes nothing (the CLI may persist the
receipt to a local path). It reuses the existing governed route exactly as
``worksheet_preview`` does -- authored YAML -> ``compose_lesson_content_result``
-> ``build_slides_replace_requests`` -- so Notion-first resolution is not a
policy statement here, it is the only way in: without a caller-bound,
verified-current governed lesson-content result that matches the requested
request / canonical unit / day / run provenance exactly, every variant is
``blocked`` and no planned slide content is emitted. Authored objectives that
carry another lesson's target (the synthetic-substitution case) are refused
by the adapter's objective reconciliation, unchanged.

An A/B preview is ``preview`` only when *both* variants preview against the
*same* verified lesson identity. The receipt's evaluation gate therefore
cannot report ready -- and ``evaluate_slides_ab_preview`` cannot return
``ready-for-evaluation`` -- unless both source-matched slide artifacts (here,
planned-content previews) exist. No receipt in this module claims a rendered
or native Google Slides artifact, classroom readiness, a winning variant, or
any production / publication / external-write authority: a caller-bound
historical read (for example the pinned run-38462963519 fixture) is read-only
lesson evidence, never live production authorization, and this module never
claims a live Notion read occurred.

Trust model of the evaluation gate, stated exactly: ``ready-for-evaluation``
proves that caller-held governed evidence verifies for the caller-held
selection, that the receipt's lesson identity, lesson content, and every
governed context token in the planned replacements equal that verified
lesson (or their fixed ``"false"`` values), that each variant's recorded
hash recomputes over its replacements, and that both variants cover the
same producer-recorded slide-index set. It does not prove the receipt was
produced by this module, and it cannot prove the authenticity of authored
slide or question text: authored material is the teacher's by design --
Notion supplies no slides or questions -- so the gate binds the *lesson*
the authored variants are about, never the authored wording itself.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .artifact_content_qa import normalize_text, scan_unresolved_tokens
from .content_spec import LessonContent
from .lesson_content_result import (
    OBJECTIVE_SOURCE_AUTHORED,
    OBJECTIVE_SOURCE_GOVERNED,
    TOKEN_DAY,
    TOKEN_FOCUS,
    TOKEN_GENERATED_AT,
    TOKEN_LOGICAL_SOURCE,
    TOKEN_OBJECTIVE_SOURCE,
    TOKEN_RECORD_URL,
    TOKEN_SOURCE_EVIDENCE,
    TOKEN_TARGET,
    TOKEN_UNIT_PAGE_ID,
    TOKEN_VERIFICATION_STATE,
    TOKEN_REQUEST_ID,
    TOKEN_VOCABULARY,
    LessonContentResultError,
    LessonContentSelection,
    compose_lesson_content_result,
    lesson_content_result_from_evidence,
    verify_lesson_content_result,
)
from .slides_requests import QA_SLIDE_INDEX_KEY, build_slides_replace_requests

PREVIEW_CONTRACT = "imc-lesson-slides-ab-preview-v1"
PREVIEW = "preview"
BLOCKED = "blocked"
READY_FOR_EVALUATION = "ready-for-evaluation"

#: Exact recorded-check key sets a genuine receipt carries (producer-pinned).
_AB_CHECK_KEYS = frozenset(
    {
        "variant_a_preview",
        "variant_b_preview",
        "same_lesson_identity",
        "same_lesson_content",
        "variants_differ_in_authored_slides",
    }
)
_VARIANT_CHECK_KEYS = frozenset(
    {
        "authored_slides_preserved",
        "authored_title_preserved",
        "learning_target_planned",
        "learning_target_in_objectives",
        "daily_focus_planned",
        "key_vocabulary_absent_when_unsourced",
        "no_unresolved_tokens",
        "slide_indexes_complete_and_unique",
    }
)

#: Lesson-identity fields that must be identical across both A/B variants.
_IDENTITY_FIELDS = (
    "request_id",
    "generated_at",
    "logical_source",
    "verification_state",
    "canonical_unit_page_id",
    "day_lesson_number",
    "record_url",
    "source_evidence",
)


def preview_lesson_slides(
    content: LessonContent,
    lesson_content_evidence: object,
    selection: LessonContentSelection,
    *,
    variant: str = "A",
) -> dict[str, Any]:
    """Return a bounded offline planned-slides preview receipt for one variant.

    ``status`` is ``preview`` only when the governed adapter accepts the
    evidence for the exact bound selection and every deterministic slide
    check passes; otherwise ``blocked`` with a closed-vocabulary
    ``reason_code`` and no planned content.
    """
    try:
        result = lesson_content_result_from_evidence(lesson_content_evidence)
        lesson = verify_lesson_content_result(result, selection)
        composed = compose_lesson_content_result(content, result, selection)
    except LessonContentResultError as exc:
        return _variant_receipt(BLOCKED, selection, variant, reason_code=exc.reason_code, detail=str(exc))

    requests = build_slides_replace_requests(composed)
    planned = []
    for request in requests:
        item = {
            "token": request["replaceAllText"]["containsText"]["text"][2:-2],
            "text": request["replaceAllText"]["replaceText"],
        }
        if QA_SLIDE_INDEX_KEY in request:
            item["slide_index"] = request[QA_SLIDE_INDEX_KEY]
        planned.append(item)
    planned_by_token = {item["token"]: item["text"] for item in planned}

    authored_indexes = sorted(set(composed.slide_token_indexes().values()))
    planned_slide_indexes = sorted({item["slide_index"] for item in planned if "slide_index" in item})
    unresolved = sorted({token for item in planned for token in scan_unresolved_tokens(item["text"])})
    checks = {
        "authored_slides_preserved": composed.slides == content.slides,
        "authored_title_preserved": planned_by_token.get("title") == content.title,
        "learning_target_planned": planned_by_token.get(TOKEN_TARGET) == lesson.daily_learning_target,
        "learning_target_in_objectives": normalize_text(lesson.daily_learning_target)
        in {normalize_text(item) for item in composed.objectives},
        "daily_focus_planned": planned_by_token.get(TOKEN_FOCUS) == lesson.daily_focus,
        "key_vocabulary_absent_when_unsourced": lesson.key_vocabulary is not None
        or TOKEN_VOCABULARY not in planned_by_token,
        "no_unresolved_tokens": not unresolved,
        # No duplicate slide indices (the canonical token map would collapse
        # them) and no missing slide index: every authored slide must reach
        # the planned replacements under its own governed index.
        "slide_indexes_complete_and_unique": planned_slide_indexes == authored_indexes
        and len(planned_slide_indexes) == len({slide["index"] for slide in composed.slides}),
    }
    failed = sorted(name for name, passed in checks.items() if passed is not True)
    if failed:
        return _variant_receipt(
            BLOCKED, selection, variant,
            reason_code="preview-check-failed",
            detail="failed checks: " + ", ".join(failed),
            checks=checks,
        )

    slides = {
        "title": composed.title,
        "objectives": list(composed.objectives),
        "objective_source": planned_by_token[TOKEN_OBJECTIVE_SOURCE],
        "learning_target": lesson.daily_learning_target,
        "daily_focus": lesson.daily_focus,
        "key_vocabulary": lesson.key_vocabulary,
        "slide_indexes": planned_slide_indexes,
        "planned_replacements": planned,
        "planned_content_sha256": _sha256(planned),
    }
    identity = _lesson_identity(lesson, planned_by_token)
    return _variant_receipt(PREVIEW, selection, variant, lesson=identity, slides=slides, checks=checks)


def preview_lesson_slides_ab(
    content_a: LessonContent,
    content_b: LessonContent,
    lesson_content_evidence: object,
    selection: LessonContentSelection,
) -> dict[str, Any]:
    """Return the A/B receipt: two variants bound to one verified lesson.

    ``status`` is ``preview`` only when both variants preview and their
    verified lesson identities are byte-identical on every identity field.
    Evaluation is never performed here; the gate only reports whether both
    source-matched artifacts exist so an evaluation *may* begin.
    """
    variant_a = preview_lesson_slides(content_a, lesson_content_evidence, selection, variant="A")
    variant_b = preview_lesson_slides(content_b, lesson_content_evidence, selection, variant="B")

    both_preview = variant_a["status"] == PREVIEW and variant_b["status"] == PREVIEW
    same_identity = bool(both_preview) and all(
        variant_a["lesson"][field] == variant_b["lesson"][field] for field in _IDENTITY_FIELDS
    )
    same_lesson_content = bool(both_preview) and (
        variant_a["slides"]["learning_target"] == variant_b["slides"]["learning_target"]
        and variant_a["slides"]["daily_focus"] == variant_b["slides"]["daily_focus"]
        and variant_a["slides"]["objectives"] == variant_b["slides"]["objectives"]
    )
    checks = {
        "variant_a_preview": variant_a["status"] == PREVIEW,
        "variant_b_preview": variant_b["status"] == PREVIEW,
        "same_lesson_identity": same_identity,
        "same_lesson_content": same_lesson_content,
        "variants_differ_in_authored_slides": bool(both_preview)
        and variant_a["slides"]["planned_content_sha256"] != variant_b["slides"]["planned_content_sha256"],
    }
    evaluation_ready = all(checks.values())
    if both_preview and evaluation_ready:
        status, reason_code, detail = PREVIEW, None, None
    elif both_preview and not checks["variants_differ_in_authored_slides"]:
        status = BLOCKED
        reason_code = "ab-variants-identical"
        detail = "A/B variants carry identical planned slide content; there is nothing to compare"
    elif both_preview:
        status = BLOCKED
        reason_code = "ab-identity-mismatch"
        detail = "A/B variants do not share one verified lesson identity and lesson content"
    else:
        status = BLOCKED
        blocked = variant_a if variant_a["status"] != PREVIEW else variant_b
        reason_code = blocked["reason_code"] or "preview-check-failed"
        detail = blocked["detail"]

    bound = _bound_selection(selection)
    return {
        "contract_version": PREVIEW_CONTRACT,
        "status": status,
        "reason_code": reason_code,
        "detail": detail,
        "preview_kind": "planned-slides-ab",
        "rendered": False,
        "native_artifact": None,
        "classroom_ready": False,
        # This receipt consumes a caller-bound governed result; it does not
        # perform or claim a live Notion read, and a historical bound run is
        # read-only evidence, not production authorization.
        "live_notion_read_claimed": False,
        "selection": bound,
        "lesson": variant_a["lesson"] if both_preview else None,
        "variants": {"A": variant_a, "B": variant_b},
        "checks": checks,
        "evaluation": {
            "ready": evaluation_ready,
            "performed": False,
            "winner": None,
            "status": READY_FOR_EVALUATION if evaluation_ready else BLOCKED,
        },
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


def evaluate_slides_ab_preview(
    ab_receipt: object,
    lesson_content_evidence: object,
    selection: LessonContentSelection,
) -> dict[str, Any]:
    """Gate visual evaluation on both source-matched artifacts existing.

    Caller-bound, like the #3582 adapter: the governed evidence and the
    exact selection are held *outside* the receipt and re-verified here, so
    a receipt cannot certify itself. Returns ``ready-for-evaluation`` only
    when the evidence verifies for the selection, the receipt's lesson
    identity and lesson content equal that verified lesson exactly, both
    variants carry the governed context tokens in their planned
    replacements, each variant's recorded content hash recomputes over its
    replacements, both variants cover the same slide-index set, every
    recorded check is true, and no authority, rendering, readiness, or
    live-read claim appears anywhere in the receipt. A hand-built or
    hand-edited receipt -- forged or stripped ``slides``, invented lesson
    identity, identical variant hashes under an edited top-level status,
    flipped authority flags, diverged lesson content -- is ``blocked``
    with ``evaluation-artifacts-missing`` (or ``ab-identity-mismatch`` when
    the two lesson identities differ, or the adapter's reason code when the
    governed evidence itself does not verify).
    This gate performs no scoring and names no winner (#3298: no evaluation
    before inspectable artifacts).
    """
    blocked = {
        "status": BLOCKED,
        "reason_code": "evaluation-artifacts-missing",
        "performed": False,
        "winner": None,
    }
    if not isinstance(ab_receipt, dict):
        return blocked
    try:
        verified = verify_lesson_content_result(
            lesson_content_result_from_evidence(lesson_content_evidence), selection
        )
    except LessonContentResultError as exc:
        return {**blocked, "reason_code": exc.reason_code}
    if ab_receipt.get("contract_version") != PREVIEW_CONTRACT or ab_receipt.get("status") != PREVIEW:
        return blocked
    if not _honest_receipt_claims(ab_receipt):
        return blocked
    checks = ab_receipt.get("checks")
    if not isinstance(checks, dict) or set(checks.keys()) != _AB_CHECK_KEYS \
            or any(value is not True for value in checks.values()):
        return blocked
    evaluation = ab_receipt.get("evaluation")
    if not isinstance(evaluation, dict) or evaluation.get("ready") is not True \
            or evaluation.get("performed") is not False or evaluation.get("winner") is not None:
        return blocked
    variants = ab_receipt.get("variants")
    if not isinstance(variants, dict):
        return blocked
    variant_a, variant_b = variants.get("A"), variants.get("B")
    if not _variant_artifact_present(variant_a) or not _variant_artifact_present(variant_b):
        return blocked
    lesson_a, lesson_b = variant_a["lesson"], variant_b["lesson"]
    if any(lesson_a.get(field) != lesson_b.get(field) for field in _IDENTITY_FIELDS):
        return {**blocked, "reason_code": "ab-identity-mismatch"}
    expected_identity = {
        "request_id": verified.request_id,
        "generated_at": verified.generated_at,
        "logical_source": verified.logical_source,
        "verification_state": verified.verification_state,
        "canonical_unit_page_id": verified.canonical_unit_page_id,
        "day_lesson_number": verified.day_lesson_number,
        "record_url": verified.record_url,
        "source_evidence": verified.source_evidence,
    }
    if any(lesson_a.get(field) != value for field, value in expected_identity.items()):
        return {**blocked, "reason_code": "ab-identity-mismatch"}
    slides_a, slides_b = variant_a["slides"], variant_b["slides"]
    if slides_a.get("learning_target") != verified.daily_learning_target \
            or slides_a.get("daily_focus") != verified.daily_focus:
        return {**blocked, "reason_code": "ab-identity-mismatch"}
    if slides_a.get("slide_indexes") != slides_b.get("slide_indexes"):
        return blocked
    # The planned replacements themselves must carry every governed context
    # token of the verified lesson with its verified value, the three
    # fixed-false authority context tokens, and objective tokens that match
    # the recorded objectives -- arbitrary replacement tokens that merely
    # coexist with a copied lesson dict do not bind the artifacts to the
    # source, and no governed provenance or authority value may be restated.
    expected_tokens = {
        TOKEN_REQUEST_ID: verified.request_id,
        TOKEN_GENERATED_AT: verified.generated_at,
        TOKEN_LOGICAL_SOURCE: verified.logical_source,
        TOKEN_VERIFICATION_STATE: verified.verification_state,
        TOKEN_UNIT_PAGE_ID: verified.canonical_unit_page_id,
        TOKEN_DAY: verified.day_lesson_number,
        TOKEN_TARGET: verified.daily_learning_target,
        TOKEN_SOURCE_EVIDENCE: verified.source_evidence,
        TOKEN_RECORD_URL: verified.record_url,
        "context_production_authorized": "false",
        "context_publication_authorized": "false",
        "context_external_write_authorized": "false",
    }
    if verified.daily_focus is not None:
        expected_tokens[TOKEN_FOCUS] = verified.daily_focus
    if verified.key_vocabulary is not None:
        expected_tokens[TOKEN_VOCABULARY] = verified.key_vocabulary
    governed_objectives = [verified.daily_learning_target]
    if verified.daily_focus is not None:
        governed_objectives.append(verified.daily_focus)
    for slides in (slides_a, slides_b):
        planned_by_token = {item["token"]: item["text"] for item in slides["planned_replacements"]}
        if any(planned_by_token.get(token) != value for token, value in expected_tokens.items()):
            return {**blocked, "reason_code": "ab-identity-mismatch"}
        if verified.daily_focus is None and TOKEN_FOCUS in planned_by_token:
            return {**blocked, "reason_code": "ab-identity-mismatch"}
        if verified.key_vocabulary is None and TOKEN_VOCABULARY in planned_by_token:
            return {**blocked, "reason_code": "ab-identity-mismatch"}
        if slides.get("key_vocabulary") != verified.key_vocabulary:
            return {**blocked, "reason_code": "ab-identity-mismatch"}
        if slides.get("title") != planned_by_token.get("title"):
            return blocked
        objective_source = planned_by_token.get(TOKEN_OBJECTIVE_SOURCE)
        if objective_source not in (OBJECTIVE_SOURCE_AUTHORED, OBJECTIVE_SOURCE_GOVERNED):
            return {**blocked, "reason_code": "ab-identity-mismatch"}
        if slides.get("objective_source") != objective_source:
            return {**blocked, "reason_code": "ab-identity-mismatch"}
        objectives = slides.get("objectives")
        if objective_source == OBJECTIVE_SOURCE_GOVERNED and objectives != governed_objectives:
            return {**blocked, "reason_code": "ab-identity-mismatch"}
        if normalize_text(verified.daily_learning_target) not in {
            normalize_text(item) for item in objectives
        }:
            return {**blocked, "reason_code": "ab-identity-mismatch"}
        for position, objective in enumerate(objectives, start=1):
            if planned_by_token.get(f"objective_{position}") != objective:
                return blocked
        if f"objective_{len(objectives) + 1}" in planned_by_token:
            return blocked
    # Top-level lesson/selection, when the receipt carries them, must be the
    # verified lesson and the caller-bound selection -- never free-standing.
    if ab_receipt.get("lesson") != lesson_a:
        return {**blocked, "reason_code": "ab-identity-mismatch"}
    if ab_receipt.get("selection") != _bound_selection(selection):
        return {**blocked, "reason_code": "ab-identity-mismatch"}
    for field in ("learning_target", "daily_focus", "objectives"):
        if slides_a.get(field) != slides_b.get(field):
            return {**blocked, "reason_code": "ab-identity-mismatch"}
    if slides_a["planned_content_sha256"] == slides_b["planned_content_sha256"]:
        return {**blocked, "reason_code": "ab-variants-identical"}
    return {
        "status": READY_FOR_EVALUATION,
        "reason_code": None,
        "performed": False,
        "winner": None,
        "lesson": lesson_a,
    }


_AUTHORITY_KEYS = frozenset(
    {"execution_authorized", "external_write_authorized", "production_authorized", "publication_authorized"}
)
_SIDE_EFFECT_KEYS = frozenset(
    {
        "notion_writes_performed",
        "drive_writes_performed",
        "credentials_initialized",
        "native_artifact_created",
        "classroom_publication_performed",
    }
)


def _honest_receipt_claims(receipt: dict[str, Any]) -> bool:
    """True only when a receipt claims no rendering, readiness, or authority.

    The authority and side-effect key sets must be exactly the published
    sets, present and false -- an empty or partial mapping proves nothing.
    """
    if receipt.get("rendered") is not False or receipt.get("classroom_ready") is not False:
        return False
    if receipt.get("live_notion_read_claimed") is not False:
        return False
    if receipt.get("native_artifact") is not None:
        return False
    authority = receipt.get("authority")
    if not isinstance(authority, dict) or set(authority.keys()) != _AUTHORITY_KEYS \
            or any(value is not False for value in authority.values()):
        return False
    side_effects = receipt.get("side_effects")
    if not isinstance(side_effects, dict) or set(side_effects.keys()) != _SIDE_EFFECT_KEYS \
            or any(value is not False for value in side_effects.values()):
        return False
    return True


def _variant_artifact_present(variant: object) -> bool:
    """True only when a variant carries a real, hash-consistent slide artifact.

    ``planned_content_sha256`` must recompute over the recorded planned
    replacements, ``slide_indexes`` must be exactly the slide-scoped indexes
    those replacements carry, and every recorded variant check must be true.
    """
    if not isinstance(variant, dict):
        return False
    if variant.get("contract_version") != PREVIEW_CONTRACT or variant.get("status") != PREVIEW:
        return False
    if not _honest_receipt_claims(variant):
        return False
    checks = variant.get("checks")
    if not isinstance(checks, dict) or set(checks.keys()) != _VARIANT_CHECK_KEYS \
            or any(value is not True for value in checks.values()):
        return False
    lesson = variant.get("lesson")
    if not isinstance(lesson, dict) or any(not lesson.get(field) for field in _IDENTITY_FIELDS):
        return False
    slides = variant.get("slides")
    if not isinstance(slides, dict):
        return False
    planned = slides.get("planned_replacements")
    if not isinstance(planned, list) or not planned:
        return False
    for item in planned:
        if not isinstance(item, dict) or not isinstance(item.get("token"), str) \
                or not isinstance(item.get("text"), str):
            return False
        if "slide_index" in item and (isinstance(item["slide_index"], bool)
                                      or not isinstance(item["slide_index"], int)):
            return False
    # The producer builds replacements from a token dict, so a genuine
    # receipt never repeats a token name. A duplicate would let a dict
    # collapse hide an earlier forged value behind the genuine one.
    token_names = [item["token"] for item in planned]
    if len(token_names) != len(set(token_names)):
        return False
    if slides.get("planned_content_sha256") != _sha256(planned):
        return False
    planned_indexes = sorted({item["slide_index"] for item in planned if "slide_index" in item})
    if not planned_indexes or slides.get("slide_indexes") != planned_indexes:
        return False
    if not isinstance(slides.get("learning_target"), str) or not slides["learning_target"]:
        return False
    if not isinstance(slides.get("objectives"), list) or not slides["objectives"]:
        return False
    return True


def _lesson_identity(lesson: Any, planned_by_token: dict[str, str]) -> dict[str, Any]:
    return {
        "request_id": lesson.request_id,
        "generated_at": lesson.generated_at,
        "logical_source": lesson.logical_source,
        "verification_state": lesson.verification_state,
        "canonical_unit_page_id": lesson.canonical_unit_page_id,
        "day_lesson_number": planned_by_token[TOKEN_DAY],
        "record_url": planned_by_token[TOKEN_RECORD_URL],
        "source_evidence": lesson.source_evidence,
    }


def _bound_selection(selection: object) -> dict[str, Any] | None:
    if not isinstance(selection, LessonContentSelection):
        return None
    return {
        "request_id": selection.request_id,
        "canonical_unit_page_id": selection.canonical_unit_page_id,
        "day_lesson_number": selection.day_lesson_number,
        "generated_at": selection.generated_at,
    }


def _variant_receipt(
    status: str,
    selection: LessonContentSelection,
    variant: str,
    *,
    reason_code: str | None = None,
    detail: str | None = None,
    lesson: dict[str, Any] | None = None,
    slides: dict[str, Any] | None = None,
    checks: dict[str, bool] | None = None,
) -> dict[str, Any]:
    return {
        "contract_version": PREVIEW_CONTRACT,
        "status": status,
        "reason_code": reason_code,
        "detail": detail,
        "variant": variant,
        "preview_kind": "planned-slides-content",
        "rendered": False,
        "native_artifact": None,
        "classroom_ready": False,
        "live_notion_read_claimed": False,
        "selection": _bound_selection(selection),
        "lesson": lesson,
        "slides": slides,
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


__all__ = [
    "BLOCKED",
    "PREVIEW",
    "PREVIEW_CONTRACT",
    "READY_FOR_EVALUATION",
    "evaluate_slides_ab_preview",
    "preview_lesson_slides",
    "preview_lesson_slides_ab",
]
