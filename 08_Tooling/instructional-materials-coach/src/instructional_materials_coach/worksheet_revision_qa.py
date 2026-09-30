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
