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

ReadExecutor = Callable[[Mapping[str, Any]], Mapping[str, Any]]

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
    "root_cause_or_diagnosis",
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


def capture_lesson_candidate(payload: Mapping[str, Any]) -> dict[str, object]:
    """Producer -> CKR5 -> projection -> reviewable catalog draft. Writes nothing."""
    outcome = parse_candidate(payload)
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
            "catalog_fields_over_limit": over,
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


def propose_lesson_refinement(payload: Mapping[str, Any], execute_read: ReadExecutor) -> dict[str, object]:
    """Exact current lesson + receipt-linked evidence -> CKR7 proposal. Writes nothing."""
    request = parse_refinement(payload)
    raw = execute_read(build_known_reference_query([request["lesson_id"]]))
    rows = raw.get("results") if isinstance(raw, Mapping) else None
    if type(rows) is not list:
        return {"status": "manual-review", "reason_codes": ["lesson-read-malformed"], "revision_proposal": None}
    matches = []
    for row in rows[:5]:
        normalized = normalize_lesson_row(row) if isinstance(row, Mapping) else None
        if isinstance(normalized, LessonActivationSkip) and normalized.lesson_id == request["lesson_id"]:
            return {"status": "manual-review", "reason_codes": ["lesson-not-normalizable:" + normalized.reason],
                    "revision_proposal": None}
        if normalized is not None and not isinstance(normalized, LessonActivationSkip) and normalized.lesson_id == request["lesson_id"]:
            matches.append((row, normalized))
    if len(matches) != 1:
        return {"status": "manual-review", "reason_codes": ["lesson-identity-not-unique" if matches else "lesson-not-found"],
                "revision_proposal": None}
    row, lesson = matches[0]
    if lesson.source_revision != request["source_revision"]:
        # Never refine from stale text; the proposal must bind the live revision.
        return {"status": "rejected", "reason_codes": ["stale-lesson-revision"], "revision_proposal": None}
    what_happened = _what_happened(row)
    if what_happened is None:
        return {"status": "manual-review", "reason_codes": ["lesson-what-happened-missing"], "revision_proposal": None}
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
                "revision_proposal": None}
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
