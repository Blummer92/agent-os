"""Deterministic worksheet pagination-balance evaluation (#2735).

A page fails this rule when rendered evidence shows a large unused vertical
band while the next bounded content block would fit safely on that same page:
the band equals or exceeds the next block's height plus the separation the
block needs. Intentional whitespace that serves pacing, transitions, or
readability is not in scope here -- this evaluator only sees rendered heights
and never judges instructional intent.

Evidence the evaluator cannot establish is routed to manual review rather than
given a mechanical pass: a page whose layout facts are unavailable is reported
as unmeasured instead of silently passing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class PageComposition:
    """Rendered vertical composition facts for one worksheet page."""

    page_index: int
    unused_band: float
    """Largest unused vertical band below the page's content."""
    next_block_height: float
    """Rendered height of the next bounded content block (0.0 when none follows)."""
    block_separation: float
    """Spacing required between consecutive content blocks."""
    measured: bool = True
    """False when layout facts are unavailable for this page."""


@dataclass(frozen=True, slots=True)
class PaginationBalanceFinding:
    """A page with an avoidable unused vertical band."""

    page_index: int
    unused_band: float
    next_block_height: float
    block_separation: float


@dataclass(frozen=True, slots=True)
class PaginationBalanceResult:
    """Evaluation outcome: findings plus any pages needing manual review."""

    findings: tuple[PaginationBalanceFinding, ...]
    unmeasured_pages: tuple[int, ...]

    @property
    def balanced(self) -> bool:
        """True when no page has an avoidable unused vertical band."""
        return not self.findings

    @property
    def needs_manual_review(self) -> bool:
        """True when at least one page could not be measured mechanically."""
        return bool(self.unmeasured_pages)


def _validate(page: PageComposition) -> None:
    if page.page_index < 0:
        raise ValueError("page_index must be non-negative")
    for name, value in (
        ("unused_band", page.unused_band),
        ("next_block_height", page.next_block_height),
        ("block_separation", page.block_separation),
    ):
        if value < 0:
            raise ValueError(f"{name} must be non-negative")


def evaluate_pagination_balance(
    pages: Iterable[PageComposition],
) -> PaginationBalanceResult:
    """Flag pages with an avoidable unused vertical band.

    A page is flagged when the next bounded content block exists and the
    largest unused vertical band fits it safely: ``unused_band >=
    next_block_height + block_separation``. Unmeasured pages are collected
    for manual review rather than passed.
    """
    findings: list[PaginationBalanceFinding] = []
    unmeasured: list[int] = []
    for page in pages:
        _validate(page)
        if not page.measured:
            unmeasured.append(page.page_index)
            continue
        if page.next_block_height <= 0:
            continue
        if page.unused_band >= page.next_block_height + page.block_separation:
            findings.append(
                PaginationBalanceFinding(
                    page_index=page.page_index,
                    unused_band=page.unused_band,
                    next_block_height=page.next_block_height,
                    block_separation=page.block_separation,
                )
            )
    return PaginationBalanceResult(
        findings=tuple(findings), unmeasured_pages=tuple(unmeasured)
    )
