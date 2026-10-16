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
