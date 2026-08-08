from __future__ import annotations

import ast
import copy
from pathlib import Path

import pytest

import instructional_workflow_contracts.current_curriculum_state as current_state
from instructional_workflow_contracts.common import ValidationStatus

MODULE = (
    Path(__file__).parents[1]
    / "src"
    / "instructional_workflow_contracts"
    / "current_curriculum_state.py"
)


def ref(stable_id: str) -> dict[str, object]:
    return {
        "system": "notion",
        "stable_id": stable_id,
        "exact_location": f"collection://example/{stable_id}",
        "verification_evidence": "caller-supplied-read-back",
    }


def owner(
    evidence_id: str,
    *,
    decision_key: str = "unit-generation-approval",
    value: str | None = "modeling-first",
    classification: str = "owner-governed",
    owner_name: str = "unit-alignment",
    revision: int = 1,
    observed_at: str = "2026-08-01T12:00:00Z",
    currentness: str = "current",
    material: bool = True,
    relation_resolved: bool = True,
) -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "owner": owner_name,
        "decision_key": decision_key,
        "value": value,
        "classification": classification,
        "source_revision": revision,
        "observed_at": observed_at,
        "currentness": currentness,
        "material": material,
        "relation_resolved": relation_resolved,
        "reference": ref(evidence_id),
    }


def asset(
    asset_id: str,
    *,
    exists: bool = True,
    approved_use: bool | None = False,
    student_reuse: bool | None = False,
) -> dict[str, object]:
    return {
        "asset_id": asset_id,
        "exists": exists,
        "approved_for_requested_use": approved_use,
        "approved_student_reuse": student_reuse,
        "source_revision": 1,
    }


def evidence(
    *,
    unit_status: str = "active",
    action: str = "make-photography-slides",
    relative_time: str = "none",
    requires_assets: bool = False,
    owner_evidence: list[dict[str, object]] | None = None,
    assets: list[dict[str, object]] | None = None,
    required_keys: list[str] | None = None,
    current_context: dict[str, object] | None = None,
) -> dict[str, object]:
    value: dict[str, object] = {
        "contract_version": current_state.INPUT_CONTRACT_ID,
        "canonical_unit": {"stable_id": "photography-foundations", "status": unit_status},
        "request": {
            "action": action,
            "artifact_type": "slides",
            "relative_time": relative_time,
            "requires_reusable_assets": requires_assets,
        },
        "required_decision_keys": required_keys or ["unit-generation-approval"],
        "owner_evidence": owner_evidence if owner_evidence is not None else [owner("ua-1")],
        "asset_evidence": assets or [],
    }
    if current_context is not None:
        value["current_context"] = current_context
    return value


def payload(result) -> dict[str, object]:
    assert result.record is not None
    return result.record.to_dict()


def test_photography_stale_owner_plus_newer_narrative_needs_reconciliation() -> None:
    value = evidence(
        owner_evidence=[
            owner("ua-stale", currentness="stale", observed_at="2026-08-01T12:00:00Z"),
            owner(
                "unit-narrative",
                classification="teacher-entered",
                owner_name="canonical-unit",
                value="locked-sequence-approved",
                observed_at="2026-08-07T12:00:00Z",
            ),
        ]
    )
    result = current_state.resolve_current_curriculum_state(value)
    state = payload(result)
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert state["disposition"] == "needs-reconciliation"
    assert state["owner_states"] == []
    assert state["context_evidence"][0]["evidence_id"] == "unit-narrative"
    assert state["contradictions"][0]["kind"] == "newer-narrative-vs-stale-owner"


def test_newer_narrative_cannot_override_current_owner_state() -> None:
    result = current_state.resolve_current_curriculum_state(
        evidence(
            owner_evidence=[
                owner("ua-current", value="modeling-first"),
                owner(
                    "packet-narrative",
                    classification="teacher-entered",
                    owner_name="daily-packet",
                    value="ready-to-generate",
                    observed_at="2026-08-07T12:00:00Z",
                ),
            ]
        )
    )
    state = payload(result)
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert state["owner_states"][0]["value"] == "modeling-first"
    assert state["disposition"] == "needs-reconciliation"


def test_newer_owner_remains_operative_over_older_narrative() -> None:
    result = current_state.resolve_current_curriculum_state(
        evidence(
            owner_evidence=[
                owner("ua-current", value="ready", revision=3, observed_at="2026-08-07T12:00:00Z"),
                owner(
                    "old-note",
                    classification="teacher-entered",
                    owner_name="canonical-unit",
                    value="modeling-first",
                    observed_at="2026-08-01T12:00:00Z",
                ),
            ]
        )
    )
    state = payload(result)
    assert result.status is ValidationStatus.VALID
    assert state["owner_states"][0]["value"] == "ready"
    assert state["disposition"] == "supported"


def test_stale_packet_routing_with_newer_locked_content_reconciles() -> None:
    result = current_state.resolve_current_curriculum_state(
        evidence(
            required_keys=["packet-generation-gate"],
            owner_evidence=[
                owner(
                    "packet-gate-stale",
                    decision_key="packet-generation-gate",
                    owner_name="daily-packet",
                    value="modeling-first",
                    currentness="stale",
                ),
                owner(
                    "packet-locked-content",
                    decision_key="packet-generation-gate",
                    classification="teacher-entered",
                    owner_name="daily-packet",
                    value="locked-week-sequence",
                    observed_at="2026-08-07T12:00:00Z",
                ),
            ],
        )
    )
    state = payload(result)
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert "source-stale-material" in state["reason_codes"]


def test_incomplete_modeling_gate_remains_owner_state_without_invented_readiness() -> None:
    result = current_state.resolve_current_curriculum_state(
        evidence(
            required_keys=["modeling-handoff-ready"],
            owner_evidence=[
                owner(
                    "modeling-1",
                    decision_key="modeling-handoff-ready",
                    owner_name="teacher-modeling-coach",
                    value="partial",
                )
            ],
        )
    )
    state = payload(result)
    assert result.status is ValidationStatus.VALID
    assert state["owner_states"][0]["value"] == "partial"
    assert state["authority"]["production_authorized"] is False


def test_conflicting_owner_values_fail_closed() -> None:
    result = current_state.resolve_current_curriculum_state(
        evidence(owner_evidence=[owner("ua-1", value="ready"), owner("ua-2", value="blocked")])
    )
    state = payload(result)
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert state["disposition"] == "needs-decision"
    assert state["contradictions"][0]["kind"] == "owner-value-conflict"


def test_stale_material_owner_evidence_fails_closed() -> None:
    result = current_state.resolve_current_curriculum_state(
        evidence(owner_evidence=[owner("ua-stale", currentness="stale")])
    )
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert payload(result)["disposition"] == "needs-reconciliation"


def test_display_ready_signal_cannot_override_owner_and_surfaces_drift() -> None:
    result = current_state.resolve_current_curriculum_state(
        evidence(
            owner_evidence=[
                owner("ua-owner", value="modeling-first"),
                owner(
                    "rollup-ready",
                    classification="display-derived",
                    owner_name="unit-readiness-heatmap",
                    value="ready",
                    material=True,
                ),
            ]
        )
    )
    state = payload(result)
    assert state["owner_states"][0]["value"] == "modeling-first"
    assert state["contradictions"][0]["kind"] == "display-drift"
    assert state["disposition"] == "needs-reconciliation"


def test_advisory_routing_conflict_never_overrides_owner() -> None:
    result = current_state.resolve_current_curriculum_state(
        evidence(
            owner_evidence=[
                owner("ua-owner", value="teacher-modeling-coach"),
                owner(
                    "agent-route",
                    classification="agent-suggested",
                    owner_name="routing-dashboard",
                    value="instructional-materials-coach",
                    material=False,
                ),
            ]
        )
    )
    state = payload(result)
    assert result.status is ValidationStatus.VALID
    assert state["owner_states"][0]["value"] == "teacher-modeling-coach"
    assert state["contradictions"][0]["kind"] == "advisory-conflict"


def test_semantically_equivalent_input_order_has_same_identity_and_fingerprint() -> None:
    records = [
        owner("ua-owner"),
        owner("note-b", classification="teacher-entered", owner_name="canonical-unit", value="modeling-first"),
    ]
    first = current_state.resolve_current_curriculum_state(evidence(owner_evidence=records))
    second = current_state.resolve_current_curriculum_state(evidence(owner_evidence=list(reversed(records))))
    assert first.record is not None and second.record is not None
    assert first.record.record_id == second.record.record_id
    assert first.record.fingerprint == second.record.fingerprint
    assert first.record.to_dict() == second.record.to_dict()


def test_input_is_not_mutated() -> None:
    value = evidence()
    before = copy.deepcopy(value)
    current_state.resolve_current_curriculum_state(value)
    assert value == before


def test_tomorrow_without_current_day_anchor_is_blocked() -> None:
    result = current_state.resolve_current_curriculum_state(evidence(relative_time="tomorrow"))
    state = payload(result)
    assert result.status is ValidationStatus.BLOCKED
    assert state["resolved_day_id"] is None
    assert "routing-current-day-missing" in state["blockers"]


def test_tomorrow_with_explicit_anchor_resolves_from_supplied_order() -> None:
    result = current_state.resolve_current_curriculum_state(
        evidence(
            relative_time="tomorrow",
            current_context={
                "current_day_id": "day-2",
                "ordered_day_ids": ["day-1", "day-2", "day-3"],
            },
        )
    )
    assert result.status is ValidationStatus.VALID
    assert payload(result)["resolved_day_id"] == "day-3"


def test_asset_exists_but_is_not_reusable_and_required_blocks() -> None:
    result = current_state.resolve_current_curriculum_state(
        evidence(requires_assets=True, assets=[asset("photo-1")])
    )
    state = payload(result)
    assert result.status is ValidationStatus.BLOCKED
    assert state["assets"]["matching_asset_exists"] is True
    assert state["assets"]["approved_reusable_student_facing_exists"] is False
    assert state["authority"]["production_authorized"] is False


def test_approved_reusable_asset_reports_eligibility_without_authority() -> None:
    result = current_state.resolve_current_curriculum_state(
        evidence(requires_assets=True, assets=[asset("photo-1", approved_use=True, student_reuse=True)])
    )
    state = payload(result)
    assert result.status is ValidationStatus.VALID
    assert state["assets"]["approved_reusable_student_facing_exists"] is True
    assert state["authority"]["production_authorized"] is False


def test_ambiguous_asset_eligibility_needs_reconciliation() -> None:
    result = current_state.resolve_current_curriculum_state(
        evidence(requires_assets=True, assets=[asset("photo-1", approved_use=None, student_reuse=None)])
    )
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert payload(result)["disposition"] == "needs-reconciliation"


def test_missing_required_owner_evidence_blocks() -> None:
    result = current_state.resolve_current_curriculum_state(
        evidence(required_keys=["packet-generation-gate"], owner_evidence=[])
    )
    assert result.status is ValidationStatus.BLOCKED
    assert "dependency-owner-evidence-missing" in payload(result)["blockers"]


def test_unresolved_required_relation_blocks() -> None:
    result = current_state.resolve_current_curriculum_state(
        evidence(owner_evidence=[owner("ua-1", relation_resolved=False)])
    )
    assert result.status is ValidationStatus.BLOCKED
    assert "dependency-owner-relation-unresolved" in payload(result)["blockers"]


@pytest.mark.parametrize("status", ["ambiguous", "archived", "split", "merged", "human-review-required"])
def test_non_active_canonical_unit_requires_decision(status: str) -> None:
    result = current_state.resolve_current_curriculum_state(evidence(unit_status=status))
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert payload(result)["disposition"] == "needs-decision"


def test_malformed_and_unsupported_inputs_fail_closed() -> None:
    assert current_state.resolve_current_curriculum_state(None).status is ValidationStatus.INVALID
    value = evidence()
    value["contract_version"] = "curriculum-current-state-evidence-v2"
    result = current_state.resolve_current_curriculum_state(value)
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("handoff-version-unsupported",)


def test_bounds_fail_closed() -> None:
    value = evidence()
    value["owner_evidence"] = [
        owner(f"evidence-{index}", decision_key=f"decision-{index}")
        for index in range(current_state.MAX_OWNER_EVIDENCE + 1)
    ]
    result = current_state.resolve_current_curriculum_state(value)
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("handoff-oversized",)


def test_authority_escalation_attack_fails_closed() -> None:
    value = evidence()
    value["production_authorized"] = True
    result = current_state.resolve_current_curriculum_state(value)
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("authority-escalation-attempt",)


def test_safe_unknown_additive_field_is_ignored() -> None:
    value = evidence()
    value["future_optional_context"] = {"note": "safe additive evidence"}
    base = current_state.resolve_current_curriculum_state(evidence())
    future = current_state.resolve_current_curriculum_state(value)
    assert base.record is not None and future.record is not None
    assert base.record.fingerprint == future.record.fingerprint


def test_module_has_no_network_credentials_filesystem_or_subprocess_imports() -> None:
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    forbidden = (
        "requests",
        "httpx",
        "urllib",
        "socket",
        "subprocess",
        "os",
        "pathlib",
        "notion",
        "google",
        "github",
        "workflow_scheduler",
        "navigation_registry",
    )
    assert not [name for name in imports if name.startswith(forbidden)]
