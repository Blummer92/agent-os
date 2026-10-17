"""Student-voice screening for student-facing worksheet copy (#3213).

Teacher-guide language leaked onto the Motion Spot student pages: rigor-ramp
stage labels written for the teacher, cognitive-load jargon, teacher-phrased
gate and recovery rules, and the teacher's modeling script. This module
screens student-facing copy for that modeling voice. The scan is
whitespace-normalized and case-insensitive substring matching, mirroring the
internal-review-language screen in ``student_material_pdf.py``.

Deliberate student-facing uses are declared explicitly (the PDF preview path
exposes ``explicit_student_copy_teacher_voice_phrases``); unknown
declarations fail closed so a typo cannot silently read as intent.

``"sentence frames"`` is intentionally NOT screened: it is a legitimate
classroom tool term that can appear in genuine student copy, and the leaked
stage-label paragraphs that quoted it always carry a screened marker
(``"heavy modeling"``, ``"early stage"``) that this scan catches.

This module performs no I/O and grants no authority.
"""
from __future__ import annotations

from typing import Any, Container, Iterable, Mapping

#: Teacher-guide modeling voice that must not appear in student-facing
#: worksheet copy by default. Each entry is ``(label, phrase)``; labels are
#: reported in blocked receipts and ``_KNOWN`` phrases are the bounded
#: explicit-declaration vocabulary. Matching is case-insensitive substring
#: matching on whitespace-normalized copy.
TEACHER_VOICE_PHRASES: tuple[tuple[str, str], ...] = (
    # Modeling/stage language quoted from the leaked Motion Spot student
    # pages (#3213); matches the validated worksheet-engine teacher-voice
    # gate vocabulary.
    ("heavy modeling", "heavy modeling"),
    ("rigor-ramp stage label", "early stage"),
    ("rigor-ramp stage label", "middle stage"),
    ("rigor-ramp stage label", "late stage"),
    ("teacher modeling script", "teacher model"),
    ("cognitive-load jargon", "one revision focus"),
    ("cognitive-load jargon", "keeps revision manageable"),
    ("cognitive-load jargon", "cognitive load"),
    # Teacher-phrased rules quoted from the student pages (#3213): these
    # belong in the teacher guide and slide deck, not on the student sheet.
    ("teacher-phrased rule", "gate rule"),
    ("teacher-phrased rule", "recovery rule"),
)

_KNOWN_TEACHER_VOICE_PHRASES: frozenset[str] = frozenset(
    phrase for _, phrase in TEACHER_VOICE_PHRASES
)


def normalize_phrase(phrase: str) -> str:
    """Whitespace-normalize and casefold one phrase for scanning."""
    return " ".join(phrase.split()).casefold()


def known_teacher_voice_phrases() -> frozenset[str]:
    """The bounded vocabulary for explicit student-copy declarations."""
    return _KNOWN_TEACHER_VOICE_PHRASES


def scan_teacher_voice(
    texts: Iterable[str],
    *,
    allowed: Container[str] = (),
) -> tuple[str, ...]:
    """Return labels for teacher-voice phrases found in the given texts.

    Scans each text with whitespace-normalized case-insensitive substring
    matching. A phrase in ``allowed`` (normalized) is treated as
    deliberately student-facing and is not reported. Returns the matching
    labels in phrase-list order, deduplicated.
    """
    normalized_texts = [normalize_phrase(text) for text in texts]
    allowed_normalized = {normalize_phrase(phrase) for phrase in allowed}
    found: list[str] = []
    for label, phrase in TEACHER_VOICE_PHRASES:
        if phrase in allowed_normalized:
            continue
        if any(phrase in text for text in normalized_texts):
            if label not in found:
                found.append(label)
    return tuple(found)


class StudentVoiceError(ValueError):
    """Fail-closed error for teacher-guide modeling voice in student-facing copy."""


def docs_replace_student_texts(
    docs_requests: Iterable[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Extract the student-facing replacement text from Docs ``replaceAllText`` requests.

    Only ``replaceText`` values are student-facing; ``containsText`` is the
    ``{{token}}`` placeholder being replaced. Non-``replaceAllText`` requests
    (for example style updates) carry no student copy and are skipped.
    """
    texts: list[str] = []
    for request in docs_requests:
        replace = request.get("replaceAllText") if isinstance(request, Mapping) else None
        if not isinstance(replace, Mapping):
            continue
        text = replace.get("replaceText", "")
        texts.append(text if isinstance(text, str) else "")
    return tuple(texts)


def require_student_voice(
    docs_requests: Iterable[Mapping[str, Any]],
    *,
    allowed: Iterable[str] = (),
) -> None:
    """Fail closed when planned worksheet copy carries teacher-guide modeling voice.

    Production Docs-build seam: the replacement text of the governed
    ``replaceAllText`` requests is exactly the student-facing copy written
    into the worksheet Doc, so this runs in the build composition before any
    Drive write. Reuses :func:`scan_teacher_voice` -- the single governed
    vocabulary. A phrase in ``allowed`` is deliberately student-facing, but
    only when it names a known vocabulary phrase: unknown declarations fail
    closed so a typo cannot silently read as intent.
    """
    allowed_tuple = tuple(allowed)
    if len(allowed_tuple) > 16:
        raise StudentVoiceError(
            "explicit student-copy teacher-voice phrases exceed the bounded build limit"
        )
    seen: set[str] = set()
    known = known_teacher_voice_phrases()
    for phrase in allowed_tuple:
        if not isinstance(phrase, str) or not phrase.strip():
            raise StudentVoiceError(
                "explicit student-copy teacher-voice phrases must be non-empty text"
            )
        normalized = normalize_phrase(phrase)
        if normalized not in known:
            raise StudentVoiceError(
                f"unknown student-copy teacher-voice phrase: {phrase}"
            )
        if normalized in seen:
            raise StudentVoiceError(
                "explicit student-copy teacher-voice phrases must be unique"
            )
        seen.add(normalized)
    leaked = scan_teacher_voice(docs_replace_student_texts(docs_requests), allowed=allowed_tuple)
    if leaked:
        raise StudentVoiceError(
            "worksheet copy contains teacher-guide modeling voice: " + ", ".join(leaked)
            + ". Rewrite in student voice; teacher guidance belongs in the teacher guide and "
            "slide deck, not on the student sheet. Declare deliberately student-facing "
            "phrases via explicit_student_copy_teacher_voice_phrases."
        )
