"""Bounded execution seam for one admitted #2283 Notion read.

This module composes existing capabilities and adds none of its own:

- #2282 ``build_scheduler_fallback_read_executor`` / ``retrieve_curriculum_evidence``
  own execution-surface routing and the read-only action boundary;
- #980 owns request-sensitive read planning;
- #971 owns relation-first Visual Asset Library retrieval;
- #975 owns provider-neutral evidence assembly;
- #973 owns currentness, conflict, and authority resolution;
- #936 owns the read-only Notion adapter and the ``NOTION_TOKEN`` contract.

No Notion client, curriculum context engine, asset registry, cache, queue,
scheduler, retry loop, or source of truth is created here. Routine reads never
require GCE: the injected executor is supplied by the GitHub Actions job.
"""

from __future__ import annotations

from typing import Callable, Mapping

from instructional_workflow_contracts.common import thaw_json
from instructional_workflow_contracts.current_curriculum_state import (
    resolve_current_curriculum_state,
)
from navigation_registry.connectors.base import ConnectorError
from navigation_registry.connectors.curriculum_execution_surface_router import (
    FALLBACK_ROUTE,
    READ_ONLY_ACTIONS,
    build_scheduler_fallback_read_executor,
    retrieve_curriculum_evidence,
)
from navigation_registry.connectors.scheduler_notion_evidence import (
    SchedulerNotionEvidenceAdapter,
)

from .admission import build_curriculum_read_request
from .models import (
    CanonicalUnitBinding,
    NotionReadAdmission,
    NotionReadCatalog,
    NotionReadRequestError,
)

#: Zero-argument factory returning the bounded Scheduler read-task callable.
#: It is invoked only after ``secret_dispatch_authorized`` is proven true, so a
#: rejected admission never reaches the credential-bearing composition.
SchedulerTaskExecutorFactory = Callable[[], Callable[[Mapping[str, object]], object]]


def execute_admitted_notion_read(
    admission: NotionReadAdmission,
    *,
    catalog: NotionReadCatalog,
    scheduler_task_executor_factory: SchedulerTaskExecutorFactory,
    current_context: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Run one admitted bounded read and return normalized #973 state evidence."""
    if not isinstance(admission, NotionReadAdmission):
        raise NotionReadRequestError("admission evidence is required")
    if admission.status != "admitted" or admission.secret_dispatch_authorized is not True:
        # The single credential gate. The factory is deliberately untouched here.
        raise NotionReadRequestError(
            "secret-bearing dispatch requires an admitted #2283 request"
        )
    if not callable(scheduler_task_executor_factory):
        raise NotionReadRequestError("scheduler task executor factory must be callable")

    unit = catalog.canonical_unit(str(admission.canonical_unit_key))
    if unit is None or not unit.dispatchable:
        raise NotionReadRequestError("canonical unit binding is not dispatchable")

    request = build_curriculum_read_request(str(admission.request_class))

    def resolve_identity(logical_source: str) -> dict[str, object]:
        binding = catalog.source(logical_source)
        if binding is None or not binding.dispatchable:
            # Fail closed rather than broadening to another data source or a
            # workspace-wide search.
            raise NotionReadRequestError(
                f"logical source is not an approved binding: {logical_source!r}"
            )
        return {
            "logical_source": binding.logical_source,
            "data_source_id": binding.data_source_id,
            "human_review_required": False,
        }

    execute_task = _bounded_read_task_executor(scheduler_task_executor_factory())
    # Curriculum status is live Notion truth, resolved here through the canonical
    # normalizer so #973 decides disposition from the unit's actual state.
    unit_status = _resolve_live_unit_status(unit, execute_task)

    routed = retrieve_curriculum_evidence(
        request=request,
        canonical_unit={
            "stable_id": unit.stable_id,
            "status": unit_status,
            "provider_page_id": unit.provider_page_id,
        },
        resolve_identity=resolve_identity,
        # The GitHub-controlled job always uses the existing Agent OS read-only
        # reader; it never depends on a native ChatGPT Notion connector.
        native_notion_connector_available=False,
        fallback_factory=lambda: build_scheduler_fallback_read_executor(
            execute_scheduler_task=execute_task
        ),
        current_context=current_context,
    )

    packet = routed["curriculum_evidence"]
    state = resolve_current_curriculum_state(packet)
    if state.record is None:
        raise NotionReadRequestError("bounded read produced no #973 state record")

    return {
        "read_route": routed["read_route"],
        "expected_read_route": FALLBACK_ROUTE,
        "state_status": state.status.value,
        # Reuse the canonical inverse of #973's freeze step instead of writing a
        # second traversal of the same frozen structure.
        "state_payload": thaw_json(state.record.payload),
    }


def _bounded_read_task_executor(
    execute_task: object,
) -> Callable[[Mapping[str, object]], object]:
    """Refuse any action outside the inherited #2282 read-only bound.

    #2282 already bounds what it dispatches, but the canonical-unit resolution
    below calls the injected executor directly, and the #936 adapter's own action
    surface is wider than #2282's (it also exposes page-body and property reads).
    Re-asserting the bound from the canonical constant keeps every dispatch on
    this path inside it without restating the action set.
    """
    if not callable(execute_task):
        raise NotionReadRequestError("scheduler task executor must be callable")

    def execute(payload: Mapping[str, object]) -> object:
        action = payload.get("action") if isinstance(payload, Mapping) else None
        if action not in READ_ONLY_ACTIONS:
            raise NotionReadRequestError(
                f"action is outside the bounded read surface: {action!r}"
            )
        return execute_task(payload)

    return execute


def _resolve_live_unit_status(
    unit: CanonicalUnitBinding,
    execute_task: Callable[[Mapping[str, object]], object],
) -> str:
    """Resolve the canonical unit's #973 status from live evidence.

    The scheduler result is normalized by the canonical
    ``SchedulerNotionEvidenceAdapter``/``NotionContractAdapter`` pair, so archived
    and human-review detection stay owned upstream. This function only maps those
    canonical booleans onto the existing #973 status vocabulary; it classifies
    nothing itself.
    """
    result = execute_task({"action": "get_page", "page_id": unit.provider_page_id})
    resource = SchedulerNotionEvidenceAdapter().from_scheduler_result("get_page", result)
    if isinstance(resource, ConnectorError):
        raise NotionReadRequestError(
            f"canonical unit evidence is unavailable: {resource.message}"
        )
    if resource.canonical_id != unit.provider_page_id:
        raise NotionReadRequestError("canonical unit identity mismatch")

    if resource.metadata.get("archived") is True:
        return "archived"
    if resource.human_review_required:
        return "human-review-required"
    return "active"


__all__ = ["SchedulerTaskExecutorFactory", "execute_admitted_notion_read"]
