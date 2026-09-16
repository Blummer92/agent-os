"""Bounded Agent OS curriculum and visual-asset reads (#2282 / #2303).

Agent OS has one supported execution route for these reads: the existing governed
read-only Notion reader used by the GitHub-controlled #2283 path. The retired
native/direct ChatGPT Notion connector is not an execution surface here.

This module adapts injected Scheduler read tasks to the existing #980 orchestration
without adding a Notion client, curriculum context engine, asset registry, cache,
scheduler, retry loop, or source of truth. Request sensitivity, relation-first
Visual Asset Library lookup, and authority/safe-use semantics remain owned by
#980/#975/#973/#971. Credentials and live source sharing remain #2283 concerns.
"""

from __future__ import annotations

from typing import Callable, Mapping

from .curriculum_evidence_orchestrator import (
    MAX_RESULTS,
    CurriculumReadError,
    CurriculumReadRequest,
    CurriculumReadStep,
    ReadExecutor,
    orchestrate_curriculum_evidence,
)

# Preserve the existing public evidence value while removing the obsolete
# native-vs-fallback choice that originally gave the label its name.
FALLBACK_ROUTE = "agent-os-notion-reader"

READ_ONLY_ACTIONS = frozenset({"get_page", "query_data_source"})

SchedulerTaskExecutor = Callable[[Mapping[str, object]], object]


class CurriculumSurfaceError(CurriculumReadError):
    """Fail-closed governed read-surface error."""


def build_scheduler_fallback_read_executor(
    *,
    execute_scheduler_task: SchedulerTaskExecutor,
) -> ReadExecutor:
    """Adapt the canonical #936 Scheduler read path to the #980 read seam."""
    if not callable(execute_scheduler_task):
        raise CurriculumSurfaceError("scheduler task executor must be callable")

    def execute_read(step: CurriculumReadStep, payload: Mapping[str, object]) -> object:
        action = _read_only_action(step)
        task_payload = _scheduler_task_payload(action, payload)
        result = execute_scheduler_task(task_payload)
        return _normalize_scheduler_result(result, action)

    return execute_read


def retrieve_curriculum_evidence(
    *,
    request: CurriculumReadRequest,
    canonical_unit: Mapping[str, object],
    resolve_identity: Callable[[str], Mapping[str, object]],
    execute_read: ReadExecutor,
    current_context: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Run one bounded retrieval through the single governed Agent OS reader."""
    if not callable(execute_read):
        raise CurriculumSurfaceError("Agent OS read executor must be callable")

    packet = orchestrate_curriculum_evidence(
        request=request,
        canonical_unit=canonical_unit,
        resolve_identity=resolve_identity,
        execute_read=execute_read,
        current_context=current_context,
    )
    return {
        "read_route": FALLBACK_ROUTE,
        "curriculum_evidence": packet,
    }


def _read_only_action(step: CurriculumReadStep) -> str:
    action = getattr(step, "action", None)
    if not isinstance(action, str) or action not in READ_ONLY_ACTIONS:
        raise CurriculumSurfaceError(f"unsupported non-read action: {action!r}")
    return action


def _scheduler_task_payload(action: str, payload: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        raise CurriculumSurfaceError("read payload must be a mapping")

    if action == "get_page":
        return {
            "action": "get_page",
            "page_id": _required_text(
                payload.get("canonical_unit_provider_id"),
                "canonical_unit_provider_id",
            ),
        }

    identity = payload.get("identity")
    if not isinstance(identity, Mapping):
        raise CurriculumSurfaceError("read payload is missing resolved identity")
    data_source_id = _required_text(identity.get("data_source_id"), "identity.data_source_id")
    bound = _bounded_results(payload.get("max_results"))

    task_payload: dict[str, object] = {
        "action": "query_data_source",
        "data_source_id": data_source_id,
        "page_size": bound,
        "max_pages": 1,
        "max_results": bound,
    }
    relation_filter = payload.get("relation_filter")
    if relation_filter is not None:
        task_payload["filter"] = _relation_filter(relation_filter)
    return task_payload


def _relation_filter(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise CurriculumSurfaceError("relation filter must be a mapping")
    return {
        "property": _required_text(value.get("property"), "relation_filter.property"),
        "relation": {
            "contains": _required_text(
                value.get("contains_page_id"), "relation_filter.contains_page_id"
            )
        },
    }


def _normalize_scheduler_result(result: object, action: str) -> dict[str, object]:
    if not isinstance(result, Mapping):
        raise CurriculumSurfaceError("scheduler result must be a mapping")

    status = str(result.get("status") or "").strip().lower()
    if status != "success":
        return {
            "status": "unresolved",
            "provider_status": status or "missing",
            "provider_message": str(result.get("message") or ""),
        }

    output = result.get("output")
    if not isinstance(output, Mapping):
        raise CurriculumSurfaceError("successful scheduler result is missing output")

    if action == "get_page":
        return dict(output)

    results = output.get("results")
    if not isinstance(results, list):
        raise CurriculumSurfaceError("scheduler query output is missing results")
    for record in results:
        if not isinstance(record, Mapping):
            raise CurriculumSurfaceError("scheduler query returned a malformed record")
    return {"results": [dict(record) for record in results]}


def _bounded_results(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CurriculumSurfaceError("max_results must be an exact integer")
    if value < 1 or value > MAX_RESULTS:
        raise CurriculumSurfaceError("max_results exceeds the bounded read limit")
    return value


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CurriculumSurfaceError(f"missing required {field}")
    return value.strip()


__all__ = [
    "FALLBACK_ROUTE",
    "READ_ONLY_ACTIONS",
    "CurriculumSurfaceError",
    "build_scheduler_fallback_read_executor",
    "retrieve_curriculum_evidence",
]
