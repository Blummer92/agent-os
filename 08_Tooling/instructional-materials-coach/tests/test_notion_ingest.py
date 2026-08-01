"""Pagination, backoff, deep trees, and cache invalidation for Notion ingest.

Dependency-free: HTTP is injected, so these run on a default install.
"""
from __future__ import annotations

import pytest

from instructional_materials_coach.notion_ingest import (
    NotionIngestError,
    UnitTreeCache,
    fetch_unit_tree,
    flatten_for_context,
    iter_children,
    plain_text,
)


def block(block_id, text="", block_type="paragraph", has_children=False):
    return {
        "id": block_id,
        "type": block_type,
        "has_children": has_children,
        block_type: {"rich_text": [{"plain_text": text}]},
    }


def page(results, *, has_more=False, next_cursor=None):
    return {"results": results, "has_more": has_more, "next_cursor": next_cursor}


# --- text extraction -------------------------------------------------------


def test_plain_text_extracts_rich_text():
    assert plain_text(block("b1", "Hello world")) == "Hello world"


def test_plain_text_tolerates_unknown_block_shapes():
    assert plain_text({"type": "unsupported"}) == ""
    assert plain_text({}) == ""


# --- pagination ------------------------------------------------------------


def test_iter_children_follows_every_cursor():
    pages = {
        None: page([block("a")], has_more=True, next_cursor="c1"),
        "c1": page([block("b")], has_more=True, next_cursor="c2"),
        "c2": page([block("c")]),
    }
    calls = []

    def fetch(block_id, cursor):
        calls.append(cursor)
        return pages[cursor]

    results = iter_children(fetch, "root", sleep=lambda _s: None)
    assert [r["id"] for r in results] == ["a", "b", "c"]
    assert calls == [None, "c1", "c2"]


def test_has_more_without_cursor_raises_rather_than_truncating():
    def fetch(block_id, cursor):
        return page([block("a")], has_more=True, next_cursor=None)

    with pytest.raises(NotionIngestError, match="truncated"):
        iter_children(fetch, "root", sleep=lambda _s: None)


def test_malformed_results_payload_raises():
    def fetch(block_id, cursor):
        return {"results": "not-a-list"}

    with pytest.raises(NotionIngestError, match="Malformed"):
        iter_children(fetch, "root", sleep=lambda _s: None)


# --- backoff ---------------------------------------------------------------


def test_retries_with_exponential_backoff_then_succeeds():
    attempts = {"n": 0}
    delays = []

    def fetch(block_id, cursor):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("429 rate limited")
        return page([block("a")])

    iter_children(fetch, "root", sleep=delays.append)
    assert attempts["n"] == 3
    assert delays == [0.5, 1.0], "delay must double between attempts"


def test_exhausted_retries_raise_with_context():
    def fetch(block_id, cursor):
        raise RuntimeError("429 rate limited")

    with pytest.raises(NotionIngestError, match="Exhausted 5 attempts"):
        iter_children(fetch, "root", sleep=lambda _s: None)


# --- tree assembly ---------------------------------------------------------


def test_leaf_blocks_are_not_refetched():
    fetched = []

    def fetch(block_id, cursor):
        fetched.append(block_id)
        if block_id == "page1":
            return page([block("leaf", "Only child")])
        raise AssertionError(f"should not fetch children of leaf {block_id}")

    tree = fetch_unit_tree(fetch, "page1", last_edited_time="t0")
    assert fetched == ["page1"]
    assert tree.block_count() == 2  # root + leaf


def test_deep_tree_is_assembled_and_depth_capped():
    def fetch(block_id, cursor):
        # Every block claims one child, so depth is bounded only by max_depth.
        return page([block(f"{block_id}-child", "deep", has_children=True)])

    tree = fetch_unit_tree(fetch, "page1", last_edited_time="t0", max_depth=4)
    assert tree.block_count() == 5  # root + 4 levels


def test_flatten_renders_indented_payload():
    def fetch(block_id, cursor):
        if block_id == "page1":
            return page([block("h", "Heading", has_children=True)])
        return page([block("b", "Bullet")])

    tree = fetch_unit_tree(fetch, "page1", last_edited_time="t0")
    text = flatten_for_context(tree)
    assert "Heading" in text and "Bullet" in text
    assert text.index("Heading") < text.index("Bullet")


# --- cache -----------------------------------------------------------------


def test_cache_hits_on_same_edit_time():
    def fetch(block_id, cursor):
        return page([])

    cache = UnitTreeCache()
    tree = fetch_unit_tree(fetch, "page1", last_edited_time="t0")
    cache.put(tree)
    assert cache.get("page1", "t0") is tree


def test_cache_invalidates_when_edit_time_changes():
    def fetch(block_id, cursor):
        return page([])

    cache = UnitTreeCache()
    cache.put(fetch_unit_tree(fetch, "page1", last_edited_time="t0"))
    assert cache.get("page1", "t1") is None, "stale content must never be served"


def test_cache_miss_on_unknown_page():
    assert UnitTreeCache().get("nope", "t0") is None


def test_module_exposes_no_write_verb():
    import instructional_materials_coach.notion_ingest as mod

    for banned in ("create", "update", "delete", "archive", "patch", "append"):
        assert not any(banned in name.lower() for name in dir(mod)), banned
