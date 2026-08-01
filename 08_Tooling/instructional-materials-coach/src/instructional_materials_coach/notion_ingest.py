"""Assemble a Notion unit tree into one payload for a single model call.

Notion cannot return a page tree in one response: `blocks.children.list` caps
at 100 per request and block content is recursive, so pagination is mandatory
regardless of how large the model's context window is. The win here is one
*model* call over an assembled document, not fewer HTTP calls.

Read-only by construction -- this module exposes no write verb. HTTP is
injected, so the package takes on no new network dependency and tests need no
live Notion access.
"""
from __future__ import annotations

import dataclasses
from typing import Any, Callable, Iterator, Optional

MAX_PAGE_SIZE = 100
DEFAULT_MAX_DEPTH = 12
DEFAULT_MAX_RETRIES = 5
INITIAL_BACKOFF_SECONDS = 0.5

# Notion allows roughly 3 requests/second; deep trees amplify quickly.
ChildrenFetcher = Callable[[str, Optional[str]], dict[str, Any]]


class NotionIngestError(RuntimeError):
    """Raised when a tree cannot be assembled completely."""


@dataclasses.dataclass(frozen=True)
class UnitNode:
    """One block plus its children. Depth-first assembly of a Notion page."""

    block_id: str
    block_type: str
    text: str
    children: tuple["UnitNode", ...] = ()

    def walk(self) -> Iterator["UnitNode"]:
        yield self
        for child in self.children:
            yield from child.walk()


@dataclasses.dataclass(frozen=True)
class UnitTree:
    """An assembled unit page, with the cache key it was fetched at."""

    page_id: str
    last_edited_time: str
    root: UnitNode

    def block_count(self) -> int:
        return sum(1 for _ in self.root.walk())


def plain_text(block: dict[str, Any]) -> str:
    """Extract rendered text from a Notion block, tolerating unknown types."""
    block_type = block.get("type", "")
    payload = block.get(block_type)
    if not isinstance(payload, dict):
        return ""
    rich_text = payload.get("rich_text")
    if not isinstance(rich_text, list):
        return ""
    return "".join(
        span.get("plain_text", "") for span in rich_text if isinstance(span, dict)
    ).strip()


def iter_children(
    fetch_children: ChildrenFetcher,
    block_id: str,
    *,
    sleep: Callable[[float], None],
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> list[dict[str, Any]]:
    """Page through every child of a block, with exponential backoff on retry.

    `fetch_children(block_id, cursor)` returns a Notion-shaped response. It may
    raise to signal a retryable failure such as a rate limit.
    """
    collected: list[dict[str, Any]] = []
    cursor: Optional[str] = None

    while True:
        response = _fetch_with_backoff(
            fetch_children, block_id, cursor, sleep=sleep, max_retries=max_retries
        )
        results = response.get("results", [])
        if not isinstance(results, list):
            raise NotionIngestError(f"Malformed children payload for block {block_id}.")
        collected.extend(item for item in results if isinstance(item, dict))

        if not response.get("has_more"):
            return collected
        cursor = response.get("next_cursor")
        if not cursor:
            raise NotionIngestError(
                f"Block {block_id} reported has_more with no next_cursor; tree would be truncated."
            )


def _fetch_with_backoff(
    fetch_children: ChildrenFetcher,
    block_id: str,
    cursor: Optional[str],
    *,
    sleep: Callable[[float], None],
    max_retries: int,
) -> dict[str, Any]:
    delay = INITIAL_BACKOFF_SECONDS
    last_error: Optional[Exception] = None

    for attempt in range(max_retries):
        try:
            return fetch_children(block_id, cursor)
        except Exception as exc:  # retryable; re-raised below if attempts run out
            last_error = exc
            if attempt == max_retries - 1:
                break
            sleep(delay)
            delay *= 2

    raise NotionIngestError(
        f"Exhausted {max_retries} attempts fetching children of {block_id}: {last_error}"
    ) from last_error


def fetch_unit_tree(
    fetch_children: ChildrenFetcher,
    page_id: str,
    *,
    last_edited_time: str,
    sleep: Callable[[float], None] = lambda _seconds: None,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> UnitTree:
    """Fully paginate a page into one assembled tree. Read-only."""

    def build(block_id: str, block_type: str, text: str, depth: int, has_children: bool) -> UnitNode:
        if not has_children or depth >= max_depth:
            return UnitNode(block_id=block_id, block_type=block_type, text=text)
        children = iter_children(
            fetch_children, block_id, sleep=sleep, max_retries=max_retries
        )
        return UnitNode(
            block_id=block_id,
            block_type=block_type,
            text=text,
            children=tuple(
                build(
                    child.get("id", ""),
                    child.get("type", ""),
                    plain_text(child),
                    depth + 1,
                    bool(child.get("has_children")),
                )
                for child in children
            ),
        )

    root = build(page_id, "page", "", 0, True)
    return UnitTree(page_id=page_id, last_edited_time=last_edited_time, root=root)


def flatten_for_context(tree: UnitTree) -> str:
    """Render an assembled tree into one indented payload for a single call."""
    lines: list[str] = [f"# Notion page {tree.page_id} (edited {tree.last_edited_time})"]

    def emit(node: UnitNode, depth: int) -> None:
        for child in node.children:
            if child.text:
                lines.append(f"{'  ' * depth}- [{child.block_type}] {child.text}")
            emit(child, depth + 1)

    emit(tree.root, 0)
    return "\n".join(lines)


class UnitTreeCache:
    """Caches assembled trees keyed by `last_edited_time`.

    A changed edit time invalidates the entry, so re-runs skip refetching an
    unchanged page without ever serving stale content.
    """

    def __init__(self) -> None:
        self._entries: dict[str, UnitTree] = {}

    def get(self, page_id: str, last_edited_time: str) -> Optional[UnitTree]:
        cached = self._entries.get(page_id)
        if cached is None or cached.last_edited_time != last_edited_time:
            return None
        return cached

    def put(self, tree: UnitTree) -> None:
        self._entries[tree.page_id] = tree

    def invalidate(self, page_id: str) -> None:
        self._entries.pop(page_id, None)

    def __len__(self) -> int:
        return len(self._entries)
