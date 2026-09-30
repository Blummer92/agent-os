"""Deterministic rendered-layout QA for student worksheet pages.

Evaluates only mechanically provable dead-space facts from caller-supplied
rendered-inspection evidence (for example phone-scale screenshot review). A
large blank region is evidence-backed as accidental dead space only when the
same page is missing expected content, response-space, or visual roles. When
every expected role on the page is satisfied, the whitespace may be
intentional and routes to manual review instead of a false failure: the
material-quality rubric worksheet density review treats intentional whitespace
as not a defect by itself and routes unprovable density judgments to rendered
review.

This module performs no rendering, OCR/CV, provider call, classroom
publication, or external-system mutation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

LayoutSeverity = Literal["fail", "manual-review"]

#: A blank region covering at least this share of a page is large enough to
#: evaluate. The fail / manual-review distinction is driven by expected
#: instructional roles on the page, not by this share.
LARGE_BLANK_REGION_SHARE = 0.20


class WorksheetLayoutQAError(ValueError):
    """Fail-closed error for malformed worksheet layout evidence."""


@dataclass(frozen=True)
class BlankRegion:
    """One observed blank region on a worksheet page, from rendered inspection."""

    region_id: str
    page_number: int
    share_of_page: float


@dataclass(frozen=True)
class WorksheetPageLayoutEvidence:
    """Rendered-inspection evidence for one worksheet page.

    ``expected_roles`` are the content, response-space, and visual roles the
    page is supposed to satisfy; ``missing_roles`` is the subset not satisfied
    on the page. ``inspection_scale`` records the review perspective (for
    example ``phone-scale``) required by the rendered classroom review gate.
    """

    page_number: int
    inspection_scale: str
    expected_roles: tuple[str, ...]
    missing_roles: tuple[str, ...]
    blank_regions: tuple[BlankRegion, ...]


@dataclass(frozen=True)
class WorksheetLayoutFinding:
    code: str
    severity: LayoutSeverity
    page_number: int
    message: str


@dataclass(frozen=True)
class WorksheetLayoutQAResult:
    findings: tuple[WorksheetLayoutFinding, ...]

    @property
    def passed(self) -> bool:
        return not any(finding.severity == "fail" for finding in self.findings)

    @property
    def manual_review_required(self) -> bool:
        return any(finding.severity == "manual-review" for finding in self.findings)


def _validated_pages(pages: object) -> tuple[WorksheetPageLayoutEvidence, ...]:
    if not isinstance(pages, tuple):
        raise WorksheetLayoutQAError("pages must be a tuple")
    for page in pages:
        if not isinstance(page, WorksheetPageLayoutEvidence):
            raise WorksheetLayoutQAError("pages must contain WorksheetPageLayoutEvidence values")
        if not isinstance(page.page_number, int) or isinstance(page.page_number, bool) or page.page_number < 1:
            raise WorksheetLayoutQAError("page_number must be a positive integer")
        if not isinstance(page.inspection_scale, str) or not page.inspection_scale.strip():
            raise WorksheetLayoutQAError("inspection_scale must be non-empty text")
        expected = _validated_roles(page.expected_roles, "expected_roles")
        missing = _validated_roles(page.missing_roles, "missing_roles")
        unknown = sorted(set(missing) - set(expected))
        if unknown:
            raise WorksheetLayoutQAError(
                "missing_roles must be a subset of expected_roles: " + ", ".join(unknown)
            )
        if not isinstance(page.blank_regions, tuple):
            raise WorksheetLayoutQAError("blank_regions must be a tuple")
        for region in page.blank_regions:
            if not isinstance(region, BlankRegion):
                raise WorksheetLayoutQAError("blank_regions must contain BlankRegion values")
            if not isinstance(region.region_id, str) or not region.region_id.strip():
                raise WorksheetLayoutQAError("blank region region_id must be non-empty text")
            if region.page_number != page.page_number:
                raise WorksheetLayoutQAError("blank region page_number must match its page evidence")
            if (
                isinstance(region.share_of_page, bool)
                or not isinstance(region.share_of_page, (int, float))
                or not 0.0 < region.share_of_page <= 1.0
            ):
                raise WorksheetLayoutQAError("blank region share_of_page must be in (0, 1]")
    return pages


def _validated_roles(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise WorksheetLayoutQAError(f"{name} must be a tuple")
    for role in value:
        if not isinstance(role, str) or not role.strip():
            raise WorksheetLayoutQAError(f"{name} must contain non-empty text roles")
    return value


def evaluate_worksheet_layout(pages: tuple[WorksheetPageLayoutEvidence, ...]) -> WorksheetLayoutQAResult:
    """Return deterministic dead-space failures plus bounded manual-review hooks.

    A large blank region on a page that is missing expected content,
    response-space, or visual roles is flagged as accidental dead space: the
    missing roles are the evidence that the space should have carried
    instructional content. A large blank region on a page where every expected
    role is satisfied cannot be proven accidental, so it routes to manual
    review instead of failing. Blank regions below the large-region bound are
    ordinary breathing room and produce no finding.
    """
    evidence = _validated_pages(pages)
    findings: list[WorksheetLayoutFinding] = []
    for page in evidence:
        for region in page.blank_regions:
            if region.share_of_page < LARGE_BLANK_REGION_SHARE:
                continue
            if page.missing_roles:
                findings.append(
                    WorksheetLayoutFinding(
                        "worksheet-dead-space-with-missing-roles",
                        "fail",
                        page.page_number,
                        f"Large blank region '{region.region_id}' covers "
                        f"{region.share_of_page:.0%} of page {page.page_number} while "
                        "expected content/response/visual roles are missing: "
                        + ", ".join(page.missing_roles)
                        + ". The unused space is evidence-backed as accidental dead "
                        "space, not intentional whitespace.",
                    )
                )
            else:
                findings.append(
                    WorksheetLayoutFinding(
                        "worksheet-large-blank-region-unprovable",
                        "manual-review",
                        page.page_number,
                        f"Large blank region '{region.region_id}' covers "
                        f"{region.share_of_page:.0%} of page {page.page_number} but every "
                        "expected role is satisfied. Rendered/manual review must decide "
                        "whether the whitespace is intentional; it is not mechanically "
                        "rejected.",
                    )
                )
    return WorksheetLayoutQAResult(tuple(findings))
