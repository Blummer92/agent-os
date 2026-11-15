"""Production composition of the existing Lessons Learned learning seams (#3418).

This module wires already-implemented, authority-false owners into the finite
CKR6 GitHub ingress. It adds no selector, writer, store, scheduler or authority:

- capture: CI/review producer (#1560) -> CKR5 qualification/identity (#1352)
  -> CKR6 Notion record projection (#1354) -> reviewable catalog-entry draft for
  the #3417 governed writer. Nothing is persisted.
- refinement: exact known-ID read of the current lesson through the existing
  read-only route -> CKR7 enrichment (#1364) -> reviewable update-entry draft
  bound to the canonical Lesson ID and its exact current revision.
- receipts: one bounded marker comment proving that a lesson *returned by a CKR6
  result* influenced (or was deliberately skipped for) a concrete decision.
  Retrieval alone never produces a valid receipt.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Mapping

from agent_memory_context_manager.ci_review_learning import (
    LearningSignal,
    ProducerDisposition,
    StructuredLearningOutcome,
    normalize_learning_outcome,
)
from agent_memory_context_manager.coding_failure_learning import evaluate_coding_failure
from agent_memory_context_manager.lesson_activation_bridge import (
    LessonActivationSkip,
    build_known_reference_query,
    normalize_lesson_row,
)
from agent_memory_context_manager.lesson_enrichment import (
    CurrentLessonEvidence,
    EvidenceEffect,
    RelatedGitHubEvidence,
    evaluate_lesson_enrichment,
)
from agent_memory_context_manager.notion_learning_projection import (
    ProjectionDisposition,
    project_lesson_to_notion,
)

from .ckr6_github_reader import (
    ALLOWED_REPOSITORY as GITHUB_REPOSITORY,
    GitHubIssueCommentReadUnavailable,
    get_github_issue_comment_reader,
)
from .lesson_publication_review import (
    MAX_EXISTING_LESSONS,
    CandidateLesson,
    ExistingLessonSummary,
    review_lesson_candidate,
)

ReadExecutor = Callable[[Mapping[str, Any]], Mapping[str, Any]]
# Trusted exact-comment read: comment id -> GitHub issue-comment *record*.
# The record must arrive from the authenticated read path; caller-supplied
# bodies or dicts are never receipt evidence.
CommentFetch = Callable[[int], Mapping[str, Any]]

MAX_TEXT = 512
MAX_DETAIL = 1024
MAX_REFS = 20
MAX_EVIDENCE = 8
MAX_RECEIPT_REFS = 5
CATALOG_TEXT_LIMIT = 512
LESSON_ID = re.compile(r"LL-([1-9][0-9]{0,8})")
GITHUB_URL = re.compile(r"https://github\.com/Blummer92/agent-os/(?:issues|pull)/[1-9][0-9]{0,6}(?:#[A-Za-z0-9_-]{1,64})?")
# Canonical receipt comment references. The anchor-free API form exists
# because some GitHub write hosts rewrite `#issuecomment-` anchors in comment
# bodies (observed on #3418, comment 6080494403); both name one exact comment.
RECEIPT_COMMENT_URL = re.compile(
    r"https://github\.com/Blummer92/agent-os/(?:issues|pull)/[1-9][0-9]{0,6}#issuecomment-[1-9][0-9]{0,14}"
    r"|https://api\.github\.com/repos/Blummer92/agent-os/issues/comments/[1-9][0-9]{0,14}"
)
REVISION = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z")

CANDIDATE_FIELDS = frozenset({
    "source_reference", "signal", "failure_signature", "ecosystem", "capability_kind",
    "lesson_summary", "what_happened", "severity", "owner_agent", "canonical_github_refs",
    "evidence_refs", "affected_paths", "future_use_hints", "library_name",
    "what_to_do_next_time", "guardrail", "reusable_rule_proven", "permanent_regression_ref",
    "root_cause_or_diagnosis", "existing_lessons", "existing_set_complete",
})
EXISTING_LESSON_FIELDS = frozenset({
    "lesson_id", "source_revision", "title", "what_to_do_next_time", "guardrail",
    "root_cause", "canonical_github_refs", "archived",
})
EVIDENCE_FIELDS = frozenset({
    "reference", "effect", "canonical_github_refs", "evidence_refs", "revised_title",
    "revised_what_happened", "revised_next_time", "revised_guardrail",
})
REFINEMENT_FIELDS = frozenset({"lesson_id", "source_revision", "receipt_refs", "evidence"})

# Reviewer-editable suggestion only; the live option must still exist (#3417).
_SIGNAL_LEARNING_TYPE = {
    LearningSignal.SUBSTANTIVE_REVIEW_FINDING: "QA feedback",
    LearningSignal.ESCAPED_REGRESSION: "Mistake",
    LearningSignal.REPEATED_REPAIR: "Mistake",
    LearningSignal.PROPERTY_COUNTEREXAMPLE: "Testing lesson",
    LearningSignal.OBSOLETE_VALIDATION: "Testing lesson",
    LearningSignal.FLAKY_DIAGNOSIS: "Testing lesson",
}

_NO_AUTHORITY = {
    "authority_created": False,
    "notion_write_performed": False,
    "publication_authorized": False,
}


def _text(value: object, name: str, limit: int = MAX_TEXT) -> str:
    if type(value) is not str or not value.strip() or len(value) > limit:
        raise ValueError(f"{name} must be bounded non-empty text")
    return value


def _optional_text(value: object, name: str, limit: int = MAX_TEXT) -> str | None:
    return None if value is None else _text(value, name, limit)


def _refs(value: object, name: str, limit: int = MAX_REFS) -> tuple[str, ...]:
    if value is None:
        return ()
    if type(value) is not list or len(value) > limit:
        raise ValueError(f"{name} must be a bounded list")
    return tuple(_text(item, name) for item in value)


def _source_link(refs: tuple[str, ...]) -> str | None:
    for ref in refs:
        match = GITHUB_URL.fullmatch(ref)
        if match is not None:
            return ref.split("#", 1)[0]
    return None


# ---------------------------------------------------------------- capture


def parse_candidate(payload: object) -> StructuredLearningOutcome:
    if not isinstance(payload, Mapping):
        raise ValueError("candidate must be a mapping")
    unknown = set(payload) - CANDIDATE_FIELDS
    if unknown:
        raise ValueError("unsupported CKR6 envelope fields: candidate")
    try:
        signal = LearningSignal(payload.get("signal"))
    except ValueError:
        raise ValueError("candidate signal must be a finite learning signal") from None
    proven = payload.get("reusable_rule_proven", False)
    if type(proven) is not bool:
        raise ValueError("candidate reusable_rule_proven must be bool")
    return StructuredLearningOutcome(
        source_reference=_text(payload.get("source_reference"), "source_reference"),
        signal=signal,
        failure_signature=_text(payload.get("failure_signature"), "failure_signature"),
        ecosystem=_text(payload.get("ecosystem"), "ecosystem"),
        capability_kind=_text(payload.get("capability_kind"), "capability_kind"),
        lesson_summary=_text(payload.get("lesson_summary"), "lesson_summary"),
        what_happened=_text(payload.get("what_happened"), "what_happened", MAX_DETAIL),
        severity=_text(payload.get("severity"), "severity"),
        owner_agent=_text(payload.get("owner_agent"), "owner_agent"),
        canonical_github_refs=_refs(payload.get("canonical_github_refs"), "canonical_github_refs"),
        evidence_refs=_refs(payload.get("evidence_refs"), "evidence_refs"),
        affected_paths=_refs(payload.get("affected_paths"), "affected_paths"),
        future_use_hints=_refs(payload.get("future_use_hints"), "future_use_hints"),
        library_name=_optional_text(payload.get("library_name"), "library_name"),
        what_to_do_next_time=_optional_text(payload.get("what_to_do_next_time"), "what_to_do_next_time"),
        guardrail=_optional_text(payload.get("guardrail"), "guardrail"),
        reusable_rule_proven=proven,
        permanent_regression_ref=_optional_text(payload.get("permanent_regression_ref"), "permanent_regression_ref"),
    )


def parse_existing_lessons(payload: Mapping[str, Any]) -> tuple[tuple[ExistingLessonSummary, ...], bool]:
    """Bounded caller-supplied summaries of existing lessons read through the bounded route."""
    complete = payload.get("existing_set_complete", False)
    if type(complete) is not bool:
        raise ValueError("candidate existing_set_complete must be bool")
    raw = payload.get("existing_lessons")
    if raw is None:
        return (), False
    if type(raw) is not list or len(raw) > MAX_EXISTING_LESSONS:
        raise ValueError("candidate existing_lessons must be a bounded list")
    parsed = []
    for item in raw:
        if not isinstance(item, Mapping) or set(item) - EXISTING_LESSON_FIELDS:
            raise ValueError("candidate existing_lessons entries must use supported fields")
        archived = item.get("archived", False)
        if type(archived) is not bool:
            raise ValueError("candidate existing_lessons archived must be bool")
        parsed.append(ExistingLessonSummary(
            lesson_id=_text(item.get("lesson_id"), "existing lesson_id", 16),
            source_revision=_text(item.get("source_revision"), "existing source_revision", 40),
            title=_text(item.get("title"), "existing title"),
            what_to_do_next_time=_text(item.get("what_to_do_next_time"), "existing what_to_do_next_time"),
            guardrail=_text(item.get("guardrail"), "existing guardrail"),
            root_cause=_optional_text(item.get("root_cause"), "existing root_cause", MAX_DETAIL),
            canonical_github_refs=_refs(item.get("canonical_github_refs"), "existing canonical_github_refs"),
            archived=archived,
        ))
    return tuple(parsed), complete


def capture_lesson_candidate(payload: Mapping[str, Any]) -> dict[str, object]:
    """Producer -> CKR5 -> projection -> reviewable catalog draft. Writes nothing."""
    outcome = parse_candidate(payload)
    existing, existing_complete = parse_existing_lessons(payload)
    diagnosis = _optional_text(payload.get("root_cause_or_diagnosis"), "root_cause_or_diagnosis")
    produced = normalize_learning_outcome(outcome)
    if produced.disposition is not ProducerDisposition.CKR5_CANDIDATE or produced.observation is None:
        status = {
            ProducerDisposition.NOT_REUSABLE: "non-reusable",
            ProducerDisposition.INSUFFICIENT: "insufficient-evidence",
        }.get(produced.disposition, "manual-review")
        return {"status": status, "reason_codes": list(produced.reason_codes),
                "lesson_proposal": None}
    learned = evaluate_coding_failure(produced.observation)
    projection = project_lesson_to_notion(learned, root_cause_or_diagnosis=diagnosis)
    reasons = [*produced.reason_codes, *projection.reason_codes]
    record = projection.record
    if projection.disposition not in (ProjectionDisposition.ELIGIBLE, ProjectionDisposition.RECURRENCE) or record is None:
        return {"status": learned.disposition.value, "reason_codes": reasons, "lesson_proposal": None}
    narrative = {
        "Lesson Learned": record.title,
        "What Happened": record.symptom if diagnosis is None else f"{record.symptom} Diagnosis: {diagnosis}",
        "What To Do Next Time": record.resolution_or_next_time,
        "Guardrail": record.prevention_guardrail,
    }
    descriptive = {}
    learning_type = _SIGNAL_LEARNING_TYPE.get(outcome.signal)
    if learning_type:
        descriptive["Learning Type"] = learning_type
    link = _source_link(record.canonical_github_refs)
    if link:
        descriptive["Source Link"] = link
    over = sorted(name for name, value in narrative.items() if len(value) > CATALOG_TEXT_LIMIT)
    # A reviewed catalog entry can be write-ready without being CKR6-eligible.
    # Area must be supplied by a reviewer; Source Link anchors currentness.
    activation_gaps = [
        name for name in ("Area", "Learning Type", "Source Link")
        if name not in descriptive
    ]
    # Pre-catalog quality/duplicate review against caller-supplied verified existing
    # lessons. Advisory and authority-false; without a complete verified set it holds.
    review = review_lesson_candidate(
        CandidateLesson(
            title=record.title,
            root_cause=diagnosis or "",
            what_to_do_next_time=record.resolution_or_next_time,
            guardrail=record.prevention_guardrail,
            canonical_github_refs=tuple(record.canonical_github_refs),
        ),
        existing,
        existing_set_complete=existing_complete,
    )
    return {
        "status": learned.disposition.value,
        "reason_codes": reasons,
        "lesson_proposal": {
            "operation": record.operation,
            "lesson_identity": learned.lesson_identity,
            "core_identity": learned.core_identity,
            "proposed_recurrence_count": record.proposed_recurrence_count,
            "severity": record.severity,
            "canonical_github_refs": list(record.canonical_github_refs),
            "evidence_refs": list(record.evidence_refs),
            "surface_before_work_recommendation": record.surface_before_work,
            # Reviewed through an ordinary catalog PR; the owner then issues
            # one /agent-os notion-write command (#3417). Never auto-written.
            "catalog_entry_draft": {
                "target_lesson_id": None,
                "properties": {**narrative, **descriptive},
            },
            "catalog_ready": not over,
            "activation_gaps": activation_gaps,
            # These fields are *not* writable via the governed catalog writer.
            "owner_activation_required": ["Status", "Surface Before Work?"],
            "catalog_fields_over_limit": over,
            "publication_review": review.as_dict(),
            **_NO_AUTHORITY,
        },
    }


# ------------------------------------------------------------- refinement


def parse_refinement(payload: object) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        raise ValueError("refinement must be a mapping")
    if set(payload) - REFINEMENT_FIELDS:
        raise ValueError("unsupported CKR6 envelope fields: refinement")
    lesson_id = _text(payload.get("lesson_id"), "lesson_id")
    if LESSON_ID.fullmatch(lesson_id) is None:
        raise ValueError("refinement lesson_id must be a canonical Lesson ID")
    revision = _text(payload.get("source_revision"), "source_revision")
    if REVISION.fullmatch(revision) is None:
        raise ValueError("refinement source_revision must be an exact revision")
    receipts = _refs(payload.get("receipt_refs"), "receipt_refs", MAX_RECEIPT_REFS)
    # Refinement is connected to observed use: at least one receipt comment.
    if not receipts or any(RECEIPT_COMMENT_URL.fullmatch(ref) is None for ref in receipts):
        raise ValueError("refinement receipt_refs must be canonical receipt comment URLs")
    raw_evidence = payload.get("evidence")
    if type(raw_evidence) is not list or not 0 < len(raw_evidence) <= MAX_EVIDENCE:
        raise ValueError("refinement evidence must be a bounded non-empty list")
    evidence = []
    for item in raw_evidence:
        if not isinstance(item, Mapping) or set(item) - EVIDENCE_FIELDS:
            raise ValueError("unsupported CKR6 envelope fields: evidence")
        try:
            effect = EvidenceEffect(item.get("effect"))
        except ValueError:
            raise ValueError("refinement evidence effect must be finite") from None
        evidence.append(RelatedGitHubEvidence(
            reference=_text(item.get("reference"), "reference"),
            effect=effect,
            canonical_github_refs=_refs(item.get("canonical_github_refs"), "canonical_github_refs"),
            evidence_refs=_refs(item.get("evidence_refs"), "evidence_refs") + receipts,
            revised_title=_optional_text(item.get("revised_title"), "revised_title"),
            revised_what_happened=_optional_text(item.get("revised_what_happened"), "revised_what_happened"),
            revised_next_time=_optional_text(item.get("revised_next_time"), "revised_next_time"),
            revised_guardrail=_optional_text(item.get("revised_guardrail"), "revised_guardrail"),
        ))
    return {"lesson_id": lesson_id, "source_revision": revision,
            "receipt_refs": receipts, "evidence": tuple(evidence)}


def _what_happened(row: Mapping[str, Any]) -> str | None:
    prop = row.get("properties", {}).get("What Happened")
    if not isinstance(prop, Mapping) or prop.get("type") != "rich_text":
        return None
    parts = [item.get("plain_text", "") for item in prop.get("rich_text") or () if isinstance(item, Mapping)]
    text = "".join(part for part in parts if isinstance(part, str)).strip()
    return text[:MAX_TEXT] or None


def propose_lesson_refinement(
    payload: Mapping[str, Any],
    execute_read: ReadExecutor,
    fetch_comment: CommentFetch | None = None,
) -> dict[str, object]:
    """Exact current lesson + receipt-verified evidence -> CKR7 proposal. Writes nothing.

    H1 barrier (#3418): a syntactically valid receipt URL is an identifier,
    never evidence. Before the lesson read or any CKR7 evaluation, EVERY
    supplied receipt reference is retrieved by exact comment id through the
    trusted GitHub read, validated for location/author/edit provenance,
    strictly parsed, and bound to a trusted CKR6 result that selected the
    same (lesson_id, source_revision) the refinement asks to change. A stop
    before the lesson read reports ``notion_read_performed`` false.
    """
    request = parse_refinement(payload)
    fetch = fetch_comment if fetch_comment is not None else _installed_comment_fetch()
    if fetch is None:
        return _receipt_barrier_stop("receipt-read-unavailable", manual_review=True)
    try:
        verify_receipt_evidence(request, fetch)
    except ReceiptEvidenceInvalid as exc:
        return _receipt_barrier_stop(exc.reason_code, manual_review=exc.manual_review)
    raw = execute_read(build_known_reference_query([request["lesson_id"]]))
    rows = raw.get("results") if isinstance(raw, Mapping) else None
    if type(rows) is not list:
        return {"status": "manual-review", "reason_codes": ["lesson-read-malformed"], "revision_proposal": None,
                "notion_read_performed": True}
    matches = []
    for row in rows[:5]:
        normalized = normalize_lesson_row(row) if isinstance(row, Mapping) else None
        if isinstance(normalized, LessonActivationSkip) and normalized.lesson_id == request["lesson_id"]:
            return {"status": "manual-review", "reason_codes": ["lesson-not-normalizable:" + normalized.reason],
                    "revision_proposal": None, "notion_read_performed": True}
        if normalized is not None and not isinstance(normalized, LessonActivationSkip) and normalized.lesson_id == request["lesson_id"]:
            matches.append((row, normalized))
    if len(matches) != 1:
        return {"status": "manual-review", "reason_codes": ["lesson-identity-not-unique" if matches else "lesson-not-found"],
                "revision_proposal": None, "notion_read_performed": True}
    row, lesson = matches[0]
    if lesson.source_revision != request["source_revision"]:
        # Never refine from stale text; the proposal must bind the live revision.
        return {"status": "rejected", "reason_codes": ["stale-lesson-revision"], "revision_proposal": None,
                "notion_read_performed": True}
    what_happened = _what_happened(row)
    if what_happened is None:
        return {"status": "manual-review", "reason_codes": ["lesson-what-happened-missing"], "revision_proposal": None,
                "notion_read_performed": True}
    current = CurrentLessonEvidence(
        lesson_id=lesson.lesson_id,
        source_revision=lesson.source_revision,
        title=lesson.title,
        ecosystem=lesson.ecosystem,
        capability_kind=lesson.capability_kind,
        what_happened=what_happened,
        what_to_do_next_time=lesson.what_to_do_next_time,
        guardrail=lesson.guardrail,
        canonical_github_refs=lesson.canonical_github_refs,
        evidence_refs=lesson.evidence_refs,
        origin_refs=lesson.canonical_github_refs or lesson.evidence_refs,
        keywords=lesson.keywords,
        library_name=lesson.library_name,
        currentness=lesson.currentness,
        surface_before_work=lesson.surface_before_work,
    )
    result = evaluate_lesson_enrichment(current, request["evidence"])
    proposal = result.proposal
    if proposal is None:
        return {"status": result.disposition.value, "reason_codes": list(result.reason_codes),
                "revision_proposal": None, "notion_read_performed": True}
    before = {"Lesson Learned": current.title, "What Happened": current.what_happened,
              "What To Do Next Time": current.what_to_do_next_time, "Guardrail": current.guardrail}
    after = {"Lesson Learned": proposal.title, "What Happened": proposal.what_happened,
             "What To Do Next Time": proposal.what_to_do_next_time, "Guardrail": proposal.guardrail}
    changed = {name: value for name, value in after.items() if value != before[name]}
    return {
        "status": result.disposition.value,
        "reason_codes": list(result.reason_codes),
        "revision_proposal": {
            "lesson_id": current.lesson_id,
            "expected_revision": current.source_revision,
            "receipt_refs": list(request["receipt_refs"]),
            "new_supporting_refs": list(proposal.new_supporting_refs),
            "supersedes": list(proposal.supersedes),
            "surface_before_work_after": proposal.surface_before_work,
            # Reviewed update entry for the #3417 writer; empty when no
            # narrative change is justified (e.g. confirming evidence only).
            "catalog_entry_draft": (
                {"target_lesson_id": current.lesson_id, "properties": changed} if changed else None
            ),
            **_NO_AUTHORITY,
        },
        "notion_read_performed": True,
    }


# --------------------------------------------------------------- receipts

RECEIPT_MARKER = "<!-- agent-os-lesson-receipt:v1 -->"
RECEIPT_FIELDS = frozenset({
    "ckr6_result_comment_id", "lesson_id", "source_revision", "task_ref",
    "disposition", "reason_code", "decision", "outcome_ref",
})
APPLIED_REASONS = frozenset({
    "guided-decision", "prevented-known-failure", "confirmed-existing-approach",
})
SKIPPED_REASONS = frozenset({
    "not-relevant-to-task", "superseded-by-current-github-authority",
    "guidance-outdated", "guidance-ineffective", "conflicts-with-canonical-rule",
})
REFINEMENT_SIGNAL_REASONS = frozenset({"guidance-outdated", "guidance-ineffective"})
MAX_DECISION = 256


def _canonical(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def validate_receipt_shape(receipt: object) -> dict[str, object]:
    if not isinstance(receipt, Mapping) or set(receipt) != RECEIPT_FIELDS:
        raise ValueError("receipt fields must match the bounded contract")
    result_id = receipt["ckr6_result_comment_id"]
    if type(result_id) is not int or result_id < 1:
        raise ValueError("receipt ckr6_result_comment_id must be a positive integer")
    if type(receipt["lesson_id"]) is not str or LESSON_ID.fullmatch(receipt["lesson_id"]) is None:
        raise ValueError("receipt lesson_id must be a canonical Lesson ID")
    _text(receipt["source_revision"], "source_revision")
    if type(receipt["task_ref"]) is not str or GITHUB_URL.fullmatch(receipt["task_ref"]) is None:
        raise ValueError("receipt task_ref must be a canonical issue or PR URL")
    disposition, reason = receipt["disposition"], receipt["reason_code"]
    allowed = {"applied": APPLIED_REASONS, "skipped": SKIPPED_REASONS}.get(disposition)
    if allowed is None or reason not in allowed:
        raise ValueError("receipt disposition/reason_code must be finite")
    _text(receipt["decision"], "decision", MAX_DECISION)
    outcome = receipt["outcome_ref"]
    if outcome is not None and (type(outcome) is not str or GITHUB_URL.fullmatch(outcome) is None):
        raise ValueError("receipt outcome_ref must be null or a canonical issue or PR URL")
    return dict(receipt)


def serialize_receipt_comment(receipt: Mapping[str, object]) -> str:
    return RECEIPT_MARKER + "\n" + _canonical(validate_receipt_shape(receipt))


def parse_receipt_comment(body: object) -> dict[str, object]:
    if type(body) is not str or not body.startswith(RECEIPT_MARKER + "\n"):
        raise ValueError("comment is not a lesson receipt")
    lines = body.split("\n")
    # Tolerate only the documented host attribution trailer after the JSON.
    serialized = lines[1]
    rest = "\n".join(lines[2:]).strip()
    if rest and rest != "---\n_Generated by [Claude Code](https://claude.ai/code)_":
        raise ValueError("lesson receipt must contain exactly one JSON line")
    payload = json.loads(serialized)
    if not isinstance(payload, dict) or _canonical(payload) != serialized:
        raise ValueError("lesson receipt must be canonical compact JSON")
    return validate_receipt_shape(payload)


def receipt_key(receipt: Mapping[str, object]) -> tuple[object, ...]:
    """Idempotency key: the same use of the same lesson on the same task."""
    return (receipt["ckr6_result_comment_id"], receipt["lesson_id"],
            receipt["source_revision"], receipt["task_ref"])


def verify_receipt_against_result(
    receipt: Mapping[str, object], result: Mapping[str, object], *, result_comment_id: int
) -> str | None:
    """Return None when valid, else one finite invalidity reason.

    Valid only when the referenced CKR6 result actually returned this exact
    (lesson_id, source_revision) as a selected lesson.
    """
    if receipt["ckr6_result_comment_id"] != result_comment_id:
        return "receipt-result-reference-mismatch"
    if result.get("status") != "sufficient":
        return "receipt-result-not-sufficient"
    selected = result.get("selected_lessons")
    if type(selected) is not list:
        return "receipt-result-lacks-revision-provenance"
    pairs = {(item.get("lesson_id"), item.get("source_revision")) for item in selected if isinstance(item, Mapping)}
    if (receipt["lesson_id"], receipt["source_revision"]) not in pairs:
        return "receipt-lesson-not-returned-by-ckr6"
    return None


# ------------------------------------------- receipt verification barrier (H1)
#
# A receipt reference is only an identifier. Before CKR7 may evaluate a
# refinement, every cited receipt must be fetched by exact comment id through
# the trusted read-only GitHub path (ckr6_github_reader), proven unedited and
# owner-authored at the claimed issue/PR location, strictly parsed, and bound
# to a trusted CKR6 result (consume_ckr6_result_comment) that selected the
# same (lesson_id, source_revision). A malformed second receipt is never
# excused by one valid receipt; a caller-supplied body or parsed record is
# never a fallback. No write, no new credential or permission scope: the read
# consumes the token the host already provides to its read path.

# Receipts are owner-authored claims of observed use, posted by the same
# allowed actor the CKR6 ingress admits. The CKR6 *result* author stays the
# GitHub Actions bot (ckr6_github_bridge.CKR6_PRODUCER_*); an owner receipt is
# not required to be bot-authored, and a bot receipt is not owner evidence.
TRUSTED_RECEIPT_AUTHOR = "Blummer92"

_RECEIPT_HTML_REF = re.compile(
    r"https://github\.com/Blummer92/agent-os/(issues|pull)/([1-9][0-9]{0,6})#issuecomment-([1-9][0-9]{0,14})"
)
_RECEIPT_API_REF = re.compile(
    r"https://api\.github\.com/repos/Blummer92/agent-os/issues/comments/([1-9][0-9]{0,14})"
)
_ISSUE_API_URL = re.compile(
    r"https://api\.github\.com/repos/Blummer92/agent-os/issues/([1-9][0-9]{0,6})"
)
# Only operations that SELECT lessons can support a use receipt.
_RECEIPT_RESULT_OPERATIONS = frozenset({"issue-start", "failed-repair"})


class ReceiptEvidenceInvalid(ValueError):
    """One finite receipt-barrier stop; never carries provider or token detail."""

    def __init__(self, reason_code: str, *, manual_review: bool = False) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.manual_review = manual_review


def _receipt_barrier_stop(reason_code: str, *, manual_review: bool) -> dict[str, object]:
    return {
        "status": "manual-review" if manual_review else "rejected",
        "reason_codes": [reason_code],
        "revision_proposal": None,
        # The barrier stops before the known-ID lesson read; report that
        # truthfully instead of the historical unconditional true.
        "notion_read_performed": False,
    }


def _installed_comment_fetch() -> CommentFetch | None:
    """The host-installed trusted reader, or None when this surface is unbound."""
    reader = get_github_issue_comment_reader()
    if reader is None:
        return None

    def fetch(comment_id: int) -> Mapping[str, Any]:
        return reader.read_issue_comment(GITHUB_REPOSITORY, comment_id)

    return fetch


def receipt_comment_id(ref: str) -> int:
    """Exact comment id named by either canonical receipt URL form."""
    match = _RECEIPT_HTML_REF.fullmatch(ref)
    if match is not None:
        return int(match.group(3))
    return int(_RECEIPT_API_REF.fullmatch(ref).group(1))


def _fetch_comment_record(fetch: CommentFetch, comment_id: int) -> Mapping[str, Any]:
    try:
        record = fetch(comment_id)
    except GitHubIssueCommentReadUnavailable as exc:
        if exc.reason_code == "HOST_READ_PATH_UNAVAILABLE":
            raise ReceiptEvidenceInvalid("receipt-read-unavailable", manual_review=True) from None
        if "HTTP 404" in getattr(exc, "detail", ""):
            raise ReceiptEvidenceInvalid("receipt-comment-not-found") from None
        raise ReceiptEvidenceInvalid("receipt-read-failed", manual_review=True) from None
    except ReceiptEvidenceInvalid:
        raise
    except Exception:
        # A transport shim failure is an unavailable read, never evidence.
        raise ReceiptEvidenceInvalid("receipt-read-failed", manual_review=True) from None
    if not isinstance(record, Mapping):
        raise ReceiptEvidenceInvalid("receipt-read-failed", manual_review=True)
    return record


def _record_issue_number(record: Mapping[str, Any], *, reason_code: str) -> int:
    issue_url = record.get("issue_url")
    match = _ISSUE_API_URL.fullmatch(issue_url) if type(issue_url) is str else None
    if match is None:
        raise ReceiptEvidenceInvalid(reason_code)
    return int(match.group(1))


def _record_unedited(record: Mapping[str, Any], *, reason_code: str) -> None:
    created = record.get("created_at")
    if type(created) is not str or not created.strip():
        raise ReceiptEvidenceInvalid(reason_code)
    updated = record.get("updated_at")
    if updated is not None and updated != created:
        raise ReceiptEvidenceInvalid(reason_code)


def _receipt_record(ref: str, record: Mapping[str, Any]) -> dict[str, object]:
    """Validate the server-supplied receipt record and strictly parse its body."""
    comment_id = receipt_comment_id(ref)
    if record.get("id") != comment_id:
        raise ReceiptEvidenceInvalid("receipt-location-mismatch")
    user = record.get("user")
    if not isinstance(user, Mapping) or user.get("login") != TRUSTED_RECEIPT_AUTHOR:
        raise ReceiptEvidenceInvalid("receipt-author-untrusted")
    issue_number = _record_issue_number(record, reason_code="receipt-location-mismatch")
    html_url = record.get("html_url")
    html = _RECEIPT_HTML_REF.fullmatch(ref)
    if html is not None:
        # The HTML form names kind, number and id; the server record must
        # reproduce it exactly. A cross-issue or cross-kind anchor is refused.
        if html_url != ref or int(html.group(2)) != issue_number:
            raise ReceiptEvidenceInvalid("receipt-location-mismatch")
    else:
        if type(html_url) is not str or _RECEIPT_HTML_REF.fullmatch(html_url) is None:
            raise ReceiptEvidenceInvalid("receipt-location-mismatch")
        located = _RECEIPT_HTML_REF.fullmatch(html_url)
        if int(located.group(2)) != issue_number or int(located.group(3)) != comment_id:
            raise ReceiptEvidenceInvalid("receipt-location-mismatch")
    _record_unedited(record, reason_code="receipt-comment-edited")
    try:
        return parse_receipt_comment(record.get("body"))
    except (TypeError, ValueError):
        # Never strip a trailing backtick or normalize the comment body.
        raise ReceiptEvidenceInvalid("receipt-parse-invalid") from None


def _trusted_result_for_receipt(receipt: Mapping[str, object], fetch: CommentFetch) -> Mapping[str, object]:
    """Fetch and authenticate the CKR6 result the receipt claims answered it."""
    result_id = receipt["ckr6_result_comment_id"]
    record = _fetch_comment_record(fetch, result_id)
    if record.get("id") != result_id:
        raise ReceiptEvidenceInvalid("receipt-result-untrusted")
    issue_number = _record_issue_number(record, reason_code="receipt-result-untrusted")
    html_url = record.get("html_url")
    if type(html_url) is not str:
        raise ReceiptEvidenceInvalid("receipt-result-untrusted")
    located = _RECEIPT_HTML_REF.fullmatch(html_url)
    if located is None or int(located.group(2)) != issue_number or int(located.group(3)) != result_id:
        raise ReceiptEvidenceInvalid("receipt-result-untrusted")
    target_kind = "pr" if located.group(1) == "pull" else "issue"
    _record_unedited(record, reason_code="receipt-result-untrusted")
    from .ckr6_github_bridge import (
        consume_ckr6_result_comment,
        parse_ckr6_result_comment,
    )

    try:
        payload = parse_ckr6_result_comment(record.get("body"))
    except (TypeError, ValueError):
        raise ReceiptEvidenceInvalid("receipt-result-untrusted") from None
    operation = payload.get("operation")
    if operation not in _RECEIPT_RESULT_OPERATIONS:
        raise ReceiptEvidenceInvalid("receipt-result-untrusted")
    request_id = payload.get("request_comment_id")
    if type(request_id) is not int or isinstance(request_id, bool) or request_id < 1:
        raise ReceiptEvidenceInvalid("receipt-result-untrusted")
    request_record = _fetch_comment_record(fetch, request_id)
    # The fetched request record must be the exact comment the result names:
    # same defense-in-depth id check the receipt and result records get.
    if request_record.get("id") != request_id:
        raise ReceiptEvidenceInvalid("receipt-result-untrusted")
    if _record_issue_number(request_record, reason_code="receipt-result-untrusted") != issue_number:
        raise ReceiptEvidenceInvalid("receipt-result-untrusted")
    request_created = request_record.get("created_at")
    if type(request_created) is not str or not request_created.strip():
        raise ReceiptEvidenceInvalid("receipt-result-untrusted")
    attempt_id = payload.get("attempt_id") if operation == "failed-repair" else None
    try:
        return consume_ckr6_result_comment(
            record,
            expected_request_comment_id=request_id,
            expected_request_created_at=request_created,
            expected_issue_number=issue_number,
            expected_repository=GITHUB_REPOSITORY,
            expected_operation=operation,
            expected_attempt_id=attempt_id if type(attempt_id) is str else None,
            expected_target_kind=target_kind,
        )
    except (TypeError, ValueError):
        raise ReceiptEvidenceInvalid("receipt-result-untrusted") from None


def verify_receipt_evidence(request: Mapping[str, Any], fetch: CommentFetch) -> tuple[dict[str, object], ...]:
    """Prove every receipt the refinement cites; return the verified receipts.

    Raises ``ReceiptEvidenceInvalid`` with one finite reason code on the first
    failure. Duplicate references to the same comment collapse; two distinct
    comments carrying the same ``receipt_key`` are conflicting proof and fail
    closed. Every receipt must bind the refinement's exact lesson and source
    revision and carry a disposition that is refinement evidence at all
    (``applied`` use, or ``skipped`` with a refinement-signal reason).
    """
    seen: set[int] = set()
    verified = []
    for ref in request["receipt_refs"]:
        comment_id = receipt_comment_id(ref)
        if comment_id in seen:
            continue
        seen.add(comment_id)
        record = _fetch_comment_record(fetch, comment_id)
        receipt = _receipt_record(ref, record)
        result = _trusted_result_for_receipt(receipt, fetch)
        invalid = verify_receipt_against_result(receipt, result, result_comment_id=receipt["ckr6_result_comment_id"])
        if invalid is not None:
            raise ReceiptEvidenceInvalid(invalid)
        if (
            receipt["lesson_id"] != request["lesson_id"]
            or receipt["source_revision"] != request["source_revision"]
        ):
            raise ReceiptEvidenceInvalid("receipt-lesson-mismatch")
        if receipt["disposition"] != "applied" and receipt["reason_code"] not in REFINEMENT_SIGNAL_REASONS:
            raise ReceiptEvidenceInvalid("receipt-disposition-not-refinement-evidence")
        verified.append(receipt)
    keys = [receipt_key(receipt) for receipt in verified]
    if len(set(keys)) != len(keys):
        raise ReceiptEvidenceInvalid("receipt-key-conflict")
    return tuple(verified)
