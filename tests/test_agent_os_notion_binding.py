"""Regression coverage for the #2337 Notion binding composition root.

PR #2335 (and #2283's earlier activation commit) put the ``workflow_scheduler``
binding *inside* ``scripts/agent_os_notion_read_request``, breaking two
repository contracts at once: that package's own architecture boundary and the
repository-wide #752/#912 packaging allowlist. These tests pin the corrected
placement and the behaviour the seam must preserve.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCHEDULER_SRC = ROOT / "08_Tooling/workflow-scheduler/src"
for _path in (ROOT, ROOT / "src", SCHEDULER_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from agent_os_notion_binding import (  # noqa: E402
    READ_TASK_TYPE,
    NotionBindingError,
    build_read_task,
    new_read_adapter,
)
from workflow_scheduler.adapters.notion_readonly_adapter import (  # noqa: E402
    NotionReadOnlyAdapter,
)

NOTION_READ_PACKAGE = ROOT / "scripts" / "agent_os_notion_read_request"


class _TokenAdapter(NotionReadOnlyAdapter):
    def __init__(self) -> None:
        super().__init__(token="test-token")


def test_binding_lives_outside_the_scripts_boundary() -> None:
    """The composition root must not sit under `scripts/`.

    `scripts/**` is governed by the #752/#912 allowlist, so a binding placed
    there re-creates the exact #2337 failure.
    """
    module = sys.modules["agent_os_notion_binding"]
    location = Path(module.__file__).resolve()

    assert location.is_relative_to(ROOT / "src")
    assert not location.is_relative_to(ROOT / "scripts")


def test_bounded_read_package_declares_no_scheduler_dependency() -> None:
    """The #2283 read package keeps the Scheduler an injected concern."""
    offending = []
    for path in sorted(NOTION_READ_PACKAGE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level:
                names = [node.module or ""]
            else:
                continue
            if any(
                name == "workflow_scheduler" or name.startswith("workflow_scheduler.")
                for name in names
            ):
                offending.append(path.name)

    assert offending == []


def test_read_task_is_fixed_to_the_read_type_and_copies_its_payload() -> None:
    payload = {"action": "get_page", "page_id": "page-1"}

    task = build_read_task(
        task_id="agent-os-notion-read-get_page",
        workflow_id="agent-os-notion-read",
        owner="agent-os-notion-read-request",
        action="get_page",
        idempotency_key="agent-os-notion-read-get_page",
        payload=payload,
    )

    assert task.type == READ_TASK_TYPE == "read"
    assert task.action == "get_page"
    assert task.payload == payload
    # A copy, so a caller cannot mutate a dispatched task's payload.
    payload["page_id"] = "page-2"
    assert task.payload["page_id"] == "page-1"


def test_read_task_rejects_a_non_mapping_payload() -> None:
    with pytest.raises(TypeError, match="must be a mapping"):
        build_read_task(
            task_id="t",
            workflow_id="w",
            owner="o",
            action="get_page",
            idempotency_key="k",
            payload=[("action", "get_page")],  # type: ignore[arg-type]
        )


def test_adapter_construction_returns_the_canonical_reader() -> None:
    adapter = new_read_adapter(_TokenAdapter)

    assert isinstance(adapter, NotionReadOnlyAdapter)
    assert adapter.token == "test-token"


def test_missing_token_fails_closed_before_any_dispatch(monkeypatch) -> None:
    monkeypatch.delenv("NOTION_TOKEN", raising=False)

    with pytest.raises(NotionBindingError, match="NOTION_TOKEN is unavailable"):
        new_read_adapter()


def test_a_foreign_adapter_type_is_rejected() -> None:
    with pytest.raises(TypeError, match="must return NotionReadOnlyAdapter"):
        new_read_adapter(lambda: object())


def test_a_non_callable_adapter_factory_is_rejected() -> None:
    with pytest.raises(TypeError, match="adapter_factory must be callable"):
        new_read_adapter("not-callable")  # type: ignore[arg-type]
