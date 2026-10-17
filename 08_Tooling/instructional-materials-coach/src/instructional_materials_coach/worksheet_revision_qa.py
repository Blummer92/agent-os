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
# Evidence provenance is part of the parse. A spec carries VERIFIED deck
# evidence ONLY when it declares an explicit teacher-owned-deck read record
# for the declared deck filename. Self-authored slide mappings (approximate
# slide indices, approximate mapping sources, approximate slide notes) are
# NEVER verified teacher-owned deck evidence: they parse as unverified, and a
# spec that claims a verified deck read while still carrying approximate
# slide markers is contradictory evidence and is rejected outright. Downstream
# (terminal QA), approximate slide numbers can never produce a clean
# acceptance result — they route to manual review.


_VERIFIED_DECK_EVIDENCE_KIND = "teacher-owned-deck-read"
# Text markers meaning "not yet a verified exact deck read": approximate
# slide numbers, a read still pending, or a proposed/unverified mapping.
_UNVERIFIED_EVIDENCE_MARKERS = ("approximate", "pending", "proposed", "tbd", "unverified")


@dataclass(frozen=True)
class LessonRevisionSpec:
    """Governed, parsed lesson-revision alignment inputs (#3577)."""

    lesson_id: str
    deck_revision_id: str
    deck_filename: str
    deck_learning_target_ids: tuple[str, ...]
    worksheet_lesson_id: str
    worksheet_synced_deck_revision_id: str
    worksheet_task_coverage: tuple[tuple[str, tuple[str, ...]], ...] | None
    deck_evidence_verified: bool
    approximate_evidence_refs: tuple[str, ...]


def _spec_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorksheetRevisionQAError(f"{name} must be non-empty text")
    if value != value.strip() or any(char.isspace() for char in value):
        raise WorksheetRevisionQAError(f"{name} is a malformed identity")
    return value


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


def parse_lesson_revision_spec(value: object) -> LessonRevisionSpec:
    """Parse a lesson-revision spec mapping fail-closed (#3577).

    The spec declares the deck revision identity, the deck's material
    learning targets, and the worksheet's sync declaration (synced deck
    revision + task coverage). ``deck_evidence_verified`` is True only for a
    spec with an explicit teacher-owned-deck read record for the declared
    deck filename and zero approximate slide markers; a spec claiming a
    verified read while carrying approximate slide markers is rejected.
    """
    spec = _spec_mapping(value, "lesson_revision_spec")
    lesson_id = _spec_text(spec.get("lesson_id"), "lesson_id")

    deck = _spec_mapping(spec.get("deck"), "deck")
    deck_revision_id = _spec_text(deck.get("revision_id"), "deck.revision_id")
    deck_filename = _spec_text(deck.get("filename"), "deck.filename")
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
    worksheet_task_coverage = (
        tuple(
            (task_id, tuple(sorted(covered)))
            for task_id, covered in sorted(task_targets.items())
        )
        or None
    )

    deck_evidence = spec.get("deck_evidence")
    verified = False
    if deck_evidence is not None:
        evidence = _spec_mapping(deck_evidence, "deck_evidence")
        kind = evidence.get("kind")
        evidence_filename = evidence.get("filename")
        if kind == _VERIFIED_DECK_EVIDENCE_KIND:
            if not (isinstance(evidence_filename, str) and evidence_filename == deck_filename):
                raise WorksheetRevisionQAError(
                    "deck_evidence claims a teacher-owned deck read but does not name "
                    "the declared deck filename; the evidence is not attributable."
                )
            if approximate_refs:
                raise WorksheetRevisionQAError(
                    "deck_evidence claims a verified teacher-owned deck read while the "
                    "spec still carries approximate slide markers ("
                    + ", ".join(sorted(set(approximate_refs)))
                    + "); approximate self-authored mappings are rejected as "
                    "verified evidence. Remove the approximate markers or drop the "
                    "verified claim."
                )
            verified = True
        elif kind not in (None, ""):
            raise WorksheetRevisionQAError(
                "deck_evidence.kind must be "
                + repr(_VERIFIED_DECK_EVIDENCE_KIND)
                + " to count as verified teacher-owned deck evidence; got "
                + repr(kind)
            )

    return LessonRevisionSpec(
        lesson_id=lesson_id,
        deck_revision_id=deck_revision_id,
        deck_filename=deck_filename,
        deck_learning_target_ids=tuple(target_ids),
        worksheet_lesson_id=worksheet_lesson_id,
        worksheet_synced_deck_revision_id=worksheet_synced,
        worksheet_task_coverage=worksheet_task_coverage,
        deck_evidence_verified=verified,
        approximate_evidence_refs=tuple(sorted(set(approximate_refs))),
    )
