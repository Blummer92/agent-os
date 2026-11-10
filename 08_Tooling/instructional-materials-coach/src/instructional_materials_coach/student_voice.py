"""Student-voice screening for student-facing worksheet copy (#3213).

Teacher-guide language leaked onto the Motion Spot student pages: rigor-ramp
stage labels written for the teacher, cognitive-load jargon, teacher-phrased
gate and recovery rules, and the teacher's modeling script. This module
screens student-facing copy for that modeling voice, mirroring the
internal-review-language screen in ``student_material_pdf.py``.

Matching (#3644 R5 repair) is Unicode-normalized and casefolded with
explicit zero-width-separator and dash-variant handling, followed by
word/token-boundary detection -- never bare substring matching. The old
whitespace-only substring scan both false-positived ("Translate stage
directions into a storyboard." blocked by ``late stage``; "Investigate
rules" blocked by ``gate rule``) and admitted evasions (``Heavy-modeling``,
``teacher\\u200b model``).

Deliberate student-facing uses are declared explicitly (the PDF preview path
exposes ``explicit_student_copy_teacher_voice_phrases``); unknown
declarations fail closed so a typo cannot silently read as intent.
Declarations are normalized exactly like scanned copy, so an invisible
character cannot dodge the bounded vocabulary either.

``"sentence frames"`` is intentionally NOT screened: it is a legitimate
classroom tool term that can appear in genuine student copy, and the leaked
stage-label paragraphs that quoted it always carry a screened marker
(``"heavy modeling"``, ``"early stage"``) that this scan catches.

This module performs no I/O and grants no authority.
"""
from __future__ import annotations

import itertools
import re
import unicodedata
from typing import Any, Container, Iterable, Mapping

#: Teacher-guide modeling voice that must not appear in student-facing
#: worksheet copy by default. Each entry is ``(label, phrase)``; labels are
#: reported in blocked receipts and ``_KNOWN`` phrases are the bounded
#: explicit-declaration vocabulary. Matching is case-insensitive on
#: Unicode-normalized copy with word/token boundaries (see
#: :func:`normalize_phrase`).
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

#: Invisible separators that must not split (or join) a phrase into an
#: undetectable shape: zero-width space, zero-width non-joiner, zero-width
#: joiner, zero-width no-break space / BOM, word joiner, Mongolian vowel
#: separator. Each is treated as a word separator for matching, so both
#: ``teacher\\u200bmodel`` and ``teacher\\u200b model`` read as
#: ``teacher model``.
_ZERO_WIDTH_SEPARATORS = "\u200b\u200c\u200d\ufeff\u2060\u180e"

#: Dash variants treated as word separators for matching (ASCII hyphen-minus
#: plus Unicode dash punctuation and the minus sign), so ``Heavy-modeling``
#: and ``early\\u2014stage`` read as ``heavy modeling`` and ``early stage``.
#: The soft hyphen (\\u00ad) is handled separately in :func:`_canonical_forms`.
_DASH_VARIANTS = "-\u2010\u2011\u2012\u2013\u2014\u2015\u2212"

#: Soft hyphen: an intra-word hyphenation hint that is invisible unless a
#: line breaks there. Each occurrence is BOTH a plausible intra-word join
#: (``revis\\u00adion`` reads as ``revision``) and a plausible word
#: separator (``heavy\\u00admodeling`` as an evasion), so canonicalization
#: tries every combination (bounded; see :func:`_canonical_forms`).
_SOFT_HYPHEN = "\u00ad"

_SEPARATOR_RUN_RE = re.compile(
    f"[{re.escape(_ZERO_WIDTH_SEPARATORS + _DASH_VARIANTS + _SOFT_HYPHEN)}]+"
)

#: Enumeration cap for soft-hyphen readings: 2**n combinations for n
#: occurrences. Beyond the cap the two heuristic readings (all deleted,
#: all separators) are used instead.
_MAX_SHY_ENUMERATION = 6


def _finish_canonical(text: str) -> str:
    text = _SEPARATOR_RUN_RE.sub(" ", text)
    return " ".join(text.casefold().split())


def _canonical_forms(text: str) -> tuple[str, ...]:
    """Every canonical form of ``text`` used for teacher-voice matching.

    NFKC normalization and casefolding apply to all forms; zero-width
    separators and dash variants always become word separators. Each soft
    hyphen is tried both deleted and as a separator, because it is both a
    legitimate intra-word hyphenation hint and a plausible evasion
    character. Combinations are enumerated up to ``_MAX_SHY_ENUMERATION``
    occurrences; beyond that the two heuristic readings apply. Forms are
    deduplicated, stable-ordered.
    """
    base = unicodedata.normalize("NFKC", str(text))
    shy_positions = [index for index, char in enumerate(base) if char == _SOFT_HYPHEN]
    if len(shy_positions) <= _MAX_SHY_ENUMERATION:
        combos: Iterable[tuple[str, ...]] = itertools.product(
            ("", " "), repeat=len(shy_positions)
        )
    else:
        combos = [
            tuple("" for _ in shy_positions),
            tuple(" " for _ in shy_positions),
        ]
    forms: list[str] = []
    for combo in combos:
        chars = list(base)
        for position, replacement in zip(shy_positions, combo):
            chars[position] = replacement
        collapsed = _finish_canonical("".join(chars))
        if collapsed not in forms:
            forms.append(collapsed)
    return tuple(forms)


def normalize_phrase(phrase: str) -> str:
    """Primary canonical form for teacher-voice matching.

    Applies NFKC normalization and casefolding, maps zero-width separators
    and dash variants to word separators, then collapses whitespace. Both
    scanned copy and explicit declarations go through canonicalization, so
    an invisible character or dash variant cannot evade the vocabulary or
    smuggle an undeclared phrase past the exemption check. See
    :func:`_canonical_forms` for the soft-hyphen readings.
    """
    return _canonical_forms(phrase)[0]


def _phrase_pattern(phrase: str) -> "re.Pattern[str]":
    """Word/token-boundary pattern for one canonical vocabulary phrase."""
    return re.compile(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)")


# Precompiled (label, canonical phrase, boundary pattern) triples, in
# TEACHER_VOICE_PHRASES order. Labels are reported deduplicated in this
# order.
_PHRASE_PATTERNS: tuple[tuple[str, str, "re.Pattern[str]"], ...] = tuple(
    (label, normalize_phrase(phrase), _phrase_pattern(normalize_phrase(phrase)))
    for label, phrase in TEACHER_VOICE_PHRASES
)

_KNOWN_TEACHER_VOICE_PHRASES: frozenset[str] = frozenset(
    canonical for _, canonical, _ in _PHRASE_PATTERNS
)


def known_teacher_voice_phrases() -> frozenset[str]:
    """The bounded vocabulary for explicit student-copy declarations."""
    return _KNOWN_TEACHER_VOICE_PHRASES


def scan_teacher_voice(
    texts: Iterable[str],
    *,
    allowed: Container[str] = (),
) -> tuple[str, ...]:
    """Return labels for teacher-voice phrases found in the given texts.

    Each text is Unicode-normalized, casefolded, and matched with
    word/token boundaries: ``late stage`` matches ``the late stage`` but
    not ``Translate stage``; ``gate rule`` matches ``the gate rule:`` but
    not ``Investigate rules``. Hyphen, Unicode-dash, zero-width, and
    soft-hyphen variants of a phrase are caught (``Heavy-modeling``,
    ``teacher\\u200b model``, ``revis\\u00adion``). A phrase in ``allowed``
    (canonicalized exactly like scanned copy) is treated as deliberately
    student-facing and is not reported. Returns the matching labels in
    phrase-list order, deduplicated.
    """
    normalized_texts = [
        form for text in texts for form in _canonical_forms(text)
    ]
    allowed_normalized = {
        form for phrase in allowed for form in _canonical_forms(phrase)
    }
    found: list[str] = []
    for label, canonical, pattern in _PHRASE_PATTERNS:
        if canonical in allowed_normalized:
            continue
        if any(pattern.search(text) for text in normalized_texts):
            if label not in found:
                found.append(label)
    return tuple(found)


class StudentVoiceError(ValueError):
    """Fail-closed error for teacher-guide modeling voice in student-facing copy."""


def _normalize_token_name(token: object) -> str | None:
    """Placeholder name with any ``{{...}}`` wrapper stripped."""
    if not isinstance(token, str) or not token.strip():
        return None
    token = token.strip()
    if token.startswith("{{") and token.endswith("}}"):
        token = token[2:-2].strip()
    return token or None


def _request_token_name(request: Mapping[str, Any]) -> str | None:
    """The ``{{token}}`` placeholder name of a ``replaceAllText`` request."""
    replace = request.get("replaceAllText") if isinstance(request, Mapping) else None
    contains = replace.get("containsText") if isinstance(replace, Mapping) else None
    token = contains.get("text") if isinstance(contains, Mapping) else None
    return _normalize_token_name(token)


def docs_replace_student_texts(
    docs_requests: Iterable[Mapping[str, Any]],
    *,
    used_tokens: Container[str] | None = None,
) -> tuple[str, ...]:
    """Extract the student-facing replacement text from Docs ``replaceAllText`` requests.

    Only ``replaceText`` values are student-facing; ``containsText`` is the
    ``{{token}}`` placeholder being replaced. Non-``replaceAllText`` requests
    (for example style updates) carry no student copy and are skipped.

    ``used_tokens`` is the verified projection of placeholder names the
    worksheet Doc template actually carries (#3644 R5). Requests whose token
    is positively absent from the template are no-op writes -- the token
    never occurs in the copied Doc -- so their replacement values are not
    student-facing worksheet copy and are excluded from the scan. This is a
    projection lookup, never a hard-coded ``slide_*`` assumption: a slide
    token genuinely present in the worksheet template stays in scope.
    ``None`` (projection unverified) scans every replacement value,
    fail-closed.
    """
    used_names = (
        None
        if used_tokens is None
        else {name for name in (_normalize_token_name(t) for t in used_tokens) if name}
    )
    texts: list[str] = []
    for request in docs_requests:
        replace = request.get("replaceAllText") if isinstance(request, Mapping) else None
        if not isinstance(replace, Mapping):
            continue
        if used_names is not None:
            token_name = _request_token_name(request)
            # Fail closed on unparseable tokens: only positively-unused
            # tokens leave the scan.
            if token_name is not None and token_name not in used_names:
                continue
        text = replace.get("replaceText", "")
        texts.append(text if isinstance(text, str) else "")
    return tuple(texts)


def require_student_voice(
    docs_requests: Iterable[Mapping[str, Any]],
    *,
    allowed: Iterable[str] = (),
    used_tokens: Container[str] | None = None,
) -> None:
    """Fail closed when planned worksheet copy carries teacher-guide modeling voice.

    Production Docs-build seam: the replacement text of the governed
    ``replaceAllText`` requests is exactly the student-facing copy written
    into the worksheet Doc, so this runs in the build composition before any
    Drive write. Reuses :func:`scan_teacher_voice` -- the single governed
    vocabulary. ``used_tokens`` scopes the scan to the worksheet template's
    verified token projection (see :func:`docs_replace_student_texts`); a
    phrase in ``allowed`` is deliberately student-facing, but only when it
    names a known vocabulary phrase: unknown declarations fail closed so a
    typo cannot silently read as intent.
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
        forms = _canonical_forms(phrase)
        if not any(form in known for form in forms):
            raise StudentVoiceError(
                f"unknown student-copy teacher-voice phrase: {phrase}"
            )
        if any(form in seen for form in forms):
            raise StudentVoiceError(
                "explicit student-copy teacher-voice phrases must be unique"
            )
        seen.update(forms)
    leaked = scan_teacher_voice(
        docs_replace_student_texts(docs_requests, used_tokens=used_tokens),
        allowed=allowed_tuple,
    )
    if leaked:
        raise StudentVoiceError(
            "worksheet copy contains teacher-guide modeling voice: " + ", ".join(leaked)
            + ". Rewrite in student voice; teacher guidance belongs in the teacher guide and "
            "slide deck, not on the student sheet. Declare deliberately student-facing "
            "phrases via explicit_student_copy_teacher_voice_phrases."
        )
