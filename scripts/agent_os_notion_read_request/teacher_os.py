"""Teacher OS read seam over the existing governed Notion reader (#2801, #3580, #2283).

Teacher OS discovers approved units and reads their current lessons from Notion
instead of repository-owned lesson data. This module adds no Notion client,
store, cache or credential handling: it composes pieces that already exist.

- the approved source allowlist and identity binding stay in the catalog
  (``canonical-unit`` for discovery, ``daily-generation-packet`` for lessons);
  an unverified or unbound source fails closed before any query is built;
- the action bound, relation filter, completeness proof, duplicate and
  per-record unit-identity validation are the exact ones the issue-comment
  lesson path uses (``execution.query_unit_lesson_records``);
- the 7 governed lesson fields come from ``projection.project_lesson_records``;
- the credential is read only by the existing #936 adapter, behind the lazy
  ``build_live_notion_executor_factory``, and never appears in any output.

A unit is readable only if the live, verified ``canonical-unit`` source lists
it, so adding an approved unit in Notion needs no repository edit while a page
that is not in that source is rejected (``unit-not-approved``). Every failure
is reported as a closed ``reason_code``; nothing falls back to other content.
Reads only: no Notion, Drive or classroom write exists on this path.
"""

from __future__ import annotations

import argparse
import json
import re
from typing import Callable, Mapping

from .catalog import load_catalog
from .execution import (
    SchedulerTaskExecutorFactory,
    _bounded_read_task_executor,
    complete_records,
    lesson_unit_filter,
    query_unit_lesson_records,
)
from .live_executor import build_live_notion_executor_factory
from .models import SCHEMA_VERSION, NotionReadCatalog, NotionReadRequestError, NotionReadSource
from .projection import _dashed_uuid, _plain_text_segments, project_lesson_records, reject_credential_keys
from navigation_registry.connectors.curriculum_execution_surface_router import MAX_RESULTS

RESULT_KIND = "agent-os-teacher-os-read-result"
UNIT_SOURCE = "canonical-unit"
#: Live canonical-unit registry schema: only an Active unit that needs no human review is approved.
UNIT_STATUS_PROPERTY, UNIT_APPROVED_STATUS = "Canonical Status", "Active"
UNIT_REVIEW_PROPERTY = "Human Review Required"
LESSON_SOURCE = "daily-generation-packet"
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}$")

class TeacherOsReadError(Exception):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _source(catalog: NotionReadCatalog, logical_source: str) -> NotionReadSource:
    binding = catalog.source(logical_source)
    if binding is None or not binding.dispatchable:
        raise TeacherOsReadError("source-unverified")
    return binding


def _bound_executor(factory: SchedulerTaskExecutorFactory) -> Callable[[Mapping[str, object]], object]:
    try:
        return _bounded_read_task_executor(factory())
    except NotionReadRequestError as exc:
        raise TeacherOsReadError("not-configured") from exc


def _approved(properties: object) -> bool:
    """Fail closed: a unit is approved only when its status is exactly Active and review is not required."""
    if not isinstance(properties, Mapping):
        return False
    status, review = properties.get(UNIT_STATUS_PROPERTY), properties.get(UNIT_REVIEW_PROPERTY)
    option = status.get("select") if isinstance(status, Mapping) and status.get("type") == "select" else None
    if not isinstance(option, Mapping) or option.get("name") != UNIT_APPROVED_STATUS:
        return False
    return (
        isinstance(review, Mapping)
        and review.get("type") == "checkbox"
        and review.get("checkbox") is False
    )


def _unit_index(binding: NotionReadSource, execute_task: Callable[[Mapping[str, object]], object]) -> list[dict[str, str]]:
    """Live-discover approved units: one bounded, unfiltered query of the verified unit source."""
    result = execute_task({
        "action": "query_data_source",
        "data_source_id": binding.data_source_id,
        "page_size": MAX_RESULTS,
        "max_pages": 5,
        "max_results": MAX_RESULTS + 1,
    })
    if not isinstance(result, Mapping) or str(result.get("status") or "").strip().lower() != "success":
        raise TeacherOsReadError("read-failed")
    output = result.get("output")
    if not isinstance(output, Mapping):
        raise TeacherOsReadError("read-failed")
    units: dict[str, dict[str, str]] = {}
    for record in complete_records(output):
        if record.get("archived") is True or record.get("in_trash") is True:
            continue
        properties = record.get("properties")
        if not _approved(properties):
            continue
        title = next(
            (
                _plain_text_segments(prop.get("title"))
                for prop in (properties.values() if isinstance(properties, Mapping) else ())
                if isinstance(prop, Mapping) and prop.get("type") == "title"
            ),
            None,
        )
        record_id = record.get("id")
        if not isinstance(record_id, str) or not title:
            raise NotionReadRequestError("unit record has no valid id or title")
        unit_id = _dashed_uuid(record_id)
        if unit_id in units:
            raise NotionReadRequestError("unit retrieval returned a duplicate record")
        units[unit_id] = {"unit_id": unit_id, "title": title}
    return sorted(units.values(), key=lambda unit: unit["title"].casefold())


def _envelope(catalog: NotionReadCatalog, logical_source: str, generated_at: str, **body: object) -> dict[str, object]:
    binding = catalog.source(logical_source)
    assert binding is not None
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "result_kind": RESULT_KIND,
        "status": "ok" if body.get("units") or body.get("lessons") else "empty",
        "source": {
            "logical_source": binding.logical_source,
            "display_name": binding.display_name,
            "verification_state": binding.verification_state,
            "access": "read-only",
        },
        **body,
        "generated_at": generated_at,
    }
    reject_credential_keys(payload)
    return payload


def read_units(catalog: NotionReadCatalog, factory: SchedulerTaskExecutorFactory, *, generated_at: str) -> dict[str, object]:
    binding = _source(catalog, UNIT_SOURCE)
    units = _unit_index(binding, _bound_executor(factory))
    return _envelope(catalog, UNIT_SOURCE, generated_at, units=units)


def read_unit_lessons(
    catalog: NotionReadCatalog, factory: SchedulerTaskExecutorFactory, unit_id: str, *, generated_at: str
) -> dict[str, object]:
    if not isinstance(unit_id, str) or not _UUID_RE.fullmatch(unit_id):
        raise TeacherOsReadError("invalid-request")
    unit_page_id = _dashed_uuid(unit_id)
    unit_binding = _source(catalog, UNIT_SOURCE)
    lesson_binding = _source(catalog, LESSON_SOURCE)
    execute_task = _bound_executor(factory)
    # The browser-supplied id is never trusted: it must be listed live by the verified unit source.
    approved = _unit_index(unit_binding, execute_task)
    unit = next((u for u in approved if u["unit_id"] == unit_page_id), None)
    if unit is None:
        raise TeacherOsReadError("unit-not-approved")
    records = query_unit_lesson_records(lesson_binding, unit_page_id, lesson_unit_filter(unit_page_id), execute_task)
    envelope = _envelope(
        catalog, LESSON_SOURCE, generated_at,
        unit=unit, lessons=project_lesson_records(list(records), unit_page_id),
    )
    return envelope


def run(argv: list[str] | None = None, *, factory: SchedulerTaskExecutorFactory | None = None) -> tuple[int, dict[str, object]]:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("units")
    lessons = sub.add_parser("lessons")
    lessons.add_argument("--unit-id", required=True)
    parser.add_argument("--generated-at", required=True)
    args = parser.parse_args(argv)
    catalog = load_catalog(sources_only=True)
    live = factory if factory is not None else build_live_notion_executor_factory()
    try:
        if args.command == "units":
            return 0, read_units(catalog, live, generated_at=args.generated_at)
        return 0, read_unit_lessons(catalog, live, args.unit_id, generated_at=args.generated_at)
    except TeacherOsReadError as exc:
        reason = exc.reason_code
    except Exception:  # provider/validation text is never published
        reason = "read-failed"
    status = "unavailable" if reason in ("not-configured", "source-unverified") else "error"
    return 1, {"schema_version": SCHEMA_VERSION, "result_kind": RESULT_KIND, "status": status, "reason_code": reason}


def main(argv: list[str] | None = None) -> int:
    code, payload = run(argv)
    print(json.dumps(payload, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
