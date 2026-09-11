"""Execution-surface routing for bounded curriculum and visual-asset reads (#2282).

#2282 decides only *which execution surface* performs the bounded reads that the
existing #980 orchestration already plans:

    native ChatGPT Notion available
      -> host-supplied native read executor
    native ChatGPT Notion unavailable
      -> bounded Scheduler read payloads for the canonical #936
         ``NotionReadOnlyAdapter``, injected by the caller

Both surfaces feed the same #980 -> #975 -> #973 path, so the assembled
curriculum evidence is provider-neutral and identical across routes. This module
adds no Notion client, curriculum context engine, current-state model, asset
registry, cache, or source of truth, and it does not re-plan reads: request
sensitivity, relation-first Visual Asset Library lookup, and all authority and
safe-use semantics stay owned by #980/#975/#973/#971.

Provider-specific compact Notion ids and Notion filter syntax stay inside this
seam, exactly as they already do inside #980's provider payloads. Following the
established Navigation Registry boundary, this module never imports the Workflow
Scheduler: the Scheduler remains the canonical live-read executor and the caller
injects it. Supplying a live executor, its credentials, and its source sharing
belongs to #2283, not here.
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

NATIVE_ROUTE = "native-notion-connector"
FALLBACK_ROUTE = "agent-os-notion-reader"

# The canonical #936 read actions this seam may ask the Scheduler to perform.
# Anything else — including every mutation — fails closed before dispatch.
READ_ONLY_ACTIONS = frozenset({"get_page", "query_data_source"})

SchedulerTaskExecutor = Callable[[Mapping[str, object]], object]
FallbackFactory = Callable[[], ReadExecutor]


class CurriculumSurfaceError(CurriculumReadError):
    """Fail-closed execution-surface routing error.

    Subclasses the existing #980 error so callers keep one fail-closed family
    instead of gaining a second error taxonomy.
    """


def build_scheduler_fallback_read_executor(
    *,
    execute_scheduler_task: SchedulerTaskExecutor,
) -> ReadExecutor:
    """Adapt the canonical #936 Scheduler read path to the #980 read seam.

    ``execute_scheduler_task`` receives one bounded read-only Scheduler payload
    and returns the Scheduler's existing five-state result mapping. This function
    builds those payloads and normalizes those results; it constructs no client,
    reads no credentials, performs no network access, and never retries.
    """
    if not callable(execute_scheduler_task):
        raise CurriculumSurfaceError("scheduler task executor must be callable")

    def execute_read(step: CurriculumReadStep, payload: Mapping[str, object]) -> object:
        action = _read_only_action(step)
        task_payload = _scheduler_task_payload(action, payload)
        result = execute_scheduler_task(task_payload)
        return _normalize_scheduler_result(result, action)

    return execute_read


def select_curriculum_read_executor(
    *,
    native_notion_connector_available: bool,
    native_execute_read: ReadExecutor | None = None,
    fallback_factory: FallbackFactory | None = None,
) -> tuple[str, ReadExecutor]:
    """Choose the execution surface for one bounded curriculum retrieval.

    Capability state is explicit caller evidence. The fallback composition stays
    lazy: it is never built while the native connector is available.
    """
    if type(native_notion_connector_available) is not bool:
        raise CurriculumSurfaceError(
            "native_notion_connector_available must be a built-in bool"
        )

    if native_notion_connector_available:
        if not callable(native_execute_read):
            raise CurriculumSurfaceError(
                "native route requires a host-supplied read executor"
            )
        return NATIVE_ROUTE, native_execute_read

    if not callable(fallback_factory):
        raise CurriculumSurfaceError(
            "fallback route requires the existing Agent OS reader composition"
        )
    executor = fallback_factory()
    if not callable(executor):
        raise CurriculumSurfaceError("fallback reader composition is unavailable")
    return FALLBACK_ROUTE, executor


def retrieve_curriculum_evidence(
    *,
    request: CurriculumReadRequest,
    canonical_unit: Mapping[str, object],
    resolve_identity: Callable[[str], Mapping[str, object]],
    native_notion_connector_available: bool,
    native_execute_read: ReadExecutor | None = None,
    fallback_factory: FallbackFactory | None = None,
    current_context: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Run one bounded curriculum retrieval through the selected surface.

    The returned ``curriculum_evidence`` is the unmodified #975 packet, so #973
    remains the only current-state/authority resolver. The route label is
    execution-surface evidence and carries no authority of its own.
    """
    route, execute_read = select_curriculum_read_executor(
        native_notion_connector_available=native_notion_connector_available,
        native_execute_read=native_execute_read,
        fallback_factory=fallback_factory,
    )
    packet = orchestrate_curriculum_evidence(
        request=request,
        canonical_unit=canonical_unit,
        resolve_identity=resolve_identity,
        execute_read=execute_read,
        current_context=current_context,
    )
    return {
        "read_route": route,
        "native_notion_connector_available": native_notion_connector_available,
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
    # A missing source binding fails closed here rather than guessing another
    # data source or broadening to a workspace search. Supplying it is #2283's.
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
        # Surface non-success as an explicit unresolved provider state so the
        # existing #980 fail-closed handling rejects it instead of assembling
        # partial curriculum evidence.
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
    "NATIVE_ROUTE",
    "READ_ONLY_ACTIONS",
    "CurriculumSurfaceError",
    "build_scheduler_fallback_read_executor",
    "retrieve_curriculum_evidence",
    "select_curriculum_read_executor",
]
