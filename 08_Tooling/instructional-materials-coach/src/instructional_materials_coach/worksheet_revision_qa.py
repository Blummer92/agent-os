"""Rendered-QA revision gate for student worksheets: required visual scaffolds survive revisions.

A teacher-directed revision (vocabulary fix, content tweak, layout repair) must
not silently drop required visual roles declared by the prior revision. The
artifact-first response standard already requires render QA to verify presence
of required visual components; this module binds that contract across
revisions: the revised source must carry forward every prior required role
unless the teacher or governing source explicitly removed it.

This module is pure repository-side QA. It performs no rendering, retrieval,
provider call, or external-system mutation.
"""
from __future__ import annotations

import dataclasses
import hashlib
import re
from dataclasses import dataclass
from typing import Literal

from .visual_completeness import validate_visual_completeness

RevisionVisualSeverity = Literal["fail", "manual-review"]


class WorksheetRevisionQAError(ValueError):
    """Fail-closed error for malformed worksheet revision QA inputs."""


@dataclass(frozen=True)
class WorksheetRevisionVisualFinding:
    code: str
    severity: RevisionVisualSeverity
    message: str


@dataclass(frozen=True)
class WorksheetRevisionVisualResult:
    findings: tuple[WorksheetRevisionVisualFinding, ...]

    @property
    def passed(self) -> bool:
        return not any(finding.severity == "fail" for finding in self.findings)

    @property
    def manual_review_required(self) -> bool:
        return any(finding.severity == "manual-review" for finding in self.findings)


def _validated_role_ids(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise WorksheetRevisionQAError(f"{name} must be a tuple")
    for role_id in value:
        if not isinstance(role_id, str) or not role_id.strip():
            raise WorksheetRevisionQAError(f"{name} must contain non-empty text role IDs")
        if role_id != role_id.strip() or any(char.isspace() for char in role_id):
            raise WorksheetRevisionQAError(f"{name} contains a malformed role ID")
    return value


def validate_revision_preserves_required_visual_roles(
    *,
    prior_required_role_ids: tuple[str, ...],
    revised_required_role_ids: tuple[str, ...],
    teacher_removed_role_ids: tuple[str, ...] = (),
) -> WorksheetRevisionVisualResult:
    """Fail when a revision silently drops a required visual role.

    Required visual roles declared by the prior revision must survive into the
    revised source unless the teacher or the governing source explicitly
    removed them (recorded in ``teacher_removed_role_ids``). Fixing
    vocabulary, content, or layout cannot silently delete previously required
    visual scaffolds; dropping a role without explicit removal is a
    completion regression and the revision cannot be presented as complete.
    """
    prior = _validated_role_ids(prior_required_role_ids, "prior_required_role_ids")
    revised = set(_validated_role_ids(revised_required_role_ids, "revised_required_role_ids"))
    removed = set(_validated_role_ids(teacher_removed_role_ids, "teacher_removed_role_ids"))
    dropped = sorted(set(prior) - revised - removed)
    findings: list[WorksheetRevisionVisualFinding] = []
    if dropped:
        findings.append(
            WorksheetRevisionVisualFinding(
                "worksheet-revision-required-visual-dropped",
                "fail",
                "Revision silently dropped required visual roles declared by the prior "
                "revision without explicit teacher/source removal: "
                + ", ".join(dropped)
                + ". Restore the roles or record their explicit removal before "
                "claiming a complete revision.",
            )
        )
    return WorksheetRevisionVisualResult(tuple(findings))


def validate_revision_render_visuals(
    *,
    required_role_ids: tuple[str, ...],
    rendered_visual_role_ids: tuple[str, ...] = (),
    unresolved_visual_role_ids: tuple[str, ...] = (),
) -> WorksheetRevisionVisualResult:
    """Fail when the final render has zero or missing required icons/images.

    Reuses the existing ``visual_completeness`` contract: a worksheet revision
    with required visual roles cannot pass as complete when the final render
    has zero or missing required icons/images. Roles that are required but
    unresolved route to manual review rather than receiving a false pass.
    """
    required = _validated_role_ids(required_role_ids, "required_role_ids")
    rendered = _validated_role_ids(rendered_visual_role_ids, "rendered_visual_role_ids")
    unresolved = _validated_role_ids(unresolved_visual_role_ids, "unresolved_visual_role_ids")
    outcome = validate_visual_completeness(
        required_roles=required,
        verified_roles=rendered,
        unresolved_roles=unresolved,
    )
    findings: list[WorksheetRevisionVisualFinding] = []
    if outcome.status == "fail":
        findings.append(
            WorksheetRevisionVisualFinding(
                "worksheet-revision-render-missing-required-visuals",
                "fail",
                "Final render is missing required visual roles: "
                + ", ".join(outcome.missing_roles)
                + ". A worksheet revision cannot be presented as complete while "
                "required icons/images are absent from the render.",
            )
        )
    elif outcome.status == "manual-review":
        findings.append(
            WorksheetRevisionVisualFinding(
                "worksheet-revision-render-visual-needs-review",
                "manual-review",
                "Required visual roles are unresolved in the final render: "
                + ", ".join(outcome.unresolved_roles)
                + ". Manual review must confirm their presence before a "
                "classroom-ready claim.",
            )
        )
    return WorksheetRevisionVisualResult(tuple(findings))


# --- Cross-artifact lesson-revision alignment (#3577) ---------------------------
#
# A Day 1 worksheet must practice the current approved lesson revision: the
# worksheet declares the exact deck revision it was synchronized against, and
# every material learning target of that deck revision must be covered by at
# least one worksheet task. When the deck's material learning targets change
# (new deck revision), a worksheet still declaring the older revision is
# stale and the revision cannot be presented as complete. Coverage is a
# set-membership check over declared target identities — no invented
# thresholds. Unmeasured coverage routes to manual review and never receives
# a mechanical pass. Pure repository-side QA: no rendering, retrieval, or
# external-system mutation.


def _validated_target_ids(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise WorksheetRevisionQAError(f"{name} must be a tuple")
    for target_id in value:
        if not isinstance(target_id, str) or not target_id.strip():
            raise WorksheetRevisionQAError(f"{name} must contain non-empty text target IDs")
        if target_id != target_id.strip() or any(char.isspace() for char in target_id):
            raise WorksheetRevisionQAError(f"{name} contains a malformed target ID")
    return value


def _validated_revision_token(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorksheetRevisionQAError(f"{name} must be a non-empty text revision identity")
    if value != value.strip() or any(char.isspace() for char in value):
        raise WorksheetRevisionQAError(f"{name} contains a malformed revision identity")
    return value


def _validated_task_coverage(
    value: object,
) -> tuple[tuple[str, tuple[str, ...]], ...] | None:
    if value is None:
        return None
    if not isinstance(value, tuple):
        raise WorksheetRevisionQAError("worksheet_task_coverage must be a tuple or None")
    seen_task_ids: set[str] = set()
    normalized: list[tuple[str, tuple[str, ...]]] = []
    for entry in value:
        if (
            not isinstance(entry, tuple)
            or len(entry) != 2
            or not isinstance(entry[0], str)
            or not entry[0].strip()
        ):
            raise WorksheetRevisionQAError(
                "worksheet_task_coverage entries must be (task_id, covered_target_ids) tuples"
            )
        task_id = entry[0]
        if task_id in seen_task_ids:
            raise WorksheetRevisionQAError(
                f"worksheet_task_coverage contains a duplicate task_id: {task_id}"
            )
        seen_task_ids.add(task_id)
        normalized.append((task_id, _validated_target_ids(entry[1], f"coverage of task {task_id}")))
    return tuple(normalized)


def validate_lesson_revision_alignment(
    *,
    lesson_id: str,
    deck_revision_id: str,
    deck_learning_target_ids: tuple[str, ...],
    worksheet_lesson_id: str,
    worksheet_synced_deck_revision_id: str,
    worksheet_task_coverage: tuple[tuple[str, tuple[str, ...]], ...] | None,
) -> WorksheetRevisionVisualResult:
    """Reject a stale or uncovered worksheet revision against its deck revision.

    ``worksheet_synced_deck_revision_id`` is the exact deck revision the
    worksheet was synchronized against. When the deck moves to a new revision
    (material learning targets change), a worksheet still declaring the older
    revision is stale: the finding ``worksheet-stale-deck-revision`` fails the
    revision. Every deck learning target must be covered by at least one
    worksheet task or the ``worksheet-learning-target-uncovered`` finding
    fails it. A worksheet built for a different lesson fails with
    ``worksheet-lesson-identity-mismatch``. When task coverage is unmeasured
    (``None``), alignment routes to manual review via
    ``worksheet-alignment-coverage-unmeasured`` — never a mechanical pass.
    """
    lesson = _validated_revision_token(lesson_id, "lesson_id")
    deck_revision = _validated_revision_token(deck_revision_id, "deck_revision_id")
    worksheet_lesson = _validated_revision_token(worksheet_lesson_id, "worksheet_lesson_id")
    worksheet_synced = _validated_revision_token(
        worksheet_synced_deck_revision_id, "worksheet_synced_deck_revision_id"
    )
    deck_targets = _validated_target_ids(deck_learning_target_ids, "deck_learning_target_ids")
    if not deck_targets:
        raise WorksheetRevisionQAError(
            "deck_learning_target_ids must declare at least one learning target"
        )
    coverage = _validated_task_coverage(worksheet_task_coverage)

    findings: list[WorksheetRevisionVisualFinding] = []

    if worksheet_lesson != lesson:
        findings.append(
            WorksheetRevisionVisualFinding(
                "worksheet-lesson-identity-mismatch",
                "fail",
                "Worksheet declares lesson "
                + worksheet_lesson
                + " but the deck revision under review belongs to lesson "
                + lesson
                + ". Cross-artifact synchronization requires one shared lesson identity.",
            )
        )

    if worksheet_synced != deck_revision:
        findings.append(
            WorksheetRevisionVisualFinding(
                "worksheet-stale-deck-revision",
                "fail",
                "Worksheet was synchronized against deck revision "
                + worksheet_synced
                + " but the current deck revision is "
                + deck_revision
                + ". The deck's material learning targets may have changed; "
                "re-synchronize the worksheet before claiming it is current.",
            )
        )

    if coverage is None:
        findings.append(
            WorksheetRevisionVisualFinding(
                "worksheet-alignment-coverage-unmeasured",
                "manual-review",
                "Worksheet task coverage is unmeasured: manual review must confirm "
                "every deck learning target is exercised by a worksheet task before "
                "a classroom-ready claim.",
            )
        )
        return WorksheetRevisionVisualResult(tuple(findings))

    declared_targets = set(deck_targets)
    for task_id, covered in coverage:
        unknown = sorted(set(covered) - declared_targets)
        if unknown:
            raise WorksheetRevisionQAError(
                f"task {task_id} covers undeclared learning targets: " + ", ".join(unknown)
            )
    covered_targets = {target for _, covered in coverage for target in covered}
    uncovered = sorted(declared_targets - covered_targets)
    if uncovered:
        findings.append(
            WorksheetRevisionVisualFinding(
                "worksheet-learning-target-uncovered",
                "fail",
                "Deck learning targets with no covering worksheet task: "
                + ", ".join(uncovered)
                + ". The worksheet does not practice the current approved lesson targets.",
            )
        )

    return WorksheetRevisionVisualResult(tuple(findings))


# --- Governed lesson-revision spec parsing (#3577 integration) ----------------
#
# The cross-artifact validator needs governed inputs: which deck revision the
# worksheet must synchronize against, the deck's material learning targets,
# and the worksheet's own declarations (its synced revision, its task
# coverage). Those inputs arrive as a lesson-revision spec mapping (the
# governed YAML record, e.g.
# samples/marketing_foundations_day1_lesson.yaml), parsed fail-closed here.
#
# YAML IS AN ASSERTION, NEVER A READ RECEIPT. The spec may assert the
# canonical teacher-owned Drive ID (``deck.drive_id``), the asserted revision
# and byte digest, and the coverage mapping — but it can never certify that
# the deck was actually read. A YAML ``deck_evidence`` block is rejected
# outright: a caller-typed "teacher-owned-deck-read" record is self-authored
# fake evidence, not an independently retrieved receipt.
#
# Actual source evidence arrives as an independently injected
# ``SourceContentReceipt`` built by the retrieval path (existing Drive
# metadata/fetch tools plus the host's PDF/page reader), never from YAML.
# ``bind_source_evidence`` validates the receipt against the YAML assertion
# fail-closed: wrong/foreign Drive ID, digest mismatch, filename mismatch, or
# an exact slide reference absent from the retrieved pages refuses the
# binding. Teacher ownership/endorsement is carried on the receipt as a
# SEPARATE assertion from the content hash: a hash binds bytes, it never
# establishes teacher ownership or pedagogical endorsement.


@dataclass(frozen=True)
class SourcePage:
    """One retrieved source page/slide: number + retrieved text content."""

    page_number: int
    slide_number: int | None
    text: str


@dataclass(frozen=True)
class SourceContentReceipt:
    """Independently retrieved, read-only source-content evidence (#3577).

    Built ONLY by the independent retrieval path (a Drive-backed retriever
    or an injected host reader), never parsed from YAML. ``content_digest``
    is the immutable digest of the retrieved bytes; ``teacher_owner_identity``
    and ``teacher_endorsed`` are asserted by the independent retrieval path
    (separate from the content hash — a hash binds bytes, it never
    establishes teacher ownership or pedagogical endorsement).
    """

    source_drive_id: str
    source_filename: str
    source_revision_id: str | None
    content_digest: str
    pages: tuple[SourcePage, ...]
    retrieved_at: str
    source_provenance: str
    teacher_owner_identity: str | None
    teacher_endorsed: bool

    def receipt_fingerprint(self) -> str:
        """Stable fingerprint binding every receipt field (incl. pages)."""
        payload = {
            "source_drive_id": self.source_drive_id,
            "source_filename": self.source_filename,
            "source_revision_id": self.source_revision_id,
            "content_digest": self.content_digest,
            "pages": [
                {"page_number": p.page_number, "slide_number": p.slide_number, "text": p.text}
                for p in self.pages
            ],
            "retrieved_at": self.retrieved_at,
            "source_provenance": self.source_provenance,
            "teacher_owner_identity": self.teacher_owner_identity,
            "teacher_endorsed": self.teacher_endorsed,
        }
        canonical = (
            "{"
            + ",".join(
                f"{key!r}:{_receipt_value(payload[key])}" for key in sorted(payload)
            )
            + "}"
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _receipt_value(value: object) -> str:
    if isinstance(value, str):
        return repr(value)
    if value is None or isinstance(value, bool):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_receipt_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return (
            "{"
            + ",".join(
                f"{key!r}:{_receipt_value(value[key])}" for key in sorted(value)
            )
            + "}"
        )
    return repr(value)


# Text markers meaning "not yet a verified exact deck read": approximate
# slide numbers, a read still pending, or a proposed/unverified mapping.
_UNVERIFIED_EVIDENCE_MARKERS = ("approximate", "pending", "proposed", "tbd", "unverified")

#: "exact slide N" assertions inside coverage notes; validated against the
#: independently retrieved pages at binding time. Slide 9999 (or any invented
#: number) fails the binding because no retrieved page carries it.
_EXACT_SLIDE_RE = re.compile(r"\bexact\s+slide\s+(\d+)\b", re.IGNORECASE)


@dataclass(frozen=True)
class LessonRevisionSpec:
    """Governed, parsed lesson-revision alignment inputs (#3577).

    Pure assertion: lesson/deck identity, the asserted canonical teacher-owned
    Drive ID (``deck_drive_id``), the asserted byte digest/revision, the
    deck's material learning targets, and the worksheet's sync declaration.
    ``source_evidence`` is attached ONLY by ``bind_source_evidence`` from an
    independently retrieved ``SourceContentReceipt``; ``slide_refs_validated``
    records whether every exact slide reference was validated against the
    retrieved pages.
    """

    lesson_id: str
    deck_revision_id: str
    deck_filename: str
    deck_learning_target_ids: tuple[str, ...]
    worksheet_lesson_id: str
    worksheet_synced_deck_revision_id: str
    worksheet_task_coverage: tuple[tuple[str, tuple[str, ...]], ...] | None
    approximate_evidence_refs: tuple[str, ...]
    deck_drive_id: str | None = None
    deck_drive_revision_id: str | None = None
    deck_content_digest: str | None = None
    exact_slide_refs: tuple[tuple[str, int], ...] = ()
    source_evidence: SourceContentReceipt | None = None
    slide_refs_validated: bool = False


def _spec_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorksheetRevisionQAError(f"{name} must be non-empty text")
    if value != value.strip() or any(char.isspace() for char in value):
        raise WorksheetRevisionQAError(f"{name} is a malformed identity")
    return value


def _spec_optional_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _spec_text(value, name)


def _spec_mapping(value: object, name: str) -> dict:
    if not isinstance(value, dict):
        raise WorksheetRevisionQAError(f"{name} must be a mapping")
    return value


def _looks_approximate(text: object) -> bool:
    return isinstance(text, str) and any(
        marker in text.lower() for marker in _UNVERIFIED_EVIDENCE_MARKERS
    )


def _coverage_entry_is_approximate(entry: dict) -> bool:
    if "deck_slides_approx" in entry:
        return True
    return any(
        _looks_approximate(entry.get(key))
        for key in ("deck_slide_note", "slide_note", "deck_mapping_note")
    )


def _coverage_entry_exact_slides(entry: dict) -> tuple[int, ...]:
    slides: list[int] = []
    for key in ("deck_slide_note", "slide_note", "deck_mapping_note"):
        note = entry.get(key)
        if isinstance(note, str):
            slides.extend(int(match) for match in _EXACT_SLIDE_RE.findall(note))
    return tuple(slides)


def parse_lesson_revision_spec(value: object) -> LessonRevisionSpec:
    """Parse a lesson-revision spec mapping fail-closed (#3577).

    The spec is an ASSERTION: the deck revision identity, the asserted
    canonical teacher-owned Drive ID (``deck.drive_id``), asserted byte
    digest/revision, the deck's material learning targets, and the
    worksheet's sync declaration (synced deck revision + task coverage).

    A ``deck_evidence`` mapping is REJECTED outright: YAML is never a
    self-certified read receipt, and a caller-typed
    ``teacher-owned-deck-read`` record is fake evidence. Source evidence is
    attached later by ``bind_source_evidence`` from an independently
    injected ``SourceContentReceipt``.
    """
    spec = _spec_mapping(value, "lesson_revision_spec")
    lesson_id = _spec_text(spec.get("lesson_id"), "lesson_id")

    if spec.get("deck_evidence") is not None:
        raise WorksheetRevisionQAError(
            "lesson_revision_spec must not carry deck_evidence: YAML is an "
            "assertion, never a self-certified read receipt. Source evidence "
            "is independently injected and bound via bind_source_evidence; a "
            "caller-typed deck_evidence record is rejected as fake evidence."
        )

    deck = _spec_mapping(spec.get("deck"), "deck")
    deck_revision_id = _spec_text(deck.get("revision_id"), "deck.revision_id")
    deck_filename = _spec_text(deck.get("filename"), "deck.filename")
    deck_drive_id = _spec_optional_text(deck.get("drive_id"), "deck.drive_id")
    deck_drive_revision_id = _spec_optional_text(
        deck.get("drive_revision_id"), "deck.drive_revision_id"
    )
    deck_content_digest = _spec_optional_text(
        deck.get("content_digest"), "deck.content_digest"
    )
    approximate_refs: list[str] = []
    if _looks_approximate(deck.get("slide_mapping_source")):
        approximate_refs.append("deck.slide_mapping_source")

    targets = spec.get("learning_targets")
    if not isinstance(targets, list) or not targets:
        raise WorksheetRevisionQAError("learning_targets must be a non-empty list")
    target_ids: list[str] = []
    concept_to_id: dict[str, str] = {}
    for entry in targets:
        entry_map = _spec_mapping(entry, "learning_targets entry")
        target_id = _spec_text(entry_map.get("id"), "learning_targets entry id")
        if target_id in target_ids:
            raise WorksheetRevisionQAError(
                f"learning_targets contains a duplicate id: {target_id}"
            )
        target_ids.append(target_id)
        concept = entry_map.get("concept")
        if isinstance(concept, str) and concept.strip():
            concept_to_id.setdefault(concept.strip(), target_id)

    worksheet = _spec_mapping(spec.get("worksheet"), "worksheet")
    worksheet_lesson_id = _spec_text(worksheet.get("lesson_id"), "worksheet.lesson_id")
    worksheet_synced = _spec_text(
        worksheet.get("synced_deck_revision_id"), "worksheet.synced_deck_revision_id"
    )

    coverage_matrix = spec.get("coverage_matrix")
    task_targets: dict[str, set[str]] = {}
    exact_slide_refs: list[tuple[str, int]] = []
    if coverage_matrix is not None:
        if not isinstance(coverage_matrix, list):
            raise WorksheetRevisionQAError("coverage_matrix must be a list")
        for entry in coverage_matrix:
            entry_map = _spec_mapping(entry, "coverage_matrix entry")
            ref = entry_map.get("target_id") or entry_map.get("concept")
            target_id = None
            if isinstance(ref, str) and ref.strip():
                ref = ref.strip()
                if ref in target_ids:
                    target_id = ref
                elif ref in concept_to_id:
                    target_id = concept_to_id[ref]
            if target_id is None:
                raise WorksheetRevisionQAError(
                    "coverage_matrix entry references an unknown learning target: "
                    + repr(ref)
                )
            tasks = entry_map.get("worksheet_tasks")
            if not isinstance(tasks, list) or not tasks:
                raise WorksheetRevisionQAError(
                    "coverage_matrix entry must list non-empty worksheet_tasks"
                )
            for task in tasks:
                task_id = _spec_text(task, "coverage_matrix worksheet task")
                task_targets.setdefault(task_id, set()).add(target_id)
            if _coverage_entry_is_approximate(entry_map):
                approximate_refs.append(target_id)
            for slide_no in _coverage_entry_exact_slides(entry_map):
                exact_slide_refs.append((target_id, slide_no))
    worksheet_task_coverage = (
        tuple(
            (task_id, tuple(sorted(covered)))
            for task_id, covered in sorted(task_targets.items())
        )
        or None
    )

    return LessonRevisionSpec(
        lesson_id=lesson_id,
        deck_revision_id=deck_revision_id,
        deck_filename=deck_filename,
        deck_learning_target_ids=tuple(target_ids),
        worksheet_lesson_id=worksheet_lesson_id,
        worksheet_synced_deck_revision_id=worksheet_synced,
        worksheet_task_coverage=worksheet_task_coverage,
        approximate_evidence_refs=tuple(sorted(set(approximate_refs))),
        deck_drive_id=deck_drive_id,
        deck_drive_revision_id=deck_drive_revision_id,
        deck_content_digest=deck_content_digest,
        exact_slide_refs=tuple(sorted(set(exact_slide_refs))),
    )


def bind_source_evidence(
    spec: LessonRevisionSpec, receipt: SourceContentReceipt
) -> LessonRevisionSpec:
    """Bind an independently retrieved receipt to a parsed spec (#3577).

    Validates the receipt against the YAML assertion fail-closed and returns
    a new spec carrying ``source_evidence``:

    - the spec must assert a canonical ``deck.drive_id``; without it the
      source cannot be attributed and the binding is refused;
    - the receipt's Drive ID must equal the asserted ID (wrong/foreign deck
      IDs fail);
    - the receipt's filename must equal the asserted filename;
    - when the spec asserts ``deck.content_digest`` / ``deck.drive_revision_id``,
      the receipt must match (hash/revision mismatch fails);
    - every exact slide reference in the spec must resolve to a retrieved
      page/slide with non-empty content (an invented "exact slide 9999"
      fails);
    - when the receipt carries no retrieved pages, exact slide references
      cannot be validated: the binding succeeds but
      ``slide_refs_validated`` stays False so terminal QA routes to manual
      review instead of a clean acceptance.
    """
    if not isinstance(spec, LessonRevisionSpec):
        raise WorksheetRevisionQAError("spec must be a LessonRevisionSpec")
    if not isinstance(receipt, SourceContentReceipt):
        raise WorksheetRevisionQAError("receipt must be a SourceContentReceipt")

    if spec.deck_drive_id is None:
        raise WorksheetRevisionQAError(
            "lesson-revision spec asserts no deck.drive_id: the independently "
            "retrieved source cannot be attributed to the declared deck and "
            "the evidence binding is refused. Assert the canonical "
            "teacher-owned Drive ID in the spec."
        )
    if receipt.source_drive_id != spec.deck_drive_id:
        raise WorksheetRevisionQAError(
            "source evidence Drive ID "
            + receipt.source_drive_id
            + " does not match the spec's asserted canonical teacher-owned "
            "Drive ID "
            + spec.deck_drive_id
            + "; a wrong/foreign deck cannot satisfy the lesson-revision gate."
        )
    if receipt.source_filename != spec.deck_filename:
        raise WorksheetRevisionQAError(
            "source evidence filename "
            + repr(receipt.source_filename)
            + " does not match the spec's asserted deck filename "
            + repr(spec.deck_filename)
            + "."
        )
    if (
        spec.deck_content_digest is not None
        and receipt.content_digest != spec.deck_content_digest
    ):
        raise WorksheetRevisionQAError(
            "source evidence content digest does not match the spec's asserted "
            "deck content digest; the retrieved bytes are not the declared "
            "deck revision."
        )
    if (
        spec.deck_drive_revision_id is not None
        and receipt.source_revision_id != spec.deck_drive_revision_id
    ):
        raise WorksheetRevisionQAError(
            "source evidence Drive revision "
            + repr(receipt.source_revision_id)
            + " does not match the spec's asserted deck Drive revision "
            + repr(spec.deck_drive_revision_id)
            + "."
        )

    slide_refs_validated = True
    if spec.exact_slide_refs:
        if not receipt.pages:
            slide_refs_validated = False
        else:
            retrieved = {
                page.slide_number
                for page in receipt.pages
                if page.slide_number is not None and page.text.strip()
            }
            for target_id, slide_no in spec.exact_slide_refs:
                if slide_no not in retrieved:
                    raise WorksheetRevisionQAError(
                        "spec references exact slide "
                        + str(slide_no)
                        + " (coverage target "
                        + target_id
                        + ") but the independently retrieved source content "
                        "contains no such slide with retrieved content; "
                        "invented slide references cannot satisfy the "
                        "lesson-revision gate."
                    )

    return dataclasses.replace(
        spec, source_evidence=receipt, slide_refs_validated=slide_refs_validated
    )


def observed_worksheet_alignment_findings(
    *,
    spec: LessonRevisionSpec,
    observed_text: str,
) -> WorksheetRevisionVisualResult:
    """Check the OBSERVED worksheet against the trusted anchors (#3577).

    The YAML assertion is never compared to itself: the persisted worksheet
    text must carry the trusted lesson/revision anchors from the bound spec,
    and every worksheet task in the reviewed target mapping must be observed
    in the persisted worksheet. A stale persisted worksheet (e.g. Day-8 text
    against a Day-1 declaration) fails; invented YAML tasks absent from the
    persisted worksheet fail.
    """
    if not isinstance(spec, LessonRevisionSpec):
        raise WorksheetRevisionQAError("spec must be a LessonRevisionSpec")
    observed = observed_text.casefold() if isinstance(observed_text, str) else ""
    findings: list[WorksheetRevisionVisualFinding] = []

    missing_anchors = [
        anchor
        for anchor in (spec.worksheet_lesson_id, spec.worksheet_synced_deck_revision_id)
        if anchor.casefold() not in observed
    ]
    if missing_anchors:
        findings.append(
            WorksheetRevisionVisualFinding(
                "worksheet-persisted-revision-mismatch",
                "fail",
                "The persisted worksheet does not carry the trusted "
                "lesson/revision anchors (" + ", ".join(missing_anchors) + "). "
                "The observed worksheet is stale or belongs to a different "
                "lesson revision than the declared synchronized deck revision.",
            )
        )

    if spec.worksheet_task_coverage is not None:
        unobserved = sorted(
            task_id
            for task_id, _ in spec.worksheet_task_coverage
            if task_id.casefold() not in observed
        )
        if unobserved:
            findings.append(
                WorksheetRevisionVisualFinding(
                    "worksheet-task-not-observed",
                    "fail",
                    "Worksheet tasks from the reviewed target mapping are not "
                    "observed in the persisted worksheet: "
                    + ", ".join(unobserved)
                    + ". Coverage requires observed tasks, not YAML-declared "
                    "task names.",
                )
            )

    return WorksheetRevisionVisualResult(tuple(findings))
