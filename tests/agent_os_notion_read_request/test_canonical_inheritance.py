"""Composition proofs that #2298 traverses the canonical Agent OS pipeline.

Every test here is designed to fail if #2298 stops reaching a canonical owner
and starts deciding something itself. They are deliberately few and strong: the
canonical unit tests for #980/#975/#973/#971 already exist and are not copied.

The question each test answers is: when Agent OS fixes a curriculum, asset,
currentness, or authority bug in its canonical owner, does the GitHub-to-Notion
path inherit that fix automatically?
"""

from __future__ import annotations

import pytest

from instructional_workflow_contracts import current_curriculum_evidence
from instructional_workflow_contracts import current_curriculum_state
from instructional_workflow_contracts.current_curriculum_evidence import (
    _request_mode as assembler_mode,
)
from navigation_registry.connectors import curriculum_evidence_orchestrator
from navigation_registry.connectors.curriculum_evidence_orchestrator import (
    CurriculumReadRequest,
    _request_mode as planner_mode,
)
from scripts.agent_os_notion_read_request import (
    REQUEST_CLASSES,
    REQUEST_CLASS_INTENT,
    NotionReadRequestError,
    build_curriculum_read_request,
    run_notion_read_request,
)
from scripts.agent_os_notion_read_request import execution as execution_module

from .notion_read_support import (
    ACTOR,
    GENERATED_AT,
    REPOSITORY,
    RecordingExecutor,
    transport,
    unit_page,
)


def run(catalog, executor, **kwargs):
    return run_notion_read_request(
        kwargs.pop("payload", transport()),
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
        generated_at=GENERATED_AT,
        catalog=catalog,
        scheduler_task_executor_factory=executor.factory,
        **kwargs,
    )


# --------------------------------------------------------------------------
# The canonical components are actually invoked
# --------------------------------------------------------------------------


def test_request_planning_is_performed_by_the_canonical_980_planner(
    verified_catalog, monkeypatch
) -> None:
    """#2298 must not carry its own read plan."""
    seen: list[object] = []
    canonical = curriculum_evidence_orchestrator.build_curriculum_read_plan

    def spy(request):
        seen.append(request)
        return canonical(request)

    monkeypatch.setattr(
        curriculum_evidence_orchestrator, "build_curriculum_read_plan", spy
    )

    run(verified_catalog, RecordingExecutor())

    assert seen, "the canonical #980 planner was never invoked"
    assert all(isinstance(request, CurriculumReadRequest) for request in seen)


def test_evidence_assembly_is_performed_by_the_canonical_975_assembler(
    verified_catalog, monkeypatch
) -> None:
    """#2298 must not assemble curriculum evidence itself."""
    calls: list[dict] = []
    canonical = current_curriculum_evidence.assemble_current_curriculum_evidence

    def spy(**kwargs):
        calls.append(kwargs)
        return canonical(**kwargs)

    monkeypatch.setattr(
        curriculum_evidence_orchestrator,
        "assemble_current_curriculum_evidence",
        spy,
    )

    run(verified_catalog, RecordingExecutor())

    assert len(calls) == 1, "the canonical #975 assembler was never invoked"
    assert "asset_evidence" in calls[0]


def test_authority_and_disposition_come_from_the_canonical_973_resolver(
    verified_catalog, monkeypatch
) -> None:
    """The published disposition must be #973's, not #2298's."""
    calls: list[object] = []
    canonical = current_curriculum_state.resolve_current_curriculum_state

    def spy(evidence):
        calls.append(evidence)
        return canonical(evidence)

    monkeypatch.setattr(execution_module, "resolve_current_curriculum_state", spy)

    evidence = run(verified_catalog, RecordingExecutor())

    assert calls, "the canonical #973 resolver was never invoked"
    assert evidence["result"]["currentness"]["state_id"]
    assert evidence["result"]["currentness"]["contract_version"] == (
        current_curriculum_state.CONTRACT_ID
    )


# --------------------------------------------------------------------------
# Canonical protections remain reachable through #2298's vocabulary
# --------------------------------------------------------------------------


@pytest.mark.parametrize("request_class", REQUEST_CLASSES)
def test_request_class_intent_stays_consistent_across_planner_and_assembler(
    request_class: str,
) -> None:
    """Inherit the canonical planner/assembler mode-consistency invariant.

    ``tests/test_curriculum_request_mode_consistency.py`` locks this for its own
    parameter list; #2298 introduces five new (action, artifact_type) pairs that
    must satisfy the same invariant, or the path would plan one mode and
    assemble another.
    """
    intent = REQUEST_CLASS_INTENT[request_class]
    request = build_curriculum_read_request(request_class)

    assert request.action == intent["action"]
    assert request.artifact_type == intent["artifact_type"]
    assert planner_mode(request) == assembler_mode(
        request.action, request.artifact_type
    )


@pytest.mark.parametrize(
    ("page", "expected_status", "expected_disposition"),
    [
        (unit_page(), "active", "supported"),
        (unit_page(archived=True), "archived", "needs-decision"),
        (
            unit_page(human_review_required=True),
            "human-review-required",
            "needs-decision",
        ),
        # An untitled page falls back to its id, which the canonical normalizer
        # treats as human-review evidence.
        (unit_page(title=""), "human-review-required", "needs-decision"),
    ],
)
def test_non_active_canonical_unit_still_requires_a_decision(
    verified_catalog, page: dict, expected_status: str, expected_disposition: str
) -> None:
    """#973's non-active-unit protection must be reachable through this path.

    The repository must not assert unit status: an archived, review-flagged, or
    untitled unit has to reach ``needs-decision`` exactly as
    ``test_non_active_canonical_unit_requires_decision`` requires. The published
    status label must also distinguish archived from review-flagged, so each
    canonical evidence field is independently load-bearing.
    """
    evidence = run(verified_catalog, RecordingExecutor(page=page))

    assert evidence["result"]["canonical_unit"]["status"] == expected_status
    assert evidence["result"]["currentness"]["disposition"] == expected_disposition


def test_catalog_may_not_declare_curriculum_status(catalog_payload) -> None:
    """A repository-declared unit status would bypass the protection above."""
    from scripts.agent_os_notion_read_request import parse_catalog

    from .notion_read_support import verified_payload

    payload = verified_payload(catalog_payload)
    payload["canonical_units"][0]["unit_status"] = "active"

    with pytest.raises(NotionReadRequestError, match="must not declare curriculum status"):
        parse_catalog(payload)


def test_unit_status_is_derived_from_canonical_normalizer_booleans(
    verified_catalog,
) -> None:
    """Status mapping must consume canonical evidence, not raw provider text."""
    executor = RecordingExecutor(
        page={
            "id": unit_page()["id"],
            "title": "Photography Foundations",
            # A non-boolean 'archived' is malformed evidence; the canonical
            # normalizer fails it closed to human review rather than guessing.
            "archived": "false",
        }
    )

    evidence = run(verified_catalog, executor)

    assert evidence["result"]["currentness"]["disposition"] == "needs-decision"


# --------------------------------------------------------------------------
# Provider execution stays inside the inherited read-only bound
# --------------------------------------------------------------------------


def test_every_dispatch_is_bounded_by_the_canonical_2282_action_set() -> None:
    """The bound is imported from #2282, so widening it there widens it here."""
    from navigation_registry.connectors.curriculum_execution_surface_router import (
        READ_ONLY_ACTIONS,
    )

    bounded = execution_module._bounded_read_task_executor(lambda payload: payload)

    for action in sorted(READ_ONLY_ACTIONS):
        assert bounded({"action": action})["action"] == action

    # The #936 adapter's own surface is wider than #2282's; those extra actions
    # must remain unreachable from this path.
    for action in ("get_block_children", "get_page_property", "query_database", None):
        with pytest.raises(NotionReadRequestError, match="outside the bounded read surface"):
            bounded({"action": action})


def test_canonical_unit_evidence_errors_fail_closed(verified_catalog) -> None:
    """A provider failure must surface as a fail-closed error, not a guess."""

    class FailingUnitExecutor(RecordingExecutor):
        def execute(self, payload):
            self.calls.append(dict(payload))
            return {"status": "failure", "message": "permission denied"}

    with pytest.raises(NotionReadRequestError, match="canonical unit evidence is unavailable"):
        run(verified_catalog, FailingUnitExecutor())
