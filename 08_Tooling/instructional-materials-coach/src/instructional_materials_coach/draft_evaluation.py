"""Offline, deterministic, advisory evaluation of one host-supplied lesson draft (#4072).

``imc-build evaluate-draft`` evaluates authored ``LessonContent`` YAML that a
host session wrote. It reports a closed vocabulary of deterministic findings in
one content-safe receipt (``imc-draft-evaluation-v1``). It is a leaf module:
it reuses the existing lesson-content adapter, worksheet preview, student-voice
scan and content normalization, and it imports no Drive, Docs, Slides, Notion,
GitHub, provider or credential code. It performs no I/O; the CLI reads the
bounded input files and persists the receipt.

What a receipt does and does not say:

* ``semantic_review`` is always ``not-performed`` and ``not_evaluated`` lists
  what was not checked. A ``no-deterministic-finding`` status is a statement
  about these checks only. It is never a statement about writing, subject
  accuracy, grade level, student suitability or classroom readiness.
* ``classroom_ready`` is always false and ``preview_only`` is always true. The
  receipt grants no execution, external-write, production or publication
  authority.
* The receipt contains no draft text: only codes, counts, location tokens,
  hashes of exact file bytes and fixed strings.
* ``draft-unchanged-since-prior-draft`` detects one unchanged resubmission. It
  is not a revision budget, a stop rule or a progress check.
* Nothing requires a host to run this evaluation.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import unicodedata
from typing import Any, Mapping

import yaml

from instructional_workflow_contracts.common import AuthorityEvidence, sha256_hex

from .artifact_content_qa import normalize_text
from .content_spec import LessonContent, content_from_dict
from .lesson_content_result import (
    LessonContentSelection,
    lesson_content_result_from_evidence,
    verify_lesson_content_result,
)
from .student_voice import scan_teacher_voice
from .worksheet_preview import PREVIEW, preview_lesson_worksheet

CONTRACT_VERSION = "imc-draft-evaluation-v1"

#: Same bound the existing lesson-content preview applies to its inputs.
MAX_INPUT_BYTES = 262_144
INSTRUCTION_LINE_WORD_LIMIT = 35
MAX_LOCATIONS_PER_FINDING = 32

SUPPORTED_ARTIFACT_TYPES = ("slide-deck", "worksheet")
#: Artifact types owned by the Teacher Modeling Coach (#3562); routed, not evaluated.
TEACHER_MODELING_ARTIFACT_TYPES = ("teacher-guide", "teacher-modeling-package")
TEACHER_MODELING_ROUTING_NOTE = (
    "Route this artifact type to the Teacher Modeling Coach (#3562); this evaluator does not cover it."
)

STATUS_BLOCKED = "blocked"
STATUS_FAIL = "fail"
STATUS_REVIEW = "review"
STATUS_NO_FINDING = "no-deterministic-finding"
EXIT_ZERO_STATUSES = frozenset({STATUS_NO_FINDING, STATUS_REVIEW})

SEMANTIC_REVIEW = "not-performed"
AUDIENCE_FIDELITY = "not-evaluated-deterministically"
#: Always reported as not evaluated.
NOT_EVALUATED_FIXED = ("audience-fit", "factual-accuracy", "instructional-completeness")
NOT_EVALUATED_STRUCTURE_MINIMUM = "structure-minimum"
NOT_EVALUATED_REVISION_REGRESSION = "revision-regression"

SEV_BLOCKED = "blocked"
SEV_FAIL = "fail"
SEV_REVIEW = "manual-review"

CODE_TEACHER_VOICE = "draft-teacher-voice-in-student-copy"
CODE_LONG_LINE = "draft-instruction-line-over-35-words"
CODE_UNGROUNDED_CLAIM = "draft-ungrounded-claim-pattern"
CODE_BELOW_MINIMUM = "draft-structure-below-request-declared-minimum"
CODE_ITEMS_REMOVED = "draft-revision-items-removed"
CODE_UNCHANGED = "draft-unchanged-since-prior-draft"
CODE_AI_NOT_PERMITTED = "draft-ai-generation-not-permitted"
CODE_ARTIFACT_UNSUPPORTED = "draft-artifact-type-not-supported"

#: The closed finding vocabulary, in canonical report order.
FINDING_CODES = (
    CODE_TEACHER_VOICE,
    CODE_LONG_LINE,
    CODE_UNGROUNDED_CLAIM,
    CODE_BELOW_MINIMUM,
    CODE_ITEMS_REMOVED,
    CODE_UNCHANGED,
    CODE_AI_NOT_PERMITTED,
    CODE_ARTIFACT_UNSUPPORTED,
)

FINDING_SEVERITY = {
    CODE_TEACHER_VOICE: SEV_FAIL,
    CODE_LONG_LINE: SEV_REVIEW,
    CODE_UNGROUNDED_CLAIM: SEV_REVIEW,
    CODE_BELOW_MINIMUM: SEV_FAIL,
    CODE_ITEMS_REMOVED: SEV_REVIEW,
    CODE_UNCHANGED: SEV_REVIEW,
    CODE_AI_NOT_PERMITTED: SEV_BLOCKED,
    CODE_ARTIFACT_UNSUPPORTED: SEV_BLOCKED,
}

#: Fixed one-line remediation per code. Constants: no draft text ever enters a
#: remediation, and none instructs deleting the flagged item to clear a finding.
FINDING_REMEDIATION = {
    CODE_TEACHER_VOICE: "Rewrite the flagged student-facing lines in student voice and keep every required item.",
    CODE_LONG_LINE: "Shorten or split the flagged line in place and keep its instructional content.",
    CODE_UNGROUNDED_CLAIM: (
        "Check the flagged claim against the verified lesson or a cited source, then revise it in place "
        "or mark it for teacher review."
    ),
    CODE_BELOW_MINIMUM: "Add the slides or questions the request declared and keep every existing item.",
    CODE_ITEMS_REMOVED: (
        "Restore the removed slides or questions, or tell the teacher why they were removed; "
        "do not remove content to clear another finding."
    ),
    CODE_UNCHANGED: "Revise the draft in place; unchanged resubmission does not resolve previous findings.",
    CODE_AI_NOT_PERMITTED: "Stop: the requirement does not permit AI-assisted generation. Ask the teacher or the owner.",
    CODE_ARTIFACT_UNSUPPORTED: (
        "Stop: this evaluator covers worksheet and slide-deck drafts only. Route other artifact types to their owner."
    ),
}

_CLAIM_PATTERNS = (
    re.compile(r"\d+(?:\.\d+)?\s*%|\bpercent\b", re.IGNORECASE),
    re.compile(r"\d+\s*(?:times|x)\s+more\b", re.IGNORECASE),
    re.compile(
        r"\b(?:studies|research|experts|scientists|surveys)\s+(?:show|shows|say|says|found|prove|proves)\b"
        r"|\bstatistics?\b|\baccording\s+to\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:always|never|everyone|nobody|guarantee|guaranteed)\b", re.IGNORECASE),
)
_QUESTION_TOKEN_RE = re.compile(r"question_\d+")
_BULLET_TOKEN_RE = re.compile(r"slide_\d+_bullet_\d+")
_ARTIFACT_TYPE_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")

LOCATION_SLIDES = "slides"
LOCATION_QUESTIONS = "worksheet_questions"
LOCATION_DRAFT = "draft"

_PREVIEW_LESSON_KEYS = (
    "request_id",
    "generated_at",
    "logical_source",
    "verification_state",
    "canonical_unit_page_id",
    "day_lesson_number",
)


class DraftEvaluationInputError(ValueError):
    """An input cannot be evaluated; the CLI reports it and writes no receipt."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(f"{reason_code}: {message}")
        self.reason_code = reason_code


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_bounded(data: object, label: str) -> bytes:
    if not isinstance(data, (bytes, bytearray)):
        raise DraftEvaluationInputError("input-unreadable", f"{label} must be bytes")
    if len(data) > MAX_INPUT_BYTES:
        raise DraftEvaluationInputError("input-unreadable", f"{label} exceeds the byte bound")
    return bytes(data)


# Parsed YAML may be much larger than its input bytes when aliases reuse a
# nested sequence. Student drafts do not require aliases; reject them before
# construction instead of relying on the raw-file size bound alone.
MAX_DRAFT_YAML_DEPTH = 64
MAX_DRAFT_YAML_NODES = 8192


class _BoundedDraftLoader(yaml.SafeLoader):
    def __init__(self, stream: str) -> None:
        super().__init__(stream)
        self._draft_depth = 0
        self._draft_nodes = 0

    def compose_node(self, parent: object, index: object) -> yaml.Node:
        if self.check_event(yaml.AliasEvent):
            raise yaml.YAMLError("YAML aliases are not supported for draft content")
        self._draft_depth += 1
        self._draft_nodes += 1
        try:
            if self._draft_depth > MAX_DRAFT_YAML_DEPTH or self._draft_nodes > MAX_DRAFT_YAML_NODES:
                raise yaml.YAMLError("draft YAML structure exceeds the allowed bound")
            return super().compose_node(parent, index)
        finally:
            self._draft_depth -= 1


def parse_draft(data: bytes, label: str = "draft") -> LessonContent:
    """Parse bounded draft YAML without expanding aliases or excessive nesting."""
    raw = _require_bounded(data, label)
    try:
        return content_from_dict(yaml.load(raw.decode("utf-8"), Loader=_BoundedDraftLoader))
    except UnicodeDecodeError as exc:
        raise DraftEvaluationInputError("input-unreadable", f"{label} is not UTF-8 text") from exc
    except yaml.YAMLError as exc:
        raise DraftEvaluationInputError("input-unreadable", f"{label} is not valid YAML") from exc
    except (ValueError, TypeError, AttributeError, RecursionError) as exc:
        raise DraftEvaluationInputError("input-unreadable", f"{label} is not valid lesson content: {str(exc)[:200]}") from exc


def _tokens(content: LessonContent) -> list[tuple[str, str]]:
    try:
        return list(content.placeholder_tokens().items())
    except ValueError as exc:
        raise DraftEvaluationInputError("input-unreadable", f"draft token collision: {str(exc)[:200]}") from exc


def _comparable(content: LessonContent) -> Any:
    """Compare authored student-facing content, not mutable provenance metadata.

    A2's unchanged-resubmission check must survive changes to the bound lesson,
    host-supplied context, or other non-instructional metadata. Preserve slide
    order/indices and all student-facing strings; fold only whitespace.
    """
    return {
        "title": normalize_text(content.title),
        "objectives": [normalize_text(value) for value in content.objectives],
        "slides": [
            {
                "index": slide["index"],
                "heading": normalize_text(slide.get("heading", "")),
                "bullets": [normalize_text(value) for value in slide.get("bullets", [])],
            }
            for slide in content.slides
        ],
        "worksheet_questions": [normalize_text(value) for value in content.worksheet_questions],
    }


def _finding(code: str, locations: list[str], *, routing_note: str | None = None) -> dict[str, Any]:
    finding: dict[str, Any] = {
        "code": code,
        "severity": FINDING_SEVERITY[code],
        "occurrences": len(locations),
        "locations": locations[:MAX_LOCATIONS_PER_FINDING],
        "locations_truncated": len(locations) > MAX_LOCATIONS_PER_FINDING,
        "remediation": FINDING_REMEDIATION[code],
    }
    if routing_note is not None:
        finding["routing_note"] = routing_note
    return finding


def _requirement_facts(data: bytes) -> tuple[str, bool]:
    """Return (artifact_type, ai_assisted_generation_permitted) from a validated MaterialRequirement."""
    from instructional_workflow_contracts.common import ValidationStatus, thaw_json
    from instructional_workflow_contracts.material_requirement import validate_material_requirement

    raw = _require_bounded(data, "material requirement")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise DraftEvaluationInputError("input-unreadable", "material requirement is not valid JSON") from exc
    result = validate_material_requirement(value)
    if result.status is not ValidationStatus.VALID or result.record is None:
        codes = ",".join(result.reason_codes) or "unspecified"
        raise DraftEvaluationInputError("requirement-invalid", f"material requirement is not valid ({codes})")
    payload = thaw_json(result.record.payload)
    return payload["artifact"]["artifact_type"], payload["ai_review"]["ai_assisted_generation_permitted"]


def _preview_projection(preview: Mapping[str, Any]) -> dict[str, Any]:
    """A text-free projection of the existing preview receipt."""
    worksheet = preview.get("worksheet") or {}
    lesson = preview.get("lesson") or {}
    return {
        "contract_version": preview["contract_version"],
        "status": preview["status"],
        "preview_kind": preview["preview_kind"],
        "rendered": preview["rendered"],
        "classroom_ready": preview["classroom_ready"],
        "checks": dict(preview["checks"] or {}),
        "planned_content_sha256": worksheet.get("planned_content_sha256"),
        "selection": dict(preview["selection"] or {}),
        "lesson": {key: lesson.get(key) for key in _PREVIEW_LESSON_KEYS},
    }


def evaluate_draft(
    draft: bytes,
    *,
    prior_draft: bytes | None = None,
    lesson_content_evidence: bytes | None = None,
    selection: LessonContentSelection | None = None,
    material_requirement: bytes | None = None,
    artifact_type: str | None = None,
    min_questions: int | None = None,
    min_slides: int | None = None,
) -> dict[str, Any]:
    """Evaluate one draft and return the content-safe receipt.

    Raises ``DraftEvaluationInputError`` for an input that cannot be evaluated.
    Findings are never suppressed, downgraded or defaulted by any input: an
    absent declaration is recorded as not applicable, never as permission.
    """
    # Fail cheaply on invalid scalar arguments, before doing YAML work.
    for name, value in (("min_questions", min_questions), ("min_slides", min_slides)):
        if value is not None and (type(value) is not int or value < 1):
            raise DraftEvaluationInputError("declared-minimum-invalid", f"{name} must be a positive integer")
    if artifact_type is not None and not _ARTIFACT_TYPE_RE.fullmatch(artifact_type):
        raise DraftEvaluationInputError("artifact-type-invalid", "artifact type must be a lowercase token")
    if (lesson_content_evidence is None) != (selection is None):
        raise DraftEvaluationInputError("identity-group-incomplete", "evidence and selection must be supplied together")

    draft_bytes = _require_bounded(draft, "draft")
    content = parse_draft(draft_bytes)
    tokens = _tokens(content)
    prior_content: LessonContent | None = None
    prior_bytes: bytes | None = None
    if prior_draft is not None:
        prior_bytes = _require_bounded(prior_draft, "prior draft")
        prior_content = parse_draft(prior_bytes, "prior draft")

    # ----- identity (existing adapter, existing preview) ---------------------------------
    identity_reason: str | None = None
    verified_lesson = None
    preview_projection: dict[str, Any] | None = None
    evidence_bytes: bytes | None = None
    if lesson_content_evidence is not None:
        evidence_bytes = _require_bounded(lesson_content_evidence, "lesson-content result")
        try:
            evidence = json.loads(evidence_bytes.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError) as exc:
            raise DraftEvaluationInputError("input-unreadable", "lesson-content result is not valid JSON") from exc
        preview = preview_lesson_worksheet(content, evidence, selection)
        if preview["status"] == PREVIEW:
            verified_lesson = verify_lesson_content_result(lesson_content_result_from_evidence(evidence), selection)
            preview_projection = _preview_projection(preview)
        else:
            identity_reason = str(preview["reason_code"])

    # ----- requirement facts --------------------------------------------------------------
    declared_types: list[str] = []
    ai_permitted: bool | None = None
    material_bytes: bytes | None = None
    if material_requirement is not None:
        material_bytes = _require_bounded(material_requirement, "material requirement")
        requirement_type, ai_permitted = _requirement_facts(material_bytes)
        declared_types.append(requirement_type)
    if artifact_type is not None:
        if declared_types and declared_types[0] != artifact_type:
            raise DraftEvaluationInputError(
                "artifact-type-conflict", "explicit artifact type conflicts with the governed requirement"
            )
        declared_types.append(artifact_type)
    declared_types = sorted(set(declared_types))

    # ----- closed findings ----------------------------------------------------------------
    findings: dict[str, dict[str, Any]] = {}

    voice_locations = [token for token, text in tokens if scan_teacher_voice([text])]
    if voice_locations:
        findings[CODE_TEACHER_VOICE] = _finding(CODE_TEACHER_VOICE, voice_locations)

    long_locations = [
        token
        for token, text in tokens
        if (_QUESTION_TOKEN_RE.fullmatch(token) or _BULLET_TOKEN_RE.fullmatch(token))
        and len(text.split()) > INSTRUCTION_LINE_WORD_LIMIT
    ]
    if long_locations:
        findings[CODE_LONG_LINE] = _finding(CODE_LONG_LINE, long_locations)

    grounding = ""
    if verified_lesson is not None:
        parts = (
            verified_lesson.daily_learning_target,
            verified_lesson.daily_focus,
            verified_lesson.key_vocabulary,
            verified_lesson.source_evidence,
        )
        grounding = normalize_text(" ".join(part for part in parts if part)).casefold()
    claim_locations: list[str] = []
    for token, text in tokens:
        for pattern in _CLAIM_PATTERNS:
            if any(normalize_text(match.group(0)).casefold() not in grounding for match in pattern.finditer(text)):
                claim_locations.append(token)
                break
    if claim_locations:
        findings[CODE_UNGROUNDED_CLAIM] = _finding(CODE_UNGROUNDED_CLAIM, claim_locations)

    question_count, slide_count = len(content.worksheet_questions), len(content.slides)
    # Empty/format-only placeholders do not satisfy a request-declared minimum.
    substantive_question_count = sum(
        bool("".join(ch for ch in question if unicodedata.category(ch) != "Cf").strip())
        for question in content.worksheet_questions
    )
    below = []
    if min_questions is not None and substantive_question_count < min_questions:
        below.append(LOCATION_QUESTIONS)
    if min_slides is not None and slide_count < min_slides:
        below.append(LOCATION_SLIDES)
    if below:
        findings[CODE_BELOW_MINIMUM] = _finding(CODE_BELOW_MINIMUM, below)

    if prior_content is not None:
        removed = []
        if len(prior_content.slides) > slide_count:
            removed.append(LOCATION_SLIDES)
        if len(prior_content.worksheet_questions) > question_count:
            removed.append(LOCATION_QUESTIONS)
        if removed:
            findings[CODE_ITEMS_REMOVED] = _finding(CODE_ITEMS_REMOVED, removed)
        if _comparable(prior_content) == _comparable(content):
            findings[CODE_UNCHANGED] = _finding(CODE_UNCHANGED, [LOCATION_DRAFT])

    if ai_permitted is False:
        findings[CODE_AI_NOT_PERMITTED] = _finding(CODE_AI_NOT_PERMITTED, [LOCATION_DRAFT])
    unsupported = [kind for kind in declared_types if kind not in SUPPORTED_ARTIFACT_TYPES]
    if unsupported:
        routed = any(kind in TEACHER_MODELING_ARTIFACT_TYPES for kind in unsupported)
        findings[CODE_ARTIFACT_UNSUPPORTED] = _finding(
            CODE_ARTIFACT_UNSUPPORTED,
            [LOCATION_DRAFT],
            routing_note=TEACHER_MODELING_ROUTING_NOTE if routed else None,
        )

    ordered = [findings[code] for code in FINDING_CODES if code in findings]
    severities = {item["severity"] for item in ordered}
    if identity_reason is not None or SEV_BLOCKED in severities:
        status = STATUS_BLOCKED
    elif SEV_FAIL in severities:
        status = STATUS_FAIL
    elif SEV_REVIEW in severities:
        status = STATUS_REVIEW
    else:
        status = STATUS_NO_FINDING

    declared_minimum = min_questions is not None or min_slides is not None
    not_evaluated = list(NOT_EVALUATED_FIXED)
    if not declared_minimum:
        not_evaluated.append(NOT_EVALUATED_STRUCTURE_MINIMUM)
    if prior_content is None:
        not_evaluated.append(NOT_EVALUATED_REVISION_REGRESSION)

    applicable = {
        CODE_TEACHER_VOICE: True,
        CODE_LONG_LINE: True,
        CODE_UNGROUNDED_CLAIM: True,
        CODE_BELOW_MINIMUM: declared_minimum,
        CODE_ITEMS_REMOVED: prior_content is not None,
        CODE_UNCHANGED: prior_content is not None,
        CODE_AI_NOT_PERMITTED: material_requirement is not None,
        CODE_ARTIFACT_UNSUPPORTED: bool(declared_types),
    }
    receipt: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "status": status,
        "lesson_identity": "verified" if verified_lesson is not None else "not-verified",
        "identity_reason_code": identity_reason,
        "requirements": "present" if material_requirement is not None else "absent",
        "declared": {
            "artifact_types": declared_types,
            "min_questions": min_questions,
            "min_slides": min_slides,
            "verification": "request-declared-unverified",
        },
        "applicability": {code: "applicable" if applicable[code] else "not-applicable" for code in FINDING_CODES},
        "claim_grounding": "verified-lesson-fields" if verified_lesson is not None else "empty",
        "findings": ordered,
        "draft_counts": {
            "objectives": len(content.objectives),
            "slides": slide_count,
            "questions": question_count,
        },
        "inputs": {
            "draft_sha256": _sha256_bytes(draft_bytes),
            "prior_draft_sha256": _sha256_bytes(prior_bytes) if prior_bytes is not None else None,
            "lesson_content_result_sha256": _sha256_bytes(evidence_bytes) if evidence_bytes is not None else None,
            "material_requirement_sha256": _sha256_bytes(material_bytes) if material_bytes is not None else None,
        },
        "preview": preview_projection,
        "audience_fidelity": AUDIENCE_FIDELITY,
        "semantic_review": SEMANTIC_REVIEW,
        "not_evaluated": not_evaluated,
        "classroom_ready": False,
        "preview_only": True,
        "side_effects": {
            "notion_writes_performed": False,
            "drive_writes_performed": False,
            "credentials_initialized": False,
            "native_artifact_created": False,
            "classroom_publication_performed": False,
        },
        "authority": dataclasses.asdict(AuthorityEvidence()),
    }
    try:
        receipt["receipt_fingerprint"] = sha256_hex(receipt)
    except ValueError as exc:  # contract validation of the envelope (string or size bounds)
        raise DraftEvaluationInputError("receipt-envelope-invalid", str(exc)[:200]) from exc
    return receipt


def status_line(receipt: Mapping[str, Any]) -> str:
    """One line stating the status together with the evaluation limits."""
    return (
        f"Draft evaluation: {receipt['status']} | semantic_review: {receipt['semantic_review']} | "
        f"not_evaluated: {', '.join(receipt['not_evaluated'])} | deterministic checks only; preview only"
    )


def exit_code(receipt: Mapping[str, Any]) -> int:
    """0 for no-deterministic-finding and review; 1 for fail and blocked."""
    return 0 if receipt["status"] in EXIT_ZERO_STATUSES else 1


__all__ = [
    "CONTRACT_VERSION",
    "DraftEvaluationInputError",
    "FINDING_CODES",
    "FINDING_REMEDIATION",
    "FINDING_SEVERITY",
    "MAX_INPUT_BYTES",
    "evaluate_draft",
    "exit_code",
    "parse_draft",
    "status_line",
]
