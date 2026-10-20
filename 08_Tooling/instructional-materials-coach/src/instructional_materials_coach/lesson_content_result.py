"""Consume one governed #3580 lesson-content result into existing lesson content (#3582).

This module is a narrow, pure adapter. It performs no Notion, Drive, or other
provider call, initializes no credentials, and creates no new curriculum
schema, reader, or registry. Its only input is the public lesson-content
result already produced and sanitized by the governed #2283/#3580 read path
(``project_lesson_content_result``), optionally still wrapped in that runner's
evidence envelope. Its only output is the existing ``LessonContent`` with
additive ``context_lesson_*`` tokens composed through ``with_context_tokens``.

Authored YAML slides and worksheet questions are never replaced or invented:
Notion supplies neither, so composition requires both to be authored. The one
objective rule is deterministic and fail-closed: authored objectives must
contain the verified Daily Learning Target (whitespace-folded exact match),
and must not carry another lesson's target or focus. An explicitly empty
authored objective list is filled from the verified target/focus only when the
authored content carries an independent lesson-identity binding
(``lesson_identity.day_lesson_number``) that exactly matches the selected
lesson; the title is not canonical identity and is never the matching rule.
An absent Key Vocabulary stays absent; nothing is defaulted or inferred.

Every lesson identity the caller depends on (request, canonical unit, lesson
number, run provenance) is caller-bound evidence and must match exactly.
"""
from __future__ import annotations

import dataclasses
import unicodedata
from typing import Any, Mapping

from .artifact_content_qa import normalize_text, scan_unresolved_tokens
from .content_spec import LessonContent, _validate_slide_indexes

#: Published #3580 lesson-content result contract (scripts/agent_os_notion_read_request).
RESULT_KIND = "agent-os-notion-lesson-content-result"
SCHEMA_VERSION = "1.0"
REQUEST_CLASS = "lesson-content"
REPOSITORY = "Blummer92/agent-os"
VERIFIED_STATE = "verified-current"
#: Slice 1 (#3580) admits exactly one lesson-content source.
ADMITTED_LOGICAL_SOURCES = frozenset({"daily-generation-packet"})
#: Catalog display name pinned per admitted logical source. The producer
#: publishes the catalog's display name verbatim; any other value is not the
#: admitted source.
ADMITTED_SOURCE_DISPLAY_NAMES = {"daily-generation-packet": "Daily Generation Packet Dashboard"}
#: The producer publishes at most MAX_RESULTS (24) lessons per read.
MAX_LESSONS = 24
#: Runner evidence-envelope disposition for a completed lesson-content read.
DISPATCH_COMPLETED = "completed"
DISPATCH_REASON = "bounded-lesson-content-projected"

RESULT_KEYS = frozenset(
    {
        "schema_version",
        "result_kind",
        "repository",
        "issue_number",
        "request_id",
        "request_class",
        "source",
        "lessons",
        "authority",
        "generated_at",
    }
)
SOURCE_KEYS = frozenset({"logical_source", "display_name", "verification_state", "access"})
#: The seven governed lesson fields (the public Notion contract).
LESSON_KEYS = frozenset(
    {
        "daily_learning_target",
        "daily_focus",
        "key_vocabulary",
        "canonical_unit",
        "source_evidence",
        "day_lesson_number",
        "record_url",
    }
)
AUTHORITY_KEYS = frozenset(
    {
        "execution_authorized",
        "external_write_authorized",
        "notion_write_authorized",
        "drive_write_authorized",
        "classroom_artifact_write_authorized",
        "production_authorized",
        "publication_authorized",
        "write_allowed",
    }
)
ENVELOPE_KEYS = frozenset(
    {
        "schema_version",
        "admission",
        "dispatch_status",
        "dispatch_reason",
        "result",
        "notion_writes_performed",
        "drive_writes_performed",
        "classroom_artifact_writes_performed",
        "gce_invoked",
        "generated_at",
    }
)
_ENVELOPE_WRITE_FLAGS = (
    "notion_writes_performed",
    "drive_writes_performed",
    "classroom_artifact_writes_performed",
    "gce_invoked",
)
_ADMISSION_FALSE_FLAGS = ("write_allowed", "production_authorized", "notion_write_reachable", "gce_required")
#: Exact admission shape published by the #2283 runner
#: (``NotionReadAdmission.to_dict``). Any extra key is envelope drift.
ADMISSION_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "reason_codes",
        "repository",
        "issue_number",
        "request_id",
        "request_class",
        "canonical_unit_key",
        "fixed_page_id",
        "expected_title",
        "required_logical_sources",
        "allowed_read_actions",
        "secret_dispatch_authorized",
        "write_allowed",
        "production_authorized",
        "notion_write_reachable",
        "gce_required",
    }
)
#: Lesson text fields the producer emits as None when absent. A
#: whitespace-only value is producer-absent, not malformed; invisible
#: (zero-width) text is still malformed, never absent.
_OPTIONAL_LESSON_TEXT_FIELDS = frozenset({"daily_focus", "key_vocabulary"})
#: Governed text fields scanned for unresolved {{placeholder}} markers.
_PLACEHOLDER_SCANNED_FIELDS = (
    "daily_learning_target",
    "daily_focus",
    "key_vocabulary",
    "source_evidence",
    "day_lesson_number",
)
#: Bound on evidence nesting for the credential-key walk. Genuine runner
#: evidence nests a handful of levels; deeper nesting is refused rather than
#: recursed into.
_CREDENTIAL_WALK_MAX_DEPTH = 32

#: Same structural rule as the producer's ``reject_credential_keys``: a
#: credential-class key may only ever carry a boolean state flag.
CREDENTIAL_KEY_FRAGMENTS = (
    "authorization",
    "api_key",
    "apikey",
    "bearer",
    "cookie",
    "credential",
    "notion_token",
    "password",
    "secret",
    "session",
    "token",
)

_NOTION_RECORD_URL_PREFIXES = ("https://app.notion.com/", "https://www.notion.so/")

#: Additive context tokens this adapter may contribute. Authored tokens
#: (title, objective_N, slide_*, question_N) are never produced here.
TOKEN_REQUEST_ID = "context_lesson_request_id"
TOKEN_GENERATED_AT = "context_lesson_generated_at"
TOKEN_LOGICAL_SOURCE = "context_lesson_logical_source"
TOKEN_VERIFICATION_STATE = "context_lesson_source_verification_state"
TOKEN_UNIT_PAGE_ID = "context_lesson_canonical_unit_page_id"
TOKEN_DAY = "context_lesson_day_lesson_number"
TOKEN_TARGET = "context_lesson_learning_target"
TOKEN_FOCUS = "context_lesson_daily_focus"
TOKEN_VOCABULARY = "context_lesson_key_vocabulary"
TOKEN_SOURCE_EVIDENCE = "context_lesson_source_evidence"
TOKEN_RECORD_URL = "context_lesson_record_url"
TOKEN_OBJECTIVE_SOURCE = "context_lesson_objective_source"

OBJECTIVE_SOURCE_AUTHORED = "authored"
OBJECTIVE_SOURCE_GOVERNED = "governed-lesson-content"


class LessonContentResultError(ValueError):
    """Fail-closed rejection with a closed-vocabulary reason code."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(f"{reason_code}: {message}")
        self.reason_code = reason_code


@dataclasses.dataclass(frozen=True)
class LessonContentSelection:
    """Caller-bound identity of the one lesson to consume.

    Every field is compared exactly against the result. ``generated_at`` is
    the producer's run provenance (``<run_id>:<attempt>``), so a result from
    a different or older read cannot silently stand in for the verified one.
    """

    request_id: str
    canonical_unit_page_id: str
    day_lesson_number: str
    generated_at: str


@dataclasses.dataclass(frozen=True)
class VerifiedLesson:
    """One lesson record proven against the result contract and selection."""

    request_id: str
    generated_at: str
    logical_source: str
    verification_state: str
    canonical_unit_page_id: str
    day_lesson_number: str
    daily_learning_target: str
    daily_focus: str | None
    key_vocabulary: str | None
    source_evidence: str
    record_url: str


def lesson_content_result_from_evidence(value: object) -> Mapping[str, Any]:
    """Return the bare lesson-content result from a result or runner envelope.

    The #2283 runner publishes ``{"admission": ..., "dispatch_status": ...,
    "result": {...}}``. A completed, admitted, write-free envelope is unwrapped;
    a blocked, failed, or write-bearing envelope is refused. A bare result is
    returned unchanged for ``verify_lesson_content_result`` to validate.
    """
    if not isinstance(value, Mapping):
        raise LessonContentResultError("result-malformed", "lesson-content evidence must be a mapping")
    _reject_credential_keys(value, "evidence")
    if "result_kind" in value:
        return value
    if "dispatch_status" not in value:
        raise LessonContentResultError("result-malformed", "evidence is neither a result nor a runner envelope")
    _exact_keys(value, ENVELOPE_KEYS, "evidence envelope")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise LessonContentResultError("result-class-mismatch", "evidence envelope is not schema 1.0")
    if value.get("dispatch_status") != DISPATCH_COMPLETED or value.get("dispatch_reason") != DISPATCH_REASON:
        raise LessonContentResultError("dispatch-not-completed", "lesson-content read did not complete")
    for flag in _ENVELOPE_WRITE_FLAGS:
        if value.get(flag) is not False:
            raise LessonContentResultError("authority-not-fail-closed", f"evidence {flag} must be false")
    admission = value.get("admission")
    if not isinstance(admission, Mapping):
        raise LessonContentResultError("result-malformed", "evidence admission must be a mapping")
    _exact_keys(admission, ADMISSION_KEYS, "evidence admission")
    if admission.get("schema_version") != SCHEMA_VERSION:
        raise LessonContentResultError("result-class-mismatch", "evidence admission is not schema 1.0")
    if admission.get("status") != "admitted" or admission.get("request_class") != REQUEST_CLASS:
        raise LessonContentResultError("result-class-mismatch", "evidence admission is not an admitted lesson-content read")
    for flag in _ADMISSION_FALSE_FLAGS:
        if admission.get(flag) is not False:
            raise LessonContentResultError("authority-not-fail-closed", f"admission {flag} must be false")
    result = value.get("result")
    if not isinstance(result, Mapping):
        raise LessonContentResultError("result-malformed", "evidence result must be a mapping")
    for key in ("request_id", "repository", "issue_number"):
        if admission.get(key) != result.get(key):
            raise LessonContentResultError("provenance-mismatch", f"admission and result {key} differ")
    if value.get("generated_at") != result.get("generated_at"):
        raise LessonContentResultError("provenance-mismatch", "envelope and result generated_at differ")
    return result


def verify_lesson_content_result(result: object, selection: LessonContentSelection) -> VerifiedLesson:
    """Validate one exact lesson-content result and select the bound lesson.

    Fails closed on any contract drift: wrong result class or schema, unknown
    or unverified source, widened authority, extra or credential-bearing keys,
    foreign-unit or malformed lessons, mismatched request/run provenance,
    missing or ambiguous lesson identity, or missing required lesson fields.
    """
    _require_selection(selection)
    if not isinstance(result, Mapping):
        raise LessonContentResultError("result-malformed", "lesson-content result must be a mapping")
    _reject_credential_keys(result, "result")
    _exact_keys(result, RESULT_KEYS, "lesson-content result")
    if (
        result.get("result_kind") != RESULT_KIND
        or result.get("request_class") != REQUEST_CLASS
        or result.get("schema_version") != SCHEMA_VERSION
    ):
        raise LessonContentResultError("result-class-mismatch", "result is not a lesson-content result v1.0")
    if result.get("repository") != REPOSITORY:
        raise LessonContentResultError("repository-mismatch", "result repository is not the canonical repository")
    if type(result.get("issue_number")) is not int or result["issue_number"] <= 0:
        raise LessonContentResultError("result-malformed", "result issue_number must be a positive integer")
    if result.get("request_id") != selection.request_id:
        raise LessonContentResultError("request-mismatch", "result request_id does not match the bound request")
    generated_at = result.get("generated_at")
    if not _text(generated_at):
        raise LessonContentResultError("result-malformed", "result generated_at must be non-empty text")
    if generated_at != selection.generated_at:
        raise LessonContentResultError("provenance-mismatch", "result run provenance does not match the bound run")

    source = result.get("source")
    if not isinstance(source, Mapping):
        raise LessonContentResultError("result-malformed", "result source must be a mapping")
    _exact_keys(source, SOURCE_KEYS, "result source")
    logical_source = source.get("logical_source")
    # Membership in a frozenset hashes the candidate: an unhashable
    # logical_source would escape as TypeError, so the type gate comes first.
    if not isinstance(logical_source, str) or logical_source not in ADMITTED_LOGICAL_SOURCES:
        raise LessonContentResultError("source-unknown", "result source is not an admitted lesson-content source")
    if source.get("display_name") != ADMITTED_SOURCE_DISPLAY_NAMES[logical_source]:
        raise LessonContentResultError("source-unknown", "result source display name is not the admitted source name")
    if source.get("verification_state") != VERIFIED_STATE:
        raise LessonContentResultError("source-unverified", "result source is not verified-current")
    if source.get("access") != "read-only":
        raise LessonContentResultError("source-not-read-only", "result source access must be read-only")

    authority = result.get("authority")
    if not isinstance(authority, Mapping):
        raise LessonContentResultError("result-malformed", "result authority must be a mapping")
    _exact_keys(authority, AUTHORITY_KEYS, "result authority")
    if any(value is not False for value in authority.values()):
        raise LessonContentResultError("authority-not-fail-closed", "result authority must remain false")

    lessons = result.get("lessons")
    if not isinstance(lessons, list) or not lessons:
        raise LessonContentResultError("result-malformed", "result lessons must be a non-empty list")
    if len(lessons) > MAX_LESSONS:
        raise LessonContentResultError("result-malformed", "result lessons exceed the read bound")
    expected_unit = selection.canonical_unit_page_id
    for lesson in lessons:
        _validate_lesson_shape(lesson, expected_unit)

    _reject_duplicates(lessons, "record_url")
    _reject_variant_duplicate_identities(lessons)
    matches = [lesson for lesson in lessons if lesson["day_lesson_number"] == selection.day_lesson_number]
    if not matches:
        raise LessonContentResultError("lesson-not-found", "bound lesson is not present in the result")
    if len(matches) > 1:
        raise LessonContentResultError("lesson-identity-ambiguous", "bound lesson number matches more than one record")
    selected = matches[0]
    for field in ("daily_learning_target", "day_lesson_number", "source_evidence", "record_url"):
        if not _text(selected[field]):
            raise LessonContentResultError("lesson-field-missing", f"bound lesson has no {field}")
    if not str(selected["record_url"]).startswith(_NOTION_RECORD_URL_PREFIXES):
        raise LessonContentResultError("lesson-malformed", "bound lesson record_url is not a Notion record URL")

    return VerifiedLesson(
        request_id=selection.request_id,
        generated_at=selection.generated_at,
        logical_source=str(logical_source),
        verification_state=VERIFIED_STATE,
        canonical_unit_page_id=expected_unit,
        day_lesson_number=selected["day_lesson_number"],
        daily_learning_target=selected["daily_learning_target"],
        daily_focus=_absent_if_blank(selected["daily_focus"]),
        key_vocabulary=_absent_if_blank(selected["key_vocabulary"]),
        source_evidence=selected["source_evidence"],
        record_url=selected["record_url"],
    )


def compose_lesson_content_result(
    content: LessonContent,
    result: object,
    selection: LessonContentSelection,
) -> LessonContent:
    """Compose one verified lesson onto authored lesson content without replacing it.

    Returns a new ``LessonContent`` whose title, slides, and worksheet
    questions are the authored values unchanged. Objectives stay authored
    unless the authored list is explicitly empty, in which case they are the
    verified target (and focus, when present) only. Verified identity,
    objectives, and provenance are added as namespaced context tokens.
    """
    lesson = verify_lesson_content_result(lesson_content_result_from_evidence(result), selection)
    other_lessons = [item for item in result_lessons(result) if item["day_lesson_number"] != lesson.day_lesson_number]
    _require_authored_materials(content)
    objectives, objective_source = _reconciled_objectives(content, lesson, other_lessons)

    tokens = {
        TOKEN_REQUEST_ID: lesson.request_id,
        TOKEN_GENERATED_AT: lesson.generated_at,
        TOKEN_LOGICAL_SOURCE: lesson.logical_source,
        TOKEN_VERIFICATION_STATE: lesson.verification_state,
        TOKEN_UNIT_PAGE_ID: lesson.canonical_unit_page_id,
        TOKEN_DAY: lesson.day_lesson_number,
        TOKEN_TARGET: lesson.daily_learning_target,
        TOKEN_SOURCE_EVIDENCE: lesson.source_evidence,
        TOKEN_RECORD_URL: lesson.record_url,
        TOKEN_OBJECTIVE_SOURCE: objective_source,
        # Same fixed-false authority evidence as compose_generation_context.
        "context_production_authorized": "false",
        "context_publication_authorized": "false",
        "context_external_write_authorized": "false",
    }
    if lesson.daily_focus is not None:
        tokens[TOKEN_FOCUS] = lesson.daily_focus
    if lesson.key_vocabulary is not None:
        tokens[TOKEN_VOCABULARY] = lesson.key_vocabulary

    composed = dataclasses.replace(content, objectives=objectives)
    try:
        composed = composed.with_context_tokens(tokens)
        # Collision with an authored token is refused by LessonContent itself.
        composed.placeholder_tokens()
    except ValueError as exc:
        raise LessonContentResultError("context-token-conflict", str(exc)) from None
    return composed


def result_lessons(evidence: object) -> list[Mapping[str, Any]]:
    """Return the lessons of an already-verified result or runner envelope."""
    result = lesson_content_result_from_evidence(evidence)
    lessons = result.get("lessons")
    return list(lessons) if isinstance(lessons, list) else []


def _require_selection(selection: object) -> None:
    if not isinstance(selection, LessonContentSelection):
        raise LessonContentResultError("selection-malformed", "an explicit LessonContentSelection is required")
    for field in dataclasses.fields(selection):
        value = getattr(selection, field.name)
        if not _text(value) or value != value.strip():
            raise LessonContentResultError("selection-malformed", f"selection {field.name} must be trimmed text")
    if _dashed_uuid(selection.canonical_unit_page_id) != selection.canonical_unit_page_id:
        raise LessonContentResultError("selection-malformed", "selection canonical unit must be a dashed lowercase Notion id")


def _validate_lesson_shape(lesson: object, expected_unit: str) -> None:
    if not isinstance(lesson, Mapping):
        raise LessonContentResultError("lesson-malformed", "lesson record must be a mapping")
    _exact_keys(lesson, LESSON_KEYS, "lesson record")
    unit = lesson.get("canonical_unit")
    if not isinstance(unit, Mapping) or set(unit.keys()) != {"page_id"}:
        raise LessonContentResultError("lesson-malformed", "lesson canonical_unit must carry exactly page_id")
    page_id = unit.get("page_id")
    if not isinstance(page_id, str) or _dashed_uuid(page_id) != page_id:
        raise LessonContentResultError("lesson-malformed", "lesson canonical unit relation is malformed")
    if page_id != expected_unit:
        raise LessonContentResultError("unit-mismatch", "lesson belongs to a different canonical unit")
    for field in LESSON_KEYS - {"canonical_unit"}:
        value = lesson.get(field)
        # The producer emits absent fields as None, never "" or whitespace.
        # A whitespace-only optional field is producer-absent, not malformed;
        # invisible (zero-width) text is malformed, never absent.
        if value is None:
            continue
        if (
            field in _OPTIONAL_LESSON_TEXT_FIELDS
            and isinstance(value, str)
            and not value.strip()
        ):
            continue
        if not _text(value):
            raise LessonContentResultError("lesson-malformed", f"lesson {field} must be non-empty text or absent")
        if field in _PLACEHOLDER_SCANNED_FIELDS and scan_unresolved_tokens(value):
            raise LessonContentResultError(
                "lesson-malformed", f"lesson {field} carries unresolved placeholder text"
            )
    if lesson.get("day_lesson_number") is None or lesson.get("record_url") is None:
        raise LessonContentResultError("lesson-field-missing", "lesson identity fields are absent")


def _reject_duplicates(lessons: list[Mapping[str, Any]], field: str) -> None:
    seen: set[str] = set()
    for lesson in lessons:
        value = lesson[field]
        if value in seen:
            raise LessonContentResultError("lesson-identity-ambiguous", f"duplicate lesson {field}")
        seen.add(value)


def _reject_variant_duplicate_identities(lessons: list[Mapping[str, Any]]) -> None:
    """Fail closed when two lessons share a lesson identity modulo case/whitespace.

    ``day_lesson_number`` values that differ only by case or whitespace
    ("Day 1" vs "day 1" vs "Day  1") are the same lesson identity claimed
    twice. Exact-match selection must never silently pick one of them.
    """
    seen: dict[str, str] = {}
    for lesson in lessons:
        raw = lesson["day_lesson_number"]
        folded = normalize_text(raw).casefold()
        if folded in seen:
            raise LessonContentResultError(
                "lesson-identity-ambiguous",
                f"lessons carry case/whitespace-variant duplicate identities: {seen[folded]!r} and {raw!r}",
            )
        seen[folded] = raw


def _require_authored_materials(content: LessonContent) -> None:
    if not isinstance(content, LessonContent):
        raise LessonContentResultError("authored-content-missing", "authored LessonContent is required")
    if not _text(content.title):
        raise LessonContentResultError("authored-content-missing", "authored title must be visible text")
    # Scalar authored fields must not reach iteration: a bare string for
    # objectives or worksheet_questions would be walked character by
    # character and silently accepted.
    if (
        not isinstance(content.objectives, list)
        or any(not isinstance(item, str) for item in content.objectives)
    ):
        raise LessonContentResultError("authored-content-missing", "authored objectives must be a list of text")
    if not isinstance(content.worksheet_questions, list) or not content.worksheet_questions or any(
        not _text(item) for item in content.worksheet_questions
    ):
        raise LessonContentResultError(
            "authored-content-missing", "authored worksheet questions are required; Notion supplies none"
        )
    _require_authored_slides(content.slides)


def _require_authored_slides(slides: object) -> None:
    """Validate authored slide structures so composition never raises mid-build.

    ``placeholder_tokens`` indexes ``slide["index"]`` and walks ``bullets``;
    a scalar, a non-mapping, a missing index, or non-text bullets would escape
    as TypeError/KeyError instead of a closed reason code.
    """
    if isinstance(slides, (str, bytes)) or not isinstance(slides, list) or not slides:
        raise LessonContentResultError("authored-content-missing", "authored slides are required; Notion supplies none")
    try:
        _validate_slide_indexes(slides)
    except ValueError as exc:
        raise LessonContentResultError("authored-content-missing", str(exc)) from None
    for position, slide in enumerate(slides):
        where = f"authored slide #{position + 1}"
        if not isinstance(slide, Mapping):
            raise LessonContentResultError("authored-content-missing", f"{where} must be a mapping")
        index = slide.get("index")
        if isinstance(index, bool) or not isinstance(index, (int, str)) or (
            isinstance(index, str) and not _text(index)
        ):
            raise LessonContentResultError("authored-content-missing", f"{where} must carry a usable 'index'")
        heading = slide.get("heading")
        if "heading" in slide and not isinstance(heading, str):
            raise LessonContentResultError("authored-content-missing", f"{where} 'heading' must be text")
        bullets = slide.get("bullets", [])
        if isinstance(bullets, (str, bytes)) or not isinstance(bullets, list) or any(
            not isinstance(bullet, str) for bullet in bullets
        ):
            raise LessonContentResultError("authored-content-missing", f"{where} 'bullets' must be a list of text")


def _reconciled_objectives(
    content: LessonContent,
    lesson: VerifiedLesson,
    other_lessons: list[Mapping[str, Any]],
) -> tuple[list[str], str]:
    governed = [lesson.daily_learning_target]
    if lesson.daily_focus is not None:
        governed.append(lesson.daily_focus)
    if not content.objectives:
        # Empty authored objectives carry no independent proof that the
        # authored material belongs to the selected lesson, so the governed
        # target/focus are adopted only under an independent authored
        # lesson-identity binding that exactly matches the selected lesson.
        # The title is not canonical identity and is never the matching rule.
        identity = content.lesson_identity
        if (
            not isinstance(identity, Mapping)
            or identity.get("day_lesson_number") != lesson.day_lesson_number
        ):
            raise LessonContentResultError(
                "authored-identity-missing",
                "empty authored objectives require an independent authored "
                "lesson-identity binding matching the selected lesson",
            )
        return governed, OBJECTIVE_SOURCE_GOVERNED

    authored = {normalize_text(item) for item in content.objectives}
    if normalize_text(lesson.daily_learning_target) not in authored:
        raise LessonContentResultError(
            "objective-conflict",
            "authored objectives do not include the verified Daily Learning Target",
        )
    own = {normalize_text(item) for item in governed}
    for other in other_lessons:
        for field in ("daily_learning_target", "daily_focus"):
            value = other.get(field)
            if isinstance(value, str) and normalize_text(value) not in own and normalize_text(value) in authored:
                raise LessonContentResultError(
                    "objective-conflict",
                    "authored objectives include another lesson's verified objective",
                )
    return list(content.objectives), OBJECTIVE_SOURCE_AUTHORED


def _reject_credential_keys(value: object, path: str) -> None:
    """Refuse credential-class keys without recursing.

    Evidence is caller-supplied; a deeply nested mapping must fail closed as
    malformed rather than escaping as RecursionError. The walk is iterative
    with an explicit depth bound.
    """
    stack: list[tuple[object, str, int]] = [(value, path, 0)]
    while stack:
        current, current_path, depth = stack.pop()
        if depth > _CREDENTIAL_WALK_MAX_DEPTH:
            raise LessonContentResultError(
                "result-malformed", f"evidence nesting exceeds the bound at {current_path}"
            )
        if isinstance(current, Mapping):
            for key, item in current.items():
                lowered = str(key).lower()
                if any(fragment in lowered for fragment in CREDENTIAL_KEY_FRAGMENTS):
                    if type(item) is not bool:
                        raise LessonContentResultError(
                            "credential-key-present", f"credential-class key at {current_path}.{key}"
                        )
                    continue
                stack.append((item, f"{current_path}.{key}", depth + 1))
        elif isinstance(current, (list, tuple)):
            for index, item in enumerate(current):
                stack.append((item, f"{current_path}[{index}]", depth + 1))


def _exact_keys(value: Mapping[str, Any], expected: frozenset[str], label: str) -> None:
    keys = set(value.keys())
    if keys - expected:
        raise LessonContentResultError("result-unexpected-key", f"{label} carries unexpected keys")
    if expected - keys:
        raise LessonContentResultError("lesson-field-missing" if label == "lesson record" else "result-malformed",
                                       f"{label} is missing required keys")


def _text(value: object) -> bool:
    """True for text carrying at least one visible character.

    ``str.strip`` does not remove zero-width/format characters (Unicode
    category Cf), so invisible text such as ``"\\u200b\\u200c"`` must not
    satisfy a required-text rule.
    """
    if not isinstance(value, str):
        return False
    return bool("".join(char for char in value if unicodedata.category(char) != "Cf").strip())


def _absent_if_blank(value: object) -> str | None:
    """Normalize a whitespace-only optional lesson field to absent (None).

    The producer emits absent fields as None; a whitespace-only value is the
    same absence and must not reject an otherwise valid record. Invisible
    (zero-width) text is not blank: it is malformed, never absent. Shape
    validation already guarantees only str-or-None reaches here.
    """
    if isinstance(value, str):
        return None if not value.strip() else value
    return None


def _dashed_uuid(value: str) -> str | None:
    compact = value.replace("-", "").lower()
    if len(compact) != 32 or any(char not in "0123456789abcdef" for char in compact):
        return None
    return f"{compact[0:8]}-{compact[8:12]}-{compact[12:16]}-{compact[16:20]}-{compact[20:32]}"


__all__ = [
    "LessonContentResultError",
    "LessonContentSelection",
    "VerifiedLesson",
    "compose_lesson_content_result",
    "lesson_content_result_from_evidence",
    "result_lessons",
    "verify_lesson_content_result",
]

