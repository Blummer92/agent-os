"""Deterministic, write-free pre-catalog review of a lesson candidate (#3418).

CKR5 identity only recognizes a recurrence when an existing lesson carries the
content-hash identity, which Notion rows (``LL-n``) never do, and CKR7's
``_compatible`` only matches exact casefolded guidance over a caller-supplied
set. A retitled paraphrase of an existing lesson therefore reached the reviewed
catalog as a brand-new ``create``. This function closes that gap *before* a
catalog PR, using only finite caller-supplied evidence:

* it never reads Notion, searches, embeds, or calls a model;
* similarity is advisory: only guidance that is equal after NFKC, casefold and
  whitespace collapse (both fields together) can yield DUPLICATE or
  UPDATE_EXISTING; every paraphrase, contradiction or ambiguity is HUMAN_REVIEW;
* negations are never dropped from comparison and text is never truncated, so
  "never X" cannot be mistaken for "always X";
* every result has ``publication_authorized`` false: the reviewed catalog PR,
  the owner's exact write command and the writer's exact-title / Lesson-ID /
  revision checks remain the only publication path.

Known limit (measured, not assumed): token overlap cannot certify novelty. The
#3690 continuation candidate and live LL-82 express nearly the same lesson in
different vocabulary yet score a guidance similarity of only 0.09 (whole-text
overlap coefficient 0.28, indistinguishable from unrelated lessons at 0.27-0.28).
So the absence of a lexical match is reported as NO_LEXICAL_MATCH with
``novelty-not-semantically-verified``, never as a validated new lesson: a human
must still compare meaning before a catalog entry is merged.

Also not matched (found by independent QA; all stay non-authorizing ``no-lexical-match``):
visually identical homoglyph copies (NFKC does not fold confusables), the same words
with guidance and guardrail swapped, an identical title or root cause with different
guidance, and a candidate that is only a fragment of a long existing guidance. The
writer's exact-title and Lesson-ID checks still apply at write time.

Scope of ``existing_set_complete``: the caller's bounded, candidate-relevant read was
not truncated. It does not mean "all of Notion": the database holds far more lessons
than the 25-lesson bound, and one ingress request (16 KB) carries roughly 6 (maximum-size
entries) to 25 (short entries) lessons, about 15 at ~1 KB each. Lessons outside the
supplied set are not compared.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum

MAX_EXISTING_LESSONS = 25
MAX_REFS = 20
MAX_FIELD_CHARS = 1024
MIN_GUIDANCE_TOKENS = 4
AMBIGUOUS_FLOOR = 0.4
NEAR_MATCH = 0.6
CAUSE_DISTINCT_BELOW = 0.3
MAX_ADVISORY_SCORES = 5

# Same grammar as lesson_learning_loop.LESSON_ID / REVISION (pinned by a parity test).
LESSON_ID = re.compile(r"LL-[1-9][0-9]{0,8}")
REVISION = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z")
GITHUB_REF = re.compile(r"https://github\.com/Blummer92/agent-os/(?:issues|pull)/[1-9][0-9]{0,6}(?:#[A-Za-z0-9_-]{1,64})?")

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_STOP = frozenset({
    "the", "a", "an", "of", "to", "and", "or", "in", "on", "for", "is", "are", "be",
    "it", "this", "that", "with", "as", "at", "by", "from", "then", "than", "so",
})
# Deliberately NOT stop words: dropping one would make opposite guidance look equal.
NEGATIONS = frozenset({
    "not", "never", "no", "without", "cannot", "cant", "dont", "doesnt", "didnt", "isnt",
    "arent", "wasnt", "wont", "shouldnt", "mustnt", "couldnt", "unless", "nor", "neither",
    "avoid", "forbid", "forbidden", "prohibit", "prohibited",
})


class PublicationVerdict(str, Enum):
    NO_LEXICAL_MATCH = "no-lexical-match"
    UPDATE_EXISTING = "update-existing"
    DUPLICATE = "duplicate"
    INSUFFICIENT_EVIDENCE = "insufficient-evidence"
    HUMAN_REVIEW = "human-review"


@dataclass(frozen=True, slots=True)
class CandidateLesson:
    title: str
    root_cause: str
    what_to_do_next_time: str
    guardrail: str
    canonical_github_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExistingLessonSummary:
    """One existing lesson as read through the bounded read-only route."""

    lesson_id: str
    source_revision: str
    title: str
    what_to_do_next_time: str
    guardrail: str
    root_cause: str | None = None
    canonical_github_refs: tuple[str, ...] = ()
    archived: bool = False


@dataclass(frozen=True, slots=True)
class PublicationReview:
    verdict: PublicationVerdict
    reason_codes: tuple[str, ...]
    matched_lesson_id: str | None = None
    expected_revision: str | None = None
    advisory_scores: tuple[tuple[str, float], ...] = ()
    authority_created: bool = False
    notion_write_performed: bool = False
    publication_authorized: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "verdict": self.verdict.value,
            "reason_codes": list(self.reason_codes),
            "matched_lesson_id": self.matched_lesson_id,
            "expected_revision": self.expected_revision,
            "advisory_scores": [{"lesson_id": lid, "score": score} for lid, score in self.advisory_scores],
            "authority_created": self.authority_created,
            "notion_write_performed": self.notion_write_performed,
            "publication_authorized": self.publication_authorized,
        }


def _norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _tokens(text: str) -> frozenset[str]:
    folded = unicodedata.normalize("NFKC", text).casefold().replace("'", "").replace("’", "")
    return frozenset(word for word in _WORD.findall(folded) if word not in _STOP)


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _guidance_score(candidate: CandidateLesson, existing: ExistingLessonSummary) -> float:
    return (
        _jaccard(_tokens(candidate.what_to_do_next_time), _tokens(existing.what_to_do_next_time))
        + _jaccard(_tokens(candidate.guardrail), _tokens(existing.guardrail))
    ) / 2


def _polarity(*texts: str) -> frozenset[str]:
    return frozenset().union(*(_tokens(text) & NEGATIONS for text in texts))


def _is_exact(candidate: CandidateLesson, existing: ExistingLessonSummary) -> bool:
    return (
        _norm(candidate.what_to_do_next_time) == _norm(existing.what_to_do_next_time)
        and _norm(candidate.guardrail) == _norm(existing.guardrail)
    )


def _base_ref(ref: str) -> str:
    return ref.split("#", 1)[0]


def _review(verdict, reasons, *, matched=None, revision=None, scores=()):
    return PublicationReview(verdict, tuple(reasons), matched, revision, tuple(scores))


def _text_ok(value: object) -> bool:
    return type(value) is str and bool(value.strip())


def review_lesson_candidate(
    candidate: CandidateLesson,
    existing_lessons: tuple[ExistingLessonSummary, ...],
    *,
    existing_set_complete: bool,
) -> PublicationReview:
    """Classify a candidate against verified existing lessons; never authorizes anything."""
    if type(candidate) is not CandidateLesson:
        raise TypeError("candidate must be a CandidateLesson")
    if type(existing_lessons) is not tuple or any(type(item) is not ExistingLessonSummary for item in existing_lessons):
        raise TypeError("existing_lessons must be a tuple of ExistingLessonSummary values")
    if type(existing_set_complete) is not bool:
        raise TypeError("existing_set_complete must be bool")

    fields = (candidate.title, candidate.root_cause, candidate.what_to_do_next_time, candidate.guardrail)
    if not all(type(value) is str for value in fields) or type(candidate.canonical_github_refs) is not tuple:
        raise TypeError("candidate fields must be text and a tuple of references")

    # 1. Unsupported or generic candidates are held before any comparison.
    reasons: list[str] = []
    if not any(GITHUB_REF.fullmatch(ref) for ref in candidate.canonical_github_refs if type(ref) is str):
        reasons.append("candidate-canonical-reference-missing")
    if not candidate.root_cause.strip():
        reasons.append("candidate-root-cause-missing")
    next_tokens, guardrail_tokens = _tokens(candidate.what_to_do_next_time), _tokens(candidate.guardrail)
    if len(next_tokens) < MIN_GUIDANCE_TOKENS or len(guardrail_tokens) < MIN_GUIDANCE_TOKENS:
        reasons.append("candidate-guidance-too-generic")
    elif _norm(candidate.what_to_do_next_time) == _norm(candidate.guardrail):
        reasons.append("candidate-guidance-restates-guardrail")
    if reasons:
        return _review(PublicationVerdict.INSUFFICIENT_EVIDENCE, reasons)

    # 2. Bounds: never truncate to fit, never authorize on truncated text.
    if any(len(value) > MAX_FIELD_CHARS for value in fields) or len(candidate.canonical_github_refs) > MAX_REFS:
        return _review(PublicationVerdict.HUMAN_REVIEW, ["candidate-text-over-bound"])
    if len(existing_lessons) > MAX_EXISTING_LESSONS:
        return _review(PublicationVerdict.HUMAN_REVIEW, ["existing-lesson-budget-exceeded"])
    if not existing_set_complete:
        return _review(PublicationVerdict.HUMAN_REVIEW, ["existing-set-incomplete"])

    # 3. Existing lessons must carry a verified identity and revision.
    seen: set[str] = set()
    for item in existing_lessons:
        texts = (item.title, item.what_to_do_next_time, item.guardrail)
        if not all(_text_ok(value) for value in texts) or (item.root_cause is not None and type(item.root_cause) is not str):
            return _review(PublicationVerdict.HUMAN_REVIEW, ["existing-lesson-malformed"])
        if type(item.lesson_id) is not str or LESSON_ID.fullmatch(item.lesson_id) is None \
                or type(item.source_revision) is not str or REVISION.fullmatch(item.source_revision) is None:
            return _review(PublicationVerdict.HUMAN_REVIEW, ["existing-identity-unverified"])
        if item.lesson_id in seen:
            return _review(PublicationVerdict.HUMAN_REVIEW, ["duplicate-existing-lesson-id"])
        seen.add(item.lesson_id)
        if any(len(value) > MAX_FIELD_CHARS for value in (*texts, item.root_cause or "")):
            return _review(PublicationVerdict.HUMAN_REVIEW, ["existing-text-over-bound"])

    # 4. Advisory comparison. Exact guidance equality is the only automatic signal.
    scored = []
    for item in existing_lessons:
        score = 1.0 if _is_exact(candidate, item) else _guidance_score(candidate, item)
        if score >= AMBIGUOUS_FLOOR:
            scored.append((score, item))
    scored.sort(key=lambda pair: (-pair[0], pair[1].lesson_id))
    advisory = tuple((item.lesson_id, round(score, 3)) for score, item in scored[:MAX_ADVISORY_SCORES])

    if not scored:
        return _review(PublicationVerdict.NO_LEXICAL_MATCH, ["no-existing-lesson-above-similarity-floor", "novelty-not-semantically-verified"])
    if len(scored) > 1:
        return _review(PublicationVerdict.HUMAN_REVIEW, ["ambiguous-multiple-matches"], scores=advisory)

    score, match = scored[0]
    common = {"matched": match.lesson_id, "revision": match.source_revision, "scores": advisory}
    if match.archived:
        return _review(PublicationVerdict.HUMAN_REVIEW, ["matches-archived-lesson"], **common)
    if _is_exact(candidate, match):
        if match.root_cause and _jaccard(_tokens(candidate.root_cause), _tokens(match.root_cause)) < CAUSE_DISTINCT_BELOW:
            return _review(PublicationVerdict.HUMAN_REVIEW, ["same-guidance-different-cause"], **common)
        known = {_base_ref(ref) for ref in match.canonical_github_refs if type(ref) is str}
        # Only a well-formed repository reference is evidence; junk or foreign refs are not.
        if any(
            type(ref) is str and GITHUB_REF.fullmatch(ref) and _base_ref(ref) not in known
            for ref in candidate.canonical_github_refs
        ):
            return _review(PublicationVerdict.UPDATE_EXISTING, ["same-guidance-new-evidence"], **common)
        return _review(PublicationVerdict.DUPLICATE, ["same-guidance-no-new-evidence"], **common)
    if _polarity(candidate.what_to_do_next_time, candidate.guardrail) != _polarity(
        match.what_to_do_next_time, match.guardrail
    ):
        return _review(PublicationVerdict.HUMAN_REVIEW, ["polarity-conflict"], **common)
    reason = "possible-duplicate-paraphrase" if score >= NEAR_MATCH else "ambiguous-similarity"
    return _review(PublicationVerdict.HUMAN_REVIEW, [reason], **common)
