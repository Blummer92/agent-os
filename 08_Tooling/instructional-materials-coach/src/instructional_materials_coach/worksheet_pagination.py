"""Worksheet heading keep-with-next rule for the canonical Docs build (#3416).

A worksheet heading must stay on the same page as the content that follows
it. The canonical build guarantees this by setting ``keepWithNext`` on every
heading paragraph whose effective value is not already ``true``, and terminal
QA (#3258) verifies it on the persisted readback.

Pure functions over Google Docs ``documents.get`` JSON: no I/O, no clients.
The build and QA share one resolver so they can never disagree about which
headings need the rule.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, Mapping

HEADING_STYLE_TYPES = frozenset(f"HEADING_{level}" for level in range(1, 7))
_NORMAL_TEXT = "NORMAL_TEXT"


@dataclass(frozen=True)
class HeadingParagraph:
    """One heading paragraph and its effective keep-with-next value."""

    start_index: int
    end_index: int
    named_style_type: str
    keep_with_next: bool


def _named_style_keep_with_next(document: Mapping[str, Any]) -> dict[str, bool]:
    """Map named style type -> keepWithNext, for styles that set it."""
    resolved: dict[str, bool] = {}
    named_styles = document.get("namedStyles")
    styles = named_styles.get("styles") if isinstance(named_styles, Mapping) else None
    if not isinstance(styles, list):
        return resolved
    for style in styles:
        if not isinstance(style, Mapping):
            continue
        style_type = style.get("namedStyleType")
        paragraph_style = style.get("paragraphStyle")
        if not isinstance(style_type, str) or not isinstance(paragraph_style, Mapping):
            continue
        value = paragraph_style.get("keepWithNext")
        if isinstance(value, bool):
            resolved[style_type] = value
    return resolved


def _walk_paragraphs(content: Any) -> Iterator[Mapping[str, Any]]:
    """Yield structural elements carrying a paragraph, including table cells.

    Same walk as terminal QA's Docs text observation.
    """
    if not isinstance(content, list):
        return
    for element in content:
        if not isinstance(element, Mapping):
            continue
        if isinstance(element.get("paragraph"), Mapping):
            yield element
        table = element.get("table")
        if isinstance(table, Mapping):
            for row in table.get("tableRows", []):
                if not isinstance(row, Mapping):
                    continue
                for cell in row.get("tableCells", []):
                    if isinstance(cell, Mapping):
                        yield from _walk_paragraphs(cell.get("content"))


def heading_paragraphs(document: Mapping[str, Any]) -> tuple[HeadingParagraph, ...]:
    """Every body heading paragraph with its effective keep-with-next.

    Effective value: the paragraph's own ``keepWithNext``, else the named
    style's, else ``NORMAL_TEXT``'s, else ``False``. Ordered by start index.
    """
    if not isinstance(document, Mapping):
        return ()
    style_defaults = _named_style_keep_with_next(document)
    body = document.get("body")
    content = body.get("content") if isinstance(body, Mapping) else None
    headings: list[HeadingParagraph] = []
    for element in _walk_paragraphs(content):
        paragraph_style = element["paragraph"].get("paragraphStyle")
        if not isinstance(paragraph_style, Mapping):
            continue
        style_type = paragraph_style.get("namedStyleType")
        if style_type not in HEADING_STYLE_TYPES:
            continue
        start = element.get("startIndex")
        end = element.get("endIndex")
        if not isinstance(start, int) or not isinstance(end, int) or end <= start:
            raise ValueError(
                f"heading paragraph ({style_type}) has no valid startIndex/endIndex range"
            )
        own = paragraph_style.get("keepWithNext")
        if isinstance(own, bool):
            effective = own
        elif style_type in style_defaults:
            effective = style_defaults[style_type]
        else:
            effective = style_defaults.get(_NORMAL_TEXT, False)
        headings.append(HeadingParagraph(start, end, style_type, effective))
    headings.sort(key=lambda heading: heading.start_index)
    return tuple(headings)


def headings_missing_keep_with_next(document: Mapping[str, Any]) -> tuple[HeadingParagraph, ...]:
    """Heading paragraphs whose effective keep-with-next is not ``True``."""
    return tuple(heading for heading in heading_paragraphs(document) if not heading.keep_with_next)


def plan_heading_keep_with_next_requests(document: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """One ``updateParagraphStyle`` request per heading lacking the rule.

    Deterministic, ordered by start index, and empty when every heading is
    already effective. Non-heading paragraphs are never touched.
    """
    return tuple(
        {
            "updateParagraphStyle": {
                "range": {"startIndex": heading.start_index, "endIndex": heading.end_index},
                "paragraphStyle": {"keepWithNext": True},
                "fields": "keepWithNext",
            }
        }
        for heading in headings_missing_keep_with_next(document)
    )
