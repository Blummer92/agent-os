"""Versioned lesson-applicability contract, fail-closed validation, and
shadow-only evaluation (CKR PR-2).

This module is a foundation only. It introduces NO production recommendation
algorithm, NO production ranking change, and NO live lesson selection path:
nothing in this repository imports :func:`describe_applicability_match` from
a production request path, and the production registry is empty and inactive.

Owner decisions still outstanding (see ``OWNER_DECISIONS_PENDING`` and the
PR-2 evidence package):

* the complete failure-mechanism vocabulary is NOT approved;
* the final production-boundary / protected-invariant namespace is NOT
  approved;
* the registry storage location, governance, and reviewer identity are NOT
  approved.

Consequences, enforced in code:

* :func:`validate_registry` takes its mechanism/boundary vocabulary as an
  explicit caller argument. The default vocabulary is EMPTY, so with no
  approved vocabulary every non-empty record is rejected as
  ``unknown-mechanism`` / ``unknown-boundary``. Test fixtures pass explicit
  test-only vocabularies; those IDs are never production values.
* A reviewer name or GitHub URL carried in a registry JSON file is NOT
  independent verification of review authority. Review is a claim recorded
  in the file; PR-2 adds no reviewer-authentication path.
* Evidence carried in a registry file is a provenance CLAIM, never a
  verified observation. Serialized evidence that asserts
  ``acquisition == "trusted"`` is rejected
  (``trusted-provenance-requires-authenticated-acquisition``): a JSON file
  cannot authenticate provenance. Verified observations exist only as
  in-process :class:`VerifiedObservation` values, which no PR-2 code path
  constructs from caller JSON; the trusted acquisition path that would
  construct them in production is NOT implemented in PR-2.
* The shadow evaluator is pure and offline: no network, GitHub, Notion, or
  spreadsheet I/O, no live CI/ledger ingestion, and no authority is granted
  by a match. A shadow ``matched=True`` is an explanation of a reviewed
  record against supplied fixtures, not a selection, activation, or
  admission decision.

Production contracts reused by reference (not re-implemented, not edited):

* Lesson identity ``LL-<n>`` and source-revision timestamps follow the
  exact patterns already enforced by the CKR6 refinement envelope
  (``lesson_learning_loop``): ``LL-[1-9][0-9]{0,8}`` and
  ``YYYY-MM-DDTHH:MM:SS(.mmm)?Z``.
* Lesson eligibility mirrors ``lesson_activation_bridge.normalize_lesson_row``:
  a lesson is shadow-eligible only when it is not archived, its
  ``Surface Before Work`` flag is true, and its currentness is ``current``.
  The shadow evaluator receives that state through :class:`ShadowLessonState`,
  which the caller populates from production normalization; this module
  never reads a live Notion row itself.
* Candidate text bounds reuse the CKR2/C KR5 discipline: bounded lists,
  bounded identifiers, no truncation, fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Mapping

SCHEMA_V1 = "agent-os/lesson-applicability/v1"
VOCABULARY_VERSION_V1 = "mech-v1"

#: Bounded-list size from the PR-2 architecture package, confirmed against
#: the CKR5/CKR6 bounded-list discipline (MAX_ITEMS = 20 there; the
#: applicability contract is stricter at 8 because each entry is a reviewed
#: claim, not a free-form hint).
MAX_LIST_ENTRIES = 8
#: Maximum characters per applicable identifier (mechanism / boundary / ref).
MAX_IDENTIFIER_CHARS = 64
#: Maximum records in one registry.
MAX_REGISTRY_RECORDS = 200
#: Maximum serialized registry size in bytes.
MAX_REGISTRY_BYTES = 32 * 1024
MAX_TEXT_CHARS = 512
MAX_REVIEWER_CHARS = 128

#: Registry top-level fields. Anything else is an unknown field and fails
#: closed; silently ignoring unknown fields would let a partial or
#: forward-incompatible registry look complete.
_REGISTRY_FIELDS = frozenset({"schema", "vocabulary_version", "records", "partial"})
_RECORD_FIELDS = frozenset({
    "lesson_id", "source_revision", "mechanisms", "invariants",
    "positive_conditions", "negative_conditions", "reviewer",
    "review_reference", "review_status", "evidence",
})
_INVARIANT_FIELDS = frozenset({"boundary_id", "kind"})
_CONDITION_FIELDS = frozenset({"mechanism", "boundary_id"})
_EVIDENCE_FIELDS = frozenset({
    "kind", "reference", "repository", "observation_id", "freshness",
    "acquisition",
})

_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_LESSON_ID = re.compile(r"LL-[1-9][0-9]{0,8}")
_REVISION = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z")
_REVIEW_REFERENCE = re.compile(
    r"https://github\.com/Blummer92/agent-os/(?:issues|pull)/[1-9][0-9]{0,6}"
    r"(?:#[A-Za-z0-9_-]{1,64})?"
)
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_OBSERVATION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")

REVIEW_STATUSES = frozenset({"reviewed", "pending", "rejected"})
INVARIANT_KINDS = frozenset({"production-boundary", "protected-invariant"})
EVIDENCE_KINDS = frozenset({
    "ci-observation", "github-comment", "test-reference", "path-reference",
    "title-text", "prompt-text",
})
EVIDENCE_FRESHNESS = frozenset({"fresh", "stale", "unknown"})
EVIDENCE_ACQUISITION = frozenset({"trusted", "caller-supplied"})
CURRENTNESS_VALUES = frozenset({"current", "stale", "unverifiable"})

OWNER_DECISIONS_PENDING = (
    "complete failure-mechanism vocabulary (mech-v1 contents)",
    "final production-boundary / protected-invariant namespace",
    "registry storage location and governance",
    "reviewer identity and review-authority authentication",
    "trusted evidence-acquisition path for VerifiedObservation",
)


# ---------------------------------------------------------------------------
# Contract types
# ---------------------------------------------------------------------------


def _lesson_identity(lesson_id: object, source_revision: object) -> None:
    if type(lesson_id) is not str or _LESSON_ID.fullmatch(lesson_id) is None:
        raise ValueError("lesson_id must be a canonical lesson ID")
    if type(source_revision) is not str or _REVISION.fullmatch(source_revision) is None:
        raise ValueError("source_revision must be an exact revision timestamp")


@dataclass(frozen=True, slots=True)
class InvariantRef:
    """One registered production-boundary or protected-invariant reference."""

    boundary_id: str
    kind: str  # "production-boundary" | "protected-invariant"

    def __post_init__(self) -> None:
        _identifier(self.boundary_id, "boundary_id")
        if type(self.kind) is not str or self.kind not in INVARIANT_KINDS:
            raise ValueError("kind must be a registered invariant kind")


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """One provenance CLAIM attached to a reviewed record.

    This is a claim recorded by the reviewer, not a verified observation.
    ``acquisition == "trusted"`` is never accepted from serialized data
    (see :func:`validate_registry`); only ``caller-supplied`` claims may
    appear in a registry file.
    """

    kind: str
    reference: str
    repository: str | None = None
    observation_id: str | None = None
    freshness: str = "unknown"
    acquisition: str = "caller-supplied"

    def __post_init__(self) -> None:
        if type(self.kind) is not str or self.kind not in EVIDENCE_KINDS:
            raise ValueError("kind must be a finite evidence kind")
        _bounded_text(self.reference, "reference")
        if self.repository is not None:
            if type(self.repository) is not str or _REPOSITORY.fullmatch(self.repository) is None:
                raise ValueError("repository must be an owner/name pair")
        if self.observation_id is not None:
            if (
                type(self.observation_id) is not str
                or _OBSERVATION_ID.fullmatch(self.observation_id) is None
            ):
                raise ValueError("observation_id is malformed")
        if type(self.freshness) is not str or self.freshness not in EVIDENCE_FRESHNESS:
            raise ValueError("freshness must be a finite evidence freshness")
        if type(self.acquisition) is not str or self.acquisition not in EVIDENCE_ACQUISITION:
            raise ValueError("acquisition must be a finite evidence acquisition")


@dataclass(frozen=True, slots=True)
class ApplicabilityCondition:
    """One positive or negative applicability condition.

    A condition is satisfied by verified observations only. ``boundary_id``
    of ``None`` means the mechanism alone is the condition.
    """

    mechanism: str
    boundary_id: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.mechanism, "mechanism")
        if self.boundary_id is not None:
            _identifier(self.boundary_id, "boundary_id")


@dataclass(frozen=True, slots=True)
class ApplicabilityRecord:
    """One reviewed, source-revision-bound applicability annotation.

    The record binds a stable lesson ID to the EXACT lesson source revision
    it was reviewed against. Editing the lesson revision invalidates the
    annotation; the validator and the shadow evaluator both enforce that.
    """

    lesson_id: str
    source_revision: str
    mechanisms: tuple[str, ...]
    invariants: tuple[InvariantRef, ...]
    positive_conditions: tuple[ApplicabilityCondition, ...]
    negative_conditions: tuple[ApplicabilityCondition, ...]
    reviewer: str
    review_reference: str
    review_status: str
    evidence: tuple[EvidenceRef, ...] = ()

    def __post_init__(self) -> None:
        _lesson_identity(self.lesson_id, self.source_revision)
        _bounded_tuple(self.mechanisms, "mechanisms", _identifier)
        if not self.mechanisms:
            raise ValueError("mechanisms must be non-empty")
        if len(set(self.mechanisms)) != len(self.mechanisms):
            raise ValueError("mechanisms must be unique")
        _bounded_tuple(self.invariants, "invariants", _invariant)
        if len({item.boundary_id for item in self.invariants}) != len(self.invariants):
            raise ValueError("invariants must be unique by boundary_id")
        _bounded_tuple(self.positive_conditions, "positive_conditions", _condition)
        if not self.positive_conditions:
            raise ValueError("positive_conditions must be non-empty")
        _bounded_tuple(self.negative_conditions, "negative_conditions", _condition)
        positive_keys = {
            (item.mechanism, item.boundary_id) for item in self.positive_conditions
        }
        negative_keys = {
            (item.mechanism, item.boundary_id) for item in self.negative_conditions
        }
        if len(positive_keys) != len(self.positive_conditions):
            raise ValueError("positive_conditions must be unique")
        if len(negative_keys) != len(self.negative_conditions):
            raise ValueError("negative_conditions must be unique")
        if positive_keys & negative_keys:
            raise ValueError("positive and negative conditions must not overlap")
        _bounded_text(self.reviewer, "reviewer", MAX_REVIEWER_CHARS)
        if (
            type(self.review_reference) is not str
            or _REVIEW_REFERENCE.fullmatch(self.review_reference) is None
        ):
            raise ValueError("review_reference must be a canonical GitHub URL")
        if type(self.review_status) is not str or self.review_status not in REVIEW_STATUSES:
            raise ValueError("review_status must be a finite review status")
        _bounded_tuple(self.evidence, "evidence", _evidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lesson_id": self.lesson_id,
            "source_revision": self.source_revision,
            "mechanisms": list(self.mechanisms),
            "invariants": [
                {"boundary_id": item.boundary_id, "kind": item.kind}
                for item in self.invariants
            ],
            "positive_conditions": [
                {"mechanism": item.mechanism, "boundary_id": item.boundary_id}
                for item in self.positive_conditions
            ],
            "negative_conditions": [
                {"mechanism": item.mechanism, "boundary_id": item.boundary_id}
                for item in self.negative_conditions
            ],
            "reviewer": self.reviewer,
            "review_reference": self.review_reference,
            "review_status": self.review_status,
            "evidence": [
                {
                    "kind": item.kind,
                    "reference": item.reference,
                    "repository": item.repository,
                    "observation_id": item.observation_id,
                    "freshness": item.freshness,
                    "acquisition": item.acquisition,
                }
                for item in self.evidence
            ],
        }


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Fail-closed outcome of :func:`validate_registry`.

    On any rejection ``records`` is empty: a partially valid registry is
    never returned as usable records. ``complete`` is true only for a fully
    valid, non-partial registry.
    """

    valid: bool
    complete: bool
    reason_codes: tuple[str, ...]
    records: tuple[ApplicabilityRecord, ...]
    record_count: int
    schema: str | None
    vocabulary_version: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "complete": self.complete,
            "reason_codes": list(self.reason_codes),
            "records": [item.to_dict() for item in self.records],
            "record_count": self.record_count,
            "schema": self.schema,
            "vocabulary_version": self.vocabulary_version,
        }


@dataclass(frozen=True, slots=True)
class ShadowLessonState:
    """Production lesson state for the shadow evaluator, supplied by the caller.

    Populate from production normalization
    (``lesson_activation_bridge.normalize_lesson_row``): ``archived`` from
    the lesson Status, ``surface_before_work`` from the Surface Before Work
    checkbox, ``currentness`` from the CKR2 currentness contract, and
    ``source_revision`` from the verified ``last_edited_time``. This module
    never reads a live row itself.
    """

    lesson_id: str
    source_revision: str
    title: str
    archived: bool
    surface_before_work: bool
    currentness: str  # "current" | "stale" | "unverifiable"

    def __post_init__(self) -> None:
        _lesson_identity(self.lesson_id, self.source_revision)
        _bounded_text(self.title, "title")
        if type(self.archived) is not bool or type(self.surface_before_work) is not bool:
            raise TypeError("archived and surface_before_work must be bool")
        if type(self.currentness) is not str or self.currentness not in CURRENTNESS_VALUES:
            raise ValueError("currentness must be a finite currentness value")


@dataclass(frozen=True, slots=True)
class TaskEvidence:
    """Source-qualified task evidence offered to the shadow evaluator.

    Everything here is a caller CLAIM except the separately supplied
    verified observations. Claimed mechanisms, claimed boundaries, and
    static-inferred references can never satisfy a condition on their own;
    they are reported as ignored claims when no verified observation
    supports them.
    """

    task_reference: str
    repository: str = "Blummer92/agent-os"
    claimed_mechanisms: tuple[str, ...] = ()
    claimed_boundaries: tuple[str, ...] = ()
    static_inferred_refs: tuple[str, ...] = ()
    task_title: str | None = None

    def __post_init__(self) -> None:
        if (
            type(self.task_reference) is not str
            or _REVIEW_REFERENCE.fullmatch(self.task_reference) is None
        ):
            raise ValueError("task_reference must be a canonical GitHub URL")
        if type(self.repository) is not str or _REPOSITORY.fullmatch(self.repository) is None:
            raise ValueError("repository must be an owner/name pair")
        _bounded_tuple(self.claimed_mechanisms, "claimed_mechanisms", _identifier)
        _bounded_tuple(self.claimed_boundaries, "claimed_boundaries", _identifier)
        for ref in self.static_inferred_refs:
            _bounded_text(ref, "static_inferred_refs")
        if type(self.static_inferred_refs) is not tuple:
            raise TypeError("static_inferred_refs must be a tuple")
        if self.task_title is not None:
            _bounded_text(self.task_title, "task_title")


@dataclass(frozen=True, slots=True)
class VerifiedObservation:
    """One independently authenticated observation, supplied in-process.

    PR-2 has NO trusted acquisition path that constructs this type from
    caller JSON, a CI payload, or a spreadsheet row. Test fixtures
    construct it directly to exercise matching logic; a production caller
    must obtain it from the future authenticated acquisition path (an
    outstanding owner decision). Treating an arbitrary JSON evidence object
    as a ``VerifiedObservation`` is a programming error, not a supported
    conversion: there is deliberately no ``from_dict`` constructor.
    """

    mechanism: str
    boundary_id: str | None
    observation_id: str
    repository: str
    freshness: str  # only "fresh" observations can satisfy a condition

    def __post_init__(self) -> None:
        _identifier(self.mechanism, "mechanism")
        if self.boundary_id is not None:
            _identifier(self.boundary_id, "boundary_id")
        if (
            type(self.observation_id) is not str
            or _OBSERVATION_ID.fullmatch(self.observation_id) is None
        ):
            raise ValueError("observation_id is malformed")
        if type(self.repository) is not str or _REPOSITORY.fullmatch(self.repository) is None:
            raise ValueError("repository must be an owner/name pair")
        if type(self.freshness) is not str or self.freshness not in EVIDENCE_FRESHNESS:
            raise ValueError("freshness must be a finite evidence freshness")


@dataclass(frozen=True, slots=True)
class ApplicabilityMatch:
    """Deterministic, traceable shadow-evaluation outcome.

    ``matched=True`` means only that a reviewed record's conditions are
    satisfied by the supplied verified observations for the supplied lesson
    state. It selects nothing, activates nothing, admits nothing, and
    grants no authority.
    """

    matched: bool
    reason_codes: tuple[str, ...]
    explanation: str
    verified_mechanisms: tuple[str, ...]
    verified_boundaries: tuple[str, ...]
    confidence: str  # "verified" when matched, otherwise "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "matched": self.matched,
            "reason_codes": list(self.reason_codes),
            "explanation": self.explanation,
            "verified_mechanisms": list(self.verified_mechanisms),
            "verified_boundaries": list(self.verified_boundaries),
            "confidence": self.confidence,
        }


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------


def empty_registry_dict() -> dict[str, Any]:
    """The valid, versioned, empty production registry (no records)."""
    return {
        "schema": SCHEMA_V1,
        "vocabulary_version": VOCABULARY_VERSION_V1,
        "records": [],
    }


def serialize_registry(records: tuple[ApplicabilityRecord, ...]) -> dict[str, Any]:
    """Serialize validated records into the versioned registry shape."""
    if type(records) is not tuple or any(
        type(item) is not ApplicabilityRecord for item in records
    ):
        raise TypeError("records must be a tuple of ApplicabilityRecord values")
    return {
        "schema": SCHEMA_V1,
        "vocabulary_version": VOCABULARY_VERSION_V1,
        "records": [item.to_dict() for item in records],
    }


# ---------------------------------------------------------------------------
# Fail-closed validation
# ---------------------------------------------------------------------------


def validate_registry(
    obj: Any,
    *,
    mechanisms: frozenset[str] = frozenset(),
    boundaries: frozenset[str] = frozenset(),
    current_revisions: Mapping[str, str] | None = None,
) -> ValidationResult:
    """Validate a parsed registry object without I/O and without raising
    for expected malformed external data.

    ``mechanisms`` / ``boundaries`` are the approved closed vocabularies
    supplied by the caller; the default is EMPTY (no approved vocabulary),
    so any record naming a mechanism or boundary is rejected until the
    owner approves the vocabulary. ``current_revisions`` optionally maps
    lesson ID to its currently verified source revision; a record bound to
    any other revision is stale and rejected.

    Malformed external data yields an explicit invalid
    :class:`ValidationResult`; it never raises and never yields usable
    records. Programmer errors (a non-string vocabulary entry, a
    non-mapping ``current_revisions``) raise :class:`TypeError`.
    """
    vocabulary_mechanisms = _vocabulary(mechanisms, "mechanisms")
    vocabulary_boundaries = _vocabulary(boundaries, "boundaries")
    revisions: Mapping[str, str] = {}
    if current_revisions is not None:
        if not isinstance(current_revisions, Mapping):
            raise TypeError("current_revisions must be a mapping or None")
        for key, value in current_revisions.items():
            if type(key) is not str or type(value) is not str:
                raise TypeError("current_revisions must map strings to strings")
        revisions = current_revisions

    reasons: set[str] = set()
    schema: str | None = None
    vocabulary_version: str | None = None
    record_count = 0

    if not isinstance(obj, Mapping):
        return _invalid(("malformed-registry",), 0, None, None)
    unknown_top = set(obj) - _REGISTRY_FIELDS
    if unknown_top:
        reasons.add("unknown-registry-field")
    schema = obj.get("schema") if type(obj.get("schema")) is str else None
    if schema != SCHEMA_V1:
        reasons.add("unknown-schema-version")
    vocabulary_version = (
        obj.get("vocabulary_version")
        if type(obj.get("vocabulary_version")) is str
        else None
    )
    if vocabulary_version != VOCABULARY_VERSION_V1:
        reasons.add("unsupported-vocabulary-version")
    partial = obj.get("partial", False)
    if type(partial) is not bool:
        reasons.add("malformed-registry")
        partial = True
    if partial:
        reasons.add("partial-registry")
    raw_records = obj.get("records")
    if raw_records is None:
        reasons.add("partial-registry")
        raw_records = []
    if type(raw_records) is not list:
        reasons.add("malformed-registry")
        raw_records = []
    record_count = len(raw_records)
    if record_count > MAX_REGISTRY_RECORDS:
        reasons.add("registry-record-budget-exceeded")
    try:
        serialized = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError):
        return _invalid(
            tuple(sorted(reasons | {"malformed-registry"})),
            record_count, schema, vocabulary_version,
        )
    if len(serialized.encode("utf-8")) > MAX_REGISTRY_BYTES:
        reasons.add("registry-oversized")

    records: list[ApplicabilityRecord] = []
    seen_ids: dict[str, ApplicabilityRecord] = {}
    for raw in raw_records:
        record, record_reasons = _validate_record(
            raw, vocabulary_mechanisms, vocabulary_boundaries, revisions
        )
        reasons |= record_reasons
        if record is None:
            continue
        previous = seen_ids.get(record.lesson_id)
        if previous is not None:
            reasons.add("duplicate-lesson-identity")
            if previous != record:
                reasons.add("conflicting-lesson-record")
            continue
        seen_ids[record.lesson_id] = record
        records.append(record)

    if reasons:
        return _invalid(tuple(sorted(reasons)), record_count, schema, vocabulary_version)
    return ValidationResult(
        valid=True,
        complete=True,
        reason_codes=(),
        records=tuple(records),
        record_count=record_count,
        schema=schema,
        vocabulary_version=vocabulary_version,
    )


def _invalid(
    reasons: tuple[str, ...],
    record_count: int,
    schema: str | None,
    vocabulary_version: str | None,
) -> ValidationResult:
    return ValidationResult(
        valid=False,
        complete=False,
        reason_codes=tuple(sorted(set(reasons))),
        records=(),
        record_count=record_count,
        schema=schema,
        vocabulary_version=vocabulary_version,
    )


def _validate_record(
    raw: Any,
    vocabulary_mechanisms: frozenset[str],
    vocabulary_boundaries: frozenset[str],
    revisions: Mapping[str, str],
) -> tuple[ApplicabilityRecord | None, set[str]]:
    reasons: set[str] = set()
    if not isinstance(raw, Mapping):
        return None, {"malformed-record"}
    unknown = set(raw) - _RECORD_FIELDS
    if unknown:
        reasons.add("unknown-record-field")
    lesson_id = raw.get("lesson_id")
    if lesson_id is None or (type(lesson_id) is str and not lesson_id.strip()):
        reasons.add("missing-lesson-identity")
    elif type(lesson_id) is not str or _LESSON_ID.fullmatch(lesson_id) is None:
        reasons.add("malformed-lesson-identity")
    revision = raw.get("source_revision")
    if revision is None or (type(revision) is str and not revision.strip()):
        reasons.add("missing-lesson-revision")
    elif type(revision) is not str or _REVISION.fullmatch(revision) is None:
        reasons.add("malformed-lesson-revision")
    elif (
        type(lesson_id) is str
        and lesson_id in revisions
        and revisions[lesson_id] != revision
    ):
        reasons.add("stale-lesson-revision")
    reviewer = raw.get("reviewer")
    if reviewer is None or (type(reviewer) is str and not reviewer.strip()):
        reasons.add("missing-reviewer")
    elif type(reviewer) is not str or len(reviewer) > MAX_REVIEWER_CHARS:
        reasons.add("oversized-field")
    review_reference = raw.get("review_reference")
    if review_reference is None or (
        type(review_reference) is str and not review_reference.strip()
    ):
        reasons.add("missing-review-reference")
    elif (
        type(review_reference) is not str
        or _REVIEW_REFERENCE.fullmatch(review_reference) is None
    ):
        reasons.add("malformed-review-reference")
    review_status = raw.get("review_status")
    if review_status is None:
        reasons.add("missing-review-status")
    elif type(review_status) is not str or review_status not in REVIEW_STATUSES:
        reasons.add("malformed-review-status")
    elif review_status != "reviewed":
        reasons.add("unreviewed-record")

    mechanisms, mech_reasons = _validate_identifier_list(
        raw.get("mechanisms"), "mechanisms", vocabulary_mechanisms, "unknown-mechanism"
    )
    reasons |= mech_reasons
    invariants, inv_reasons = _validate_invariants(
        raw.get("invariants"), vocabulary_boundaries
    )
    reasons |= inv_reasons
    positives, pos_reasons = _validate_conditions(
        raw.get("positive_conditions"),
        "positive_conditions",
        vocabulary_mechanisms,
        vocabulary_boundaries,
    )
    reasons |= pos_reasons
    negatives, neg_reasons = _validate_conditions(
        raw.get("negative_conditions"),
        "negative_conditions",
        vocabulary_mechanisms,
        vocabulary_boundaries,
    )
    reasons |= neg_reasons
    if positives is not None and negatives is not None:
        positive_keys = {(item.mechanism, item.boundary_id) for item in positives}
        negative_keys = {(item.mechanism, item.boundary_id) for item in negatives}
        if positive_keys & negative_keys:
            reasons.add("conflicting-applicability-condition")
    if positives is not None and not positives:
        reasons.add("invalid-applicability-condition")
    evidence, ev_reasons = _validate_evidence(raw.get("evidence"))
    reasons |= ev_reasons

    if reasons:
        return None, reasons
    try:
        record = ApplicabilityRecord(
            lesson_id=lesson_id,  # type: ignore[arg-type]
            source_revision=revision,  # type: ignore[arg-type]
            mechanisms=tuple(mechanisms or ()),
            invariants=tuple(invariants or ()),
            positive_conditions=tuple(positives or ()),
            negative_conditions=tuple(negatives or ()),
            reviewer=reviewer,  # type: ignore[arg-type]
            review_reference=review_reference,  # type: ignore[arg-type]
            review_status=review_status,  # type: ignore[arg-type]
            evidence=tuple(evidence or ()),
        )
    except (TypeError, ValueError):
        return None, reasons | {"malformed-record"}
    return record, reasons


def _validate_identifier_list(
    raw: Any,
    field_name: str,
    vocabulary: frozenset[str],
    unknown_code: str,
) -> tuple[list[str] | None, set[str]]:
    reasons: set[str] = set()
    if raw is None:
        return None, {f"missing-{field_name}"}
    if type(raw) is not list:
        return None, {"malformed-record"}
    if len(raw) > MAX_LIST_ENTRIES:
        reasons.add("oversized-field")
    values: list[str] = []
    for item in raw:
        if type(item) is not str or _IDENTIFIER.fullmatch(item) is None:
            reasons.add("malformed-record")
            continue
        if len(item) > MAX_IDENTIFIER_CHARS:
            reasons.add("oversized-field")
            continue
        if item not in vocabulary:
            reasons.add(unknown_code)
            continue
        values.append(item)
    if len(set(values)) != len(values):
        reasons.add("malformed-record")
    return values, reasons


def _validate_invariants(
    raw: Any, vocabulary_boundaries: frozenset[str]
) -> tuple[list[InvariantRef] | None, set[str]]:
    reasons: set[str] = set()
    if raw is None:
        return None, {"missing-invariants"}
    if type(raw) is not list:
        return None, {"malformed-record"}
    if len(raw) > MAX_LIST_ENTRIES:
        reasons.add("oversized-field")
    values: list[InvariantRef] = []
    for item in raw:
        if not isinstance(item, Mapping) or set(item) - _INVARIANT_FIELDS:
            reasons.add("malformed-record")
            continue
        boundary_id = item.get("boundary_id")
        kind = item.get("kind")
        if (
            type(boundary_id) is not str
            or _IDENTIFIER.fullmatch(boundary_id) is None
        ):
            reasons.add("malformed-record")
            continue
        if boundary_id not in vocabulary_boundaries:
            reasons.add("unknown-boundary")
            continue
        if type(kind) is not str or kind not in INVARIANT_KINDS:
            reasons.add("malformed-record")
            continue
        values.append(InvariantRef(boundary_id=boundary_id, kind=kind))
    if len({item.boundary_id for item in values}) != len(values):
        reasons.add("malformed-record")
    return values, reasons


def _validate_conditions(
    raw: Any,
    field_name: str,
    vocabulary_mechanisms: frozenset[str],
    vocabulary_boundaries: frozenset[str],
) -> tuple[list[ApplicabilityCondition] | None, set[str]]:
    reasons: set[str] = set()
    if raw is None:
        return None, {f"missing-{field_name}"}
    if type(raw) is not list:
        return None, {"malformed-record"}
    if len(raw) > MAX_LIST_ENTRIES:
        reasons.add("oversized-field")
    values: list[ApplicabilityCondition] = []
    for item in raw:
        if not isinstance(item, Mapping) or set(item) - _CONDITION_FIELDS:
            reasons.add("invalid-applicability-condition")
            continue
        mechanism = item.get("mechanism")
        boundary_id = item.get("boundary_id")
        if type(mechanism) is not str or _IDENTIFIER.fullmatch(mechanism) is None:
            reasons.add("invalid-applicability-condition")
            continue
        if mechanism not in vocabulary_mechanisms:
            reasons.add("unknown-mechanism")
            continue
        if boundary_id is not None and (
            type(boundary_id) is not str
            or _IDENTIFIER.fullmatch(boundary_id) is None
        ):
            reasons.add("invalid-applicability-condition")
            continue
        if boundary_id is not None and boundary_id not in vocabulary_boundaries:
            reasons.add("unknown-boundary")
            continue
        values.append(ApplicabilityCondition(mechanism=mechanism, boundary_id=boundary_id))
    if len({(item.mechanism, item.boundary_id) for item in values}) != len(values):
        reasons.add("invalid-applicability-condition")
    return values, reasons


def _validate_evidence(raw: Any) -> tuple[list[EvidenceRef] | None, set[str]]:
    reasons: set[str] = set()
    if raw is None:
        return [], set()
    if type(raw) is not list:
        return None, {"malformed-evidence"}
    if len(raw) > MAX_LIST_ENTRIES:
        reasons.add("oversized-field")
    values: list[EvidenceRef] = []
    for item in raw:
        if not isinstance(item, Mapping) or set(item) - _EVIDENCE_FIELDS:
            reasons.add("malformed-evidence")
            continue
        kind = item.get("kind")
        reference = item.get("reference")
        repository = item.get("repository")
        observation_id = item.get("observation_id")
        freshness = item.get("freshness", "unknown")
        acquisition = item.get("acquisition", "caller-supplied")
        if type(kind) is not str or kind not in EVIDENCE_KINDS:
            reasons.add("malformed-evidence")
            continue
        try:
            _bounded_text(reference, "reference")
        except (TypeError, ValueError):
            reasons.add("malformed-evidence")
            continue
        if repository is not None and (
            type(repository) is not str or _REPOSITORY.fullmatch(repository) is None
        ):
            reasons.add("malformed-evidence")
            continue
        if observation_id is not None and (
            type(observation_id) is not str
            or _OBSERVATION_ID.fullmatch(observation_id) is None
        ):
            reasons.add("malformed-evidence")
            continue
        if type(freshness) is not str or freshness not in EVIDENCE_FRESHNESS:
            reasons.add("ambiguous-evidence")
            continue
        if type(acquisition) is not str or acquisition not in EVIDENCE_ACQUISITION:
            reasons.add("malformed-evidence")
            continue
        if acquisition == "trusted":
            # A serialized file cannot authenticate provenance. A claim of
            # trusted acquisition inside registry JSON is rejected, never
            # upgraded into verified evidence.
            reasons.add("trusted-provenance-requires-authenticated-acquisition")
            continue
        values.append(
            EvidenceRef(
                kind=kind,
                reference=reference,
                repository=repository,
                observation_id=observation_id,
                freshness=freshness,
                acquisition=acquisition,
            )
        )
    return values, reasons


# ---------------------------------------------------------------------------
# Pure, offline shadow evaluation
# ---------------------------------------------------------------------------


def describe_applicability_match(
    record: ApplicabilityRecord,
    lesson_state: ShadowLessonState,
    task: TaskEvidence,
    *,
    verified_observations: tuple[VerifiedObservation, ...] = (),
) -> ApplicabilityMatch:
    """Describe whether a reviewed record would match verified task evidence.

    Pure and offline: no I/O of any kind. Only ``verified_observations``
    can satisfy a condition; caller claims, static-inferred references,
    title text, and prompt text are never mechanism evidence. Negative
    conditions dominate positive ones. Deterministic: reason codes and the
    explanation are built from sorted values only.
    """
    if type(record) is not ApplicabilityRecord:
        raise TypeError("record must be an ApplicabilityRecord")
    if type(lesson_state) is not ShadowLessonState:
        raise TypeError("lesson_state must be a ShadowLessonState")
    if type(task) is not TaskEvidence:
        raise TypeError("task must be a TaskEvidence")
    if type(verified_observations) is not tuple or any(
        type(item) is not VerifiedObservation for item in verified_observations
    ):
        raise TypeError("verified_observations must be a tuple of VerifiedObservation values")

    reasons: set[str] = set()
    if record.lesson_id != lesson_state.lesson_id:
        reasons.add("lesson-identity-mismatch")
    if lesson_state.archived:
        reasons.add("lesson-archived")
    if not lesson_state.surface_before_work:
        reasons.add("lesson-not-surfaced-before-work")
    if lesson_state.currentness != "current":
        reasons.add("lesson-not-current")
    if record.source_revision != lesson_state.source_revision:
        reasons.add("stale-lesson-revision")
    if record.review_status != "reviewed":
        reasons.add("unreviewed-record")

    # Verified observations only: fresh, same repository, unique identity.
    # D120 Option A (owner-approved): satisfaction is per-observation. A
    # condition (mechanism, boundary) is satisfied only by ONE observation
    # carrying that mechanism AND that boundary together. The unions below
    # are kept for the explanatory output only; they never satisfy a
    # condition on their own.
    seen_observation_ids: dict[str, VerifiedObservation] = {}
    conflicting_observation_ids: set[str] = set()
    for observation in verified_observations:
        if observation.repository != task.repository:
            reasons.add("conflicting-repository-identity")
            continue
        if observation.freshness == "unknown":
            reasons.add("unknown-evidence-freshness")
            continue
        if observation.freshness != "fresh":
            reasons.add("stale-evidence")
            continue
        observation_id = observation.observation_id
        previous = seen_observation_ids.get(observation_id)
        if previous is not None:
            if previous != observation:
                # A conflicting identity contributes no verified evidence.
                conflicting_observation_ids.add(observation_id)
                reasons.add("conflicting-observation-identity")
            continue
        seen_observation_ids[observation_id] = observation

    # Collect pairs after duplicate checking so neither the match nor its
    # explanation can depend on which conflict arrived first.
    verified_pairs = {
        (observation.mechanism, observation.boundary_id)
        for observation_id, observation in seen_observation_ids.items()
        if observation_id not in conflicting_observation_ids
    }
    verified_mechanisms = {mechanism for mechanism, _ in verified_pairs}
    verified_boundaries = {boundary for _, boundary in verified_pairs if boundary is not None}

    def _satisfied(condition: ApplicabilityCondition) -> bool:
        # D120 Option A: one observation must carry the mechanism and the
        # boundary together. A boundary-less condition needs only one
        # observation carrying the mechanism.
        if condition.boundary_id is None:
            return any(
                mechanism == condition.mechanism
                for mechanism, _ in verified_pairs
            )
        return (condition.mechanism, condition.boundary_id) in verified_pairs

    if not record.positive_conditions:
        reasons.add("no-positive-applicability-condition")
    unsatisfied = [item for item in record.positive_conditions if not _satisfied(item)]
    if unsatisfied:
        reasons.add("positive-applicability-condition-unsatisfied")
    dominated = [item for item in record.negative_conditions if _satisfied(item)]
    if dominated:
        # A satisfied negative condition overrides every positive one.
        reasons.add("negative-applicability-condition")

    if task.claimed_mechanisms or task.claimed_boundaries:
        reasons.add("caller-asserted-evidence-ignored")
    if task.static_inferred_refs:
        reasons.add("static-inferred-link-is-not-verified-detection")

    # A match requires no blocking reason at all. Caller claims and static
    # references are informational only: they never satisfy a condition, so
    # the condition checks above already decided the outcome. Matched iff
    # no reason code is present other than informational claim codes AND
    # every positive condition was satisfied by verified observations AND
    # no negative condition fired.
    informational = {"caller-asserted-evidence-ignored", "static-inferred-link-is-not-verified-detection"}
    blocking = reasons - informational
    matched = (
        not blocking
        and bool(record.positive_conditions)
        and not unsatisfied
        and not dominated
        and bool(verified_mechanisms)
    )
    if not matched and task.task_title is not None and lesson_state.title:
        if _norm(task.task_title) == _norm(lesson_state.title):
            reasons.add("title-echo-is-not-mechanism-evidence")

    ordered_reasons = tuple(sorted(reasons))
    mechanisms = tuple(sorted(verified_mechanisms))
    boundaries = tuple(sorted(verified_boundaries))
    if matched:
        explanation = (
            "shadow-match: reviewed record "
            f"{record.lesson_id}@{record.source_revision} applies; "
            f"verified mechanisms={','.join(mechanisms)}; "
            f"verified boundaries={','.join(boundaries) if boundaries else '-'}; "
            "confidence=verified"
        )
    else:
        explanation = (
            "shadow-no-match: reviewed record "
            f"{record.lesson_id}@{record.source_revision} does not apply; "
            f"reasons={','.join(ordered_reasons)}; "
            f"verified mechanisms={','.join(mechanisms) if mechanisms else '-'}; "
            "confidence=none"
        )
    return ApplicabilityMatch(
        matched=matched,
        reason_codes=ordered_reasons,
        explanation=explanation,
        verified_mechanisms=mechanisms,
        verified_boundaries=boundaries,
        confidence="verified" if matched else "none",
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _vocabulary(value: Any, name: str) -> frozenset[str]:
    if isinstance(value, (frozenset, set, tuple, list)):
        items = list(value)
    else:
        raise TypeError(f"{name} must be a set, frozenset, tuple, or list of strings")
    for item in items:
        if type(item) is not str:
            raise TypeError(f"{name} must contain only strings")
    return frozenset(items)


def _identifier(value: object, name: str) -> None:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{name} must be a bounded lowercase identifier")
    if len(value) > MAX_IDENTIFIER_CHARS:
        raise ValueError(f"{name} is oversized")


def _bounded_text(value: object, name: str, maximum: int = MAX_TEXT_CHARS) -> None:
    if type(value) is not str:
        raise TypeError(f"{name} must be a string")
    if not value.strip():
        raise ValueError(f"{name} must be non-empty")
    if len(value) > maximum:
        raise ValueError(f"{name} is oversized")
    if any(ord(char) < 32 and char != "\t" for char in value):
        raise ValueError(f"{name} contains control characters")


def _bounded_tuple(value: object, name: str, check: Any) -> None:
    if type(value) is not tuple:
        raise TypeError(f"{name} must be a tuple")
    if len(value) > MAX_LIST_ENTRIES:
        raise ValueError(f"{name} is oversized")
    for item in value:
        check(item, name)


def _invariant(value: object, name: str) -> None:
    if type(value) is not InvariantRef:
        raise TypeError(f"{name} must contain InvariantRef values")


def _condition(value: object, name: str) -> None:
    if type(value) is not ApplicabilityCondition:
        raise TypeError(f"{name} must contain ApplicabilityCondition values")


def _evidence(value: object, name: str) -> None:
    if type(value) is not EvidenceRef:
        raise TypeError(f"{name} must contain EvidenceRef values")


def _norm(value: str) -> str:
    return " ".join(value.split()).casefold()
