"""#3416: heading keep-with-next for canonical worksheets.

Migrates the #3176 pagination rule into the governed build (#3259 D1/D1b):
a heading must never be the last line of a page while its section starts on
the next one. Google Docs expresses this as ``ParagraphStyle.keepWithNext``.

Pure functions over a Docs ``documents.get`` resource. The build plans
requests from the readback; terminal QA (#3258) verifies the same effective
value from its own readback.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

HEADING_STYLE_TYPES = frozenset(f"HEADING_{level}" for level in range(1, 7))


@dataclass(frozen=True)
class HeadingParagraph:
    """One heading paragraph and its effective keep-with-next value."""

    named_style_type: str
    keep_with_next: bool
    text: str
    start_index: int | None
    end_index: int | None


def _named_keep_with_next(document: Mapping[str, Any]) -> dict[str, bool]:
    named: dict[str, bool] = {}
    styles = (document.get("namedStyles") or {}).get("styles")
    if not isinstance(styles, list):
        return named
    for style in styles:
        if not isinstance(style, dict):
            continue
        paragraph_style = style.get("paragraphStyle")
        if not isinstance(paragraph_style, dict):
            continue
        value = paragraph_style.get("keepWithNext")
        if isinstance(value, bool):
            named[str(style.get("namedStyleType", ""))] = value
    return named


def _effective(paragraph_style: Mapping[str, Any], style_type: str, named: Mapping[str, bool]) -> bool:
    """First set value wins: paragraph, its named style, NORMAL_TEXT, then False."""
    direct = paragraph_style.get("keepWithNext")
    if isinstance(direct, bool):
        return direct
    if style_type in named:
        return named[style_type]
    return named.get("NORMAL_TEXT", False)


def _index(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def heading_paragraphs(document: Any) -> tuple[HeadingParagraph, ...]:
    """Every HEADING_1-6 paragraph in the body, including table cells.

    A non-mapping readback has no observable headings; callers that need
    proof of the rule (terminal QA) already fail closed on such a readback.
    """
    if not isinstance(document, Mapping):
        return ()
    named = _named_keep_with_next(document)
    headings: list[HeadingParagraph] = []

    def _walk(content: Any) -> None:
        if not isinstance(content, list):
            return
        for element in content:
            if not isinstance(element, dict):
                continue
            paragraph = element.get("paragraph")
            if isinstance(paragraph, dict):
                paragraph_style = paragraph.get("paragraphStyle")
                if not isinstance(paragraph_style, dict):
                    paragraph_style = {}
                style_type = str(paragraph_style.get("namedStyleType", ""))
                if style_type in HEADING_STYLE_TYPES:
                    text = "".join(
                        str((child.get("textRun") or {}).get("content", ""))
                        for child in paragraph.get("elements", [])
                        if isinstance(child, dict)
                    )
                    headings.append(HeadingParagraph(
                        named_style_type=style_type,
                        keep_with_next=_effective(paragraph_style, style_type, named),
                        text=text.strip(),
                        start_index=_index(element.get("startIndex")),
                        end_index=_index(element.get("endIndex")),
                    ))
            table = element.get("table")
            if isinstance(table, dict):
                for row in table.get("tableRows", []):
                    if not isinstance(row, dict):
                        continue
                    for cell in row.get("tableCells", []):
                        if isinstance(cell, dict):
                            _walk(cell.get("content"))

    _walk((document.get("body") or {}).get("content"))
    return tuple(headings)


def plan_keep_with_next_requests(document: Any) -> list[dict[str, Any]]:
    """``updateParagraphStyle`` requests for headings lacking keep-with-next.

    Empty when every heading already keeps with next, so applying the plan
    is idempotent. A heading without readable indices cannot be targeted;
    it is left for terminal QA to refuse.
    """
    targets = sorted(
        (heading for heading in heading_paragraphs(document)
         if not heading.keep_with_next
         and heading.start_index is not None
         and heading.end_index is not None
         and heading.start_index < heading.end_index),
        key=lambda heading: heading.start_index,
    )
    return [
        {
            "updateParagraphStyle": {
                "range": {"startIndex": heading.start_index, "endIndex": heading.end_index},
                "paragraphStyle": {"keepWithNext": True},
                "fields": "keepWithNext",
            }
        }
        for heading in targets
    ]
