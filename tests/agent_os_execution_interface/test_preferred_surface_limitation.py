"""#3139 preferred-execution-surface limitation classification conformance.

Covers the post-#3129 regression fixture -- a finite mission whose preferred
Codespaces surface cannot be directly observed or entered -- plus the
fail-closed sharedness rule, the proven-shared terminal case, and the
no-admissible-work stop. An end-to-end driver case proves a finite mission
with remaining GitHub-read-only work continues that work instead of emitting
a terminal report.
"""

from __future__ import annotations

import dataclasses

import pytest

from scripts.agent_os_execution_interface.continuation_driver import (
    ContinuationDecision,
    drive_governed_continuation,
)
from scripts.agent_os_execution_interface.preferred_surface_limitation import (
    PREFERRED_SURFACE_LIMITATION_SCHEMA_NAME,
    PREFERRED_SURFACE_LIMITATION_SCHEMA_VERSION,
    PreferredSurfaceLimitationDecision,
    PreferredSurfaceLimitationEvidence,
    SurfaceLimitationClassification,
    SurfaceLimitationKind,
    SurfaceLimitationReason,
    classify_preferred_surface_limitation,
)


ITEM_LOCAL = SurfaceLimitationClassification.ITEM_LOCAL_CAPABILITY_BOUNDARY
SHARED = SurfaceLimitationClassification.SHARED_MISSION_BLOCKER


def evidence(**overrides) -> PreferredSurfaceLimitationEvidence:
    """The #3139 live shape: 177 read-only operations, Codespaces unobservable."""
    values = {
        "limitation_kind": SurfaceLimitationKind.UNOBSERVABLE,
        "preferred_surface_id": "codespace:agent-os-dev",
        "mission_cursor": "cursor:3139-backlog-consolidation:000",
        "remaining_operation_count": 177,
        "operations_requiring_surface_count": 0,
        "github_read_evidence_available": True,
        "sharedness_proven": False,
    }
    values.update(overrides)
    return PreferredSurfaceLimitationEvidence(**values)


def reasons(decision: PreferredSurfaceLimitationDecision) -> tuple[str, ...]:
    return tuple(item.value for item in decision.reason_codes)


# --------------------------------------------------------------------------
# #3139 reproduction: unobservable preferred surface, read-only work remains
# --------------------------------------------------------------------------


def test_3139_reproduction_continues_read_only_work_item_local():
    decision = classify_preferred_surface_limitation(evidence())
    assert decision.classification is ITEM_LOCAL
    assert decision.mission_continues is True
    assert decision.mission_cursor_preserved is True
    assert decision.blocker is None and decision.clearing_condition is None
    assert decision.surface_requiring_operations_terminal_item_local is False
    assert SurfaceLimitationReason.PREFERRED_SURFACE_UNOBSERVABLE in decision.reason_codes
    assert (
        SurfaceLimitationReason.SHAREDNESS_UNPROVEN_FAIL_CLOSED_ITEM_LOCAL
        in decision.reason_codes
    )
    assert (
        SurfaceLimitationReason.REMAINING_OPERATIONS_GITHUB_READ_ADMISSIBLE
        in decision.reason_codes
    )
    assert SurfaceLimitationReason.SHAREDNESS_PROVEN not in decision.reason_codes


def test_3139_bug_variant_shared_promotion_is_rejected():
    """The exact historical failure: identical evidence promoted to shared.

    The fixed classifier must never produce the shared classification from
    unproven sharedness, no matter how the limitation is framed.
    """
    for kind in SurfaceLimitationKind:
        decision = classify_preferred_surface_limitation(
            evidence(limitation_kind=kind)
        )
        assert decision.classification is not SHARED
        assert decision.classification is ITEM_LOCAL


def test_surface_requiring_operations_stop_item_local_not_shared():
    decision = classify_preferred_surface_limitation(
        evidence(remaining_operation_count=10, operations_requiring_surface_count=3)
    )
    assert decision.classification is ITEM_LOCAL
    assert decision.mission_continues is True
    assert decision.surface_requiring_operations_terminal_item_local is True
    assert decision.blocker is None


def test_no_admissible_remaining_work_stops_without_shared_blocker():
    decision = classify_preferred_surface_limitation(
        evidence(
            remaining_operation_count=4,
            operations_requiring_surface_count=4,
            github_read_evidence_available=False,
        )
    )
    assert decision.classification is ITEM_LOCAL
    assert decision.mission_continues is False
    assert decision.blocker is None and decision.clearing_condition is None
    assert (
        SurfaceLimitationReason.NO_REMAINING_ADMISSIBLE_OPERATIONS
        in decision.reason_codes
    )


def test_empty_remaining_population_is_item_local_not_shared():
    decision = classify_preferred_surface_limitation(
        evidence(remaining_operation_count=0, operations_requiring_surface_count=0)
    )
    assert decision.classification is ITEM_LOCAL
    assert decision.mission_continues is False


# --------------------------------------------------------------------------
# Proven sharedness: the only path to a shared mission blocker
# --------------------------------------------------------------------------


def test_sharedness_proven_stops_mission_with_blocker():
    decision = classify_preferred_surface_limitation(
        evidence(
            sharedness_proven=True,
            sharedness_evidence=(
                "github-api-unreachable: canonical read evidence unavailable "
                "for every remaining operation"
            ),
        )
    )
    assert decision.classification is SHARED
    assert decision.mission_continues is False
    assert SurfaceLimitationReason.SHAREDNESS_PROVEN in decision.reason_codes
    assert decision.blocker and decision.clearing_condition
    assert "github-api-unreachable" in decision.blocker


def test_sharedness_proven_without_evidence_fails_closed():
    with pytest.raises(ValueError, match="sharedness_evidence"):
        evidence(sharedness_proven=True)


def test_sharedness_evidence_without_proven_claim_fails_closed():
    with pytest.raises(ValueError, match="sharedness_evidence requires"):
        evidence(sharedness_proven=False, sharedness_evidence="plausible but unproven")


def test_plausible_but_unproven_sharedness_stays_item_local():
    """Plausibility is not proof: the #3139 failure mode, pinned."""
    decision = classify_preferred_surface_limitation(
        evidence(
            limitation_kind=SurfaceLimitationKind.UNENTERABLE,
            github_read_evidence_available=True,
        )
    )
    assert decision.classification is ITEM_LOCAL
    assert decision.mission_continues is True


# --------------------------------------------------------------------------
# Decision structural invariants
# --------------------------------------------------------------------------


def test_schema_and_authority_contract():
    decision = classify_preferred_surface_limitation(evidence())
    assert decision.schema_name == PREFERRED_SURFACE_LIMITATION_SCHEMA_NAME
    assert decision.schema_version == PREFERRED_SURFACE_LIMITATION_SCHEMA_VERSION
    assert decision.execution_authorized is False
    assert decision.github_writes_authorized is False
    assert decision.merge_authorized is False
    assert decision.issue_closure_authorized is False
    assert decision.external_writes_authorized is False
    assert decision.scheduler_invoked is False


def test_reason_codes_sorted_unique_nonempty():
    decision = classify_preferred_surface_limitation(evidence())
    assert decision.reason_codes == tuple(
        sorted(set(decision.reason_codes), key=lambda item: item.value)
    )
    assert len(decision.reason_codes) > 0


def test_decision_is_frozen():
    decision = classify_preferred_surface_limitation(evidence())
    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.mission_continues = False  # type: ignore[misc]


# --------------------------------------------------------------------------
# Input validation
# --------------------------------------------------------------------------


@pytest.mark.parametrize("field", ("limitation_kind",))
def test_wrong_limitation_kind_type_rejected(field):
    with pytest.raises(TypeError):
        evidence(**{field: "unobservable"})


def test_wrong_evidence_type_rejected():
    with pytest.raises(TypeError):
        classify_preferred_surface_limitation(object())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field", ("remaining_operation_count", "operations_requiring_surface_count")
)
def test_negative_counts_rejected(field):
    with pytest.raises(ValueError):
        evidence(**{field: -1})


def test_requiring_more_than_remaining_rejected():
    with pytest.raises(ValueError, match="cannot exceed"):
        evidence(remaining_operation_count=2, operations_requiring_surface_count=3)


@pytest.mark.parametrize("field", ("preferred_surface_id", "mission_cursor"))
def test_blank_identity_rejected(field):
    with pytest.raises(ValueError):
        evidence(**{field: "   "})


def test_whitespace_in_surface_id_rejected():
    with pytest.raises(ValueError):
        evidence(preferred_surface_id="codespace:with space")


@pytest.mark.parametrize(
    "field", ("github_read_evidence_available", "sharedness_proven")
)
def test_non_bool_flags_rejected(field):
    with pytest.raises(TypeError):
        evidence(**{field: 1})


# --------------------------------------------------------------------------
# End-to-end: the finite mission continues through the limitation
# --------------------------------------------------------------------------


class BacklogConsolidationMission:
    """Finite read-only mission shaped like the #3139 live reproduction.

    The adapter owns a cursor over GitHub-read-only operations. When the
    preferred Codespaces surface proves unobservable mid-mission, the
    limitation is classified item-local and the driver keeps dispatching
    from the preserved cursor instead of emitting a terminal report.
    """

    def __init__(self, operation_count: int = 5):
        self.cursor = 0
        self.operation_count = operation_count
        self.processed: list[int] = []
        self.surface_limitation_seen = False

    def observe(self):
        if not self.surface_limitation_seen and self.cursor == 2:
            self.surface_limitation_seen = True
            decision = classify_preferred_surface_limitation(
                PreferredSurfaceLimitationEvidence(
                    limitation_kind=SurfaceLimitationKind.UNOBSERVABLE,
                    preferred_surface_id="codespace:agent-os-dev",
                    mission_cursor=f"cursor:3139:{self.cursor:03d}",
                    remaining_operation_count=self.operation_count - self.cursor,
                    operations_requiring_surface_count=0,
                    github_read_evidence_available=True,
                    sharedness_proven=False,
                )
            )
            assert decision.classification is ITEM_LOCAL
            # The historical bug returned a terminal shared-blocker payload
            # here; the fix continues from the preserved cursor instead.
            return {"terminal": False, "blocked": False, "action": "continue-read-only-reconciliation"}
        if self.cursor >= self.operation_count:
            return {"terminal": True, "blocked": False, "action": ""}
        return {"terminal": False, "blocked": False, "action": "continue-read-only-reconciliation"}

    def dispatch(self, action: str) -> None:
        assert action == "continue-read-only-reconciliation"
        self.processed.append(self.cursor)
        self.cursor += 1


def test_finite_mission_continues_past_surface_limitation():
    mission = BacklogConsolidationMission(operation_count=5)

    def decide(payload):
        return ContinuationDecision(
            action=payload["action"],
            terminal=payload["terminal"],
            blocked=payload["blocked"],
            reason_codes=(
                ("preferred-surface-item-local-boundary",)
                if mission.surface_limitation_seen and not payload["terminal"]
                else ()
            ),
        )

    result = drive_governed_continuation(mission, decide)
    assert result.status == "completed"
    assert result.user_turns_required == 0
    # Every operation processed exactly once, in cursor order, across the
    # limitation boundary: no reprocessing, no abandoned tail.
    assert mission.processed == [0, 1, 2, 3, 4]
    assert mission.surface_limitation_seen is True
