"""Regression tests for three verified Curriculum Notion mutation-oracle gaps.

Validates fail-closed checks before invoking a credential-bearing executor.
Uses shipped local pytest fixtures and a fake catalog; never contacts Notion.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from scripts.agent_os_notion_read_request import (
    NotionReadRequestError,
    admit_notion_read_request,
)
from scripts.agent_os_notion_read_request.execution import (
    complete_records,
    execute_lesson_content,
)

from .notion_read_support import ACTOR, REPOSITORY, transport

ISSUE = 3580
REQUEST_ID = "candy-branding-lesson-content"
LOGICAL_SOURCE = "daily-generation-packet"


class NoDispatch:
    """A credential-bearing executor factory must never be invoked."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self):
        self.calls += 1
        raise AssertionError("unauthorized task executor factory invoked")


def admitted(shipped_catalog):
    decision = admit_notion_read_request(
        transport(request_id=REQUEST_ID, issue_number=ISSUE),
        catalog=shipped_catalog,
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
    )
    assert decision.status == "admitted"
    assert decision.secret_dispatch_authorized is True
    return decision


@pytest.mark.parametrize(
    ("status", "secret_authorized"),
    [("admitted", False), ("rejected", True)],
    ids=["admitted-but-unauthorized", "rejected-but-flagged-authorized"],
)
def test_g054_partial_admission_fails_before_executor(
    shipped_catalog, status: str, secret_authorized: bool
) -> None:
    """An OR -> AND mutation must not let either malformed pairing through."""
    forged = replace(
        admitted(shipped_catalog),
        status=status,
        secret_dispatch_authorized=secret_authorized,
    )
    factory = NoDispatch()
    with pytest.raises(NotionReadRequestError, match="requires an admitted"):
        execute_lesson_content(
            forged,
            catalog=shipped_catalog,
            scheduler_task_executor_factory=factory,
        )
    assert factory.calls == 0


def test_g059_present_but_unverified_source_fails_before_executor(
    shipped_catalog,
) -> None:
    """Do not infer authorization from presence of a logical-source binding."""
    decision = admitted(shipped_catalog)
    original = shipped_catalog.source(LOGICAL_SOURCE)
    assert original is not None and original.dispatchable
    unverified = replace(original, verification_state="unverified")
    altered_catalog = replace(
        shipped_catalog,
        sources=tuple(
            unverified if s.logical_source == LOGICAL_SOURCE else s
            for s in shipped_catalog.sources
        ),
    )
    assert altered_catalog.source(LOGICAL_SOURCE) == unverified
    assert not unverified.dispatchable

    factory = NoDispatch()
    with pytest.raises(NotionReadRequestError, match="not an approved binding"):
        execute_lesson_content(
            decision,
            catalog=altered_catalog,
            scheduler_task_executor_factory=factory,
        )
    assert factory.calls == 0


def test_g069_non_mapping_record_fails_as_typed_contract_error() -> None:
    """A malformed record list is rejected by the completeness helper itself."""
    adapter_output = {
        "results": [{"id": "valid-shaped-but-not-yet-verified"}, "not-a-record"],
        "has_more": False,
        "next_cursor": None,
    }
    with pytest.raises(NotionReadRequestError, match="missing results"):
        complete_records(adapter_output)
