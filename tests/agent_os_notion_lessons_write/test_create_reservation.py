"""Offline contract: one permanent create claim even when Notion indexing lags."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import io
import json
import threading
import urllib.error
from unittest.mock import patch

import pytest

from scripts.agent_os_notion_lessons_write import catalog
from scripts.agent_os_notion_lessons_write.admission import AdmittedRequest, WriteBlocked
from scripts.agent_os_notion_lessons_write.create_reservation import (
    REF_PREFIX, reservation_ref, reserve_once,
)
from scripts.agent_os_notion_lessons_write.writer import execute
from tests.agent_os_notion_lessons_write.test_writer import Client

SHA = "a" * 40


class _Reply(io.BytesIO):
    status = 201


class AtomicRefs:
    """Fake the POST /git/refs create-only conflict, not a query-then-create."""
    def __init__(self):
        self.names = set()
        self.requests = []
        self.lock = threading.Lock()
        self.reject = None
        self.malformed = False

    def open(self, req, timeout):
        assert req.method == "POST"
        assert req.full_url == "https://api.github.com/repos/Blummer92/agent-os/git/refs"
        assert timeout == 15
        assert req.get_header("Authorization") == "Bearer synthetic-github-token"
        assert req.get_header("Content-type") == "application/json"
        value = json.loads(req.data)
        ref = value["ref"]
        assert ref.startswith(REF_PREFIX)
        assert value["sha"] == SHA
        with self.lock:
            self.requests.append(ref)
            if self.reject is not None:
                raise urllib.error.HTTPError(req.full_url, self.reject, "unavailable", {}, None)
            if ref in self.names:
                raise urllib.error.HTTPError(req.full_url, 422, "already exists", {}, None)
            self.names.add(ref)
        result = {"ref": ref, "object": {"sha": SHA}}
        if self.malformed:
            result["ref"] = "refs/tags/not-ours"
        return _Reply(json.dumps(result).encode())


def reserve(store, request_id=catalog.REQUEST_ID):
    return reserve_once(
        request_id, token="synthetic-github-token",
        commit_sha=SHA, opener=store,
    )


def test_atomic_tag_reference_refuses_duplicate_even_when_second_request_is_authorized():
    store = AtomicRefs()
    reserve(store)
    with pytest.raises(WriteBlocked, match="^create-reservation-already-exists$"):
        reserve(store)
    assert len(store.names) == 1
    assert len(store.requests) == 2


def test_concurrent_claimers_get_exactly_one_winner():
    store = AtomicRefs()
    def attempt(_):
        try:
            reserve(store)
            return "acquired"
        except WriteBlocked as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(8)))
    assert results.count("acquired") == 1
    assert results.count("create-reservation-already-exists") == 7
    assert len(store.names) == 1


def test_title_canonicalization_and_cross_request_deduplication():
    template = dict(catalog.lesson_for(catalog.REQUEST_ID))
    title = template["Lesson Learned"]
    first = {"target_lesson_id": None, "properties": dict(template)}
    second = {"target_lesson_id": None, "properties": {**template,
              "Lesson Learned": "  " + title.swapcase() + "  "}}
    # The real catalog rejects leading/trailing whitespace? Only use these
    # dummy values when testing key derivation, never as permission to publish.
    with patch.object(catalog, "LESSONS", {"first": first, "second": second}):
        assert reservation_ref("first") == reservation_ref("second")
        store = AtomicRefs()
        reserve(store, "first")
        with pytest.raises(WriteBlocked, match="create-reservation-already-exists"):
            reserve(store, "second")


def test_missing_or_unavailable_github_reservation_never_counts_as_success():
    for situation in ("missing-token", "invalid-sha", "permission", "lost-receipt"):
        store = AtomicRefs()
        if situation == "permission":
            store.reject = 403
        if situation == "lost-receipt":
            store.malformed = True
        with pytest.raises(WriteBlocked) as captured:
            reserve_once(
                catalog.REQUEST_ID,
                token="" if situation == "missing-token" else "synthetic-github-token",
                commit_sha="bad" if situation == "invalid-sha" else SHA,
                opener=store,
            )
        assert str(captured.value).startswith("create-reservation-")
        if situation == "lost-receipt":
            # The ref may have been committed even though the receipt was lost.
            assert len(store.names) == 1
            with pytest.raises(WriteBlocked, match="already-exists"):
                reserve(store)
        else:
            assert len(store.names) == 0


def test_update_entry_cannot_consume_a_create_reservation():
    with pytest.raises(WriteBlocked, match="create-reservation-not-applicable"):
        reservation_ref(catalog.LL93_METADATA_REQUEST_ID)


def test_lagging_notion_index_cannot_perform_second_post_after_uncertain_first_post():
    store = AtomicRefs()

    class LaggedIndex(Client):
        def reserve_create(self, request_id):
            reserve(store, request_id)

        def find_exact(self, title):
            # Simulate the same empty query index on both owner requests,
            # even after the first POST has already committed.
            self.calls.append("query")
            return {"results": [], "has_more": False}

    client = LaggedIndex()
    client.raise_mutation = True
    first = execute(AdmittedRequest(100), client)
    assert first["status"] == "uncertain"
    assert first["write_attempts"] == 1
    assert first["recovery_reason"] == "recovery-not-visible"
    assert first["create_reservation_acquired"] is True
    assert client.calls.count("write") == 1
    assert client.page is not None  # first POST committed remotely

    # The next separately admitted owner request still sees empty Notion
    # results, but GitHub's permanent create-only ref blocks another POST.
    client.raise_mutation = False
    second = execute(AdmittedRequest(101), client)
    assert second["status"] == "blocked"
    assert second["reason_code"] == "create-reservation-already-exists"
    assert second["write_attempts"] == 0
    assert client.calls.count("write") == 1
    assert len(store.names) == 1


def test_readonly_reconciliation_unchanged_needs_no_second_reservation():
    store = AtomicRefs()
    class Existing(Client):
        def reserve_create(self, request_id):
            raise AssertionError("never reserve if a canonical lesson already exists")
    from tests.agent_os_notion_lessons_write.test_writer import page
    result = execute(AdmittedRequest(102), Existing(page()))
    assert result["status"] == "unchanged"
    assert result["write_attempts"] == 0
    assert len(store.names) == 0
