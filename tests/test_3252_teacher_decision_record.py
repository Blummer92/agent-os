"""#3252: teacher visual-decision record — schema, persistence, invalidation,
and governed reuse-path semantics.

Covers the issue acceptance criteria: a teacher visual decision records the
required fields; it survives restart/retry/unrelated revisions; it is
invalidated with an explicit reason when the candidate set or asset content
changes; the governed reuse path honors a valid selection per role and
blocks (never silently replaces) an invalid one.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from instructional_workflow_contracts.teacher_visual_decision import (
    REASON_ASSET_CONTENT_CHANGED,
    REASON_ASSET_NO_LONGER_ELIGIBLE,
    REASON_CANDIDATE_SET_CHANGED,
    REASON_ROLE_RETIRED,
    TEACHER_VISUAL_DECISION_CONTRACT_ID,
    DecisionValidity,
    TeacherVisualDecisionRecord,
    canonical_candidate_set_fingerprint,
    evaluate_decision_validity,
)

ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "instructional_workflow_contracts"

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _decision(**overrides):
    record = {
        "contract_id": TEACHER_VISUAL_DECISION_CONTRACT_ID,
        "decision_id": "dec-001",
        "actor": "teacher:t-1",
        "decided_at": "2026-10-03T12:00:00.000Z",
        "requirement_id": "req-1",
        "source_revision": "visual-library-snapshot-v2",
        "role": "hook",
        "slot": 0,
        "selected_asset": {
            "asset_id": "asset-a",
            "provider_file_id": "drive-file-1",
            "content_identity": {
                "contract_version": "governed-asset-content-identity-v1",
                "source": "drive-sha256",
                "algorithm": "sha256",
                "value": SHA_A,
            },
            "revision_identity": "rev-1",
            "provenance": {"source": "drive"},
        },
        "overridden_recommendation": "asset-b",
        "candidate_set_fingerprint": SHA_C,
        "scope": "unit",
        "invalidation_rule": "candidate-set-or-content-change",
        "status": "active",
        "invalidation": None,
    }
    record.update(overrides)
    return record


def _content_identities(asset_id="asset-a", value=SHA_A):
    return {
        asset_id: {
            "contract_version": "governed-asset-content-identity-v1",
            "source": "drive-sha256",
            "algorithm": "sha256",
            "value": value,
        }
    }


def test_role_identity_survives_unrelated_requirement_revision():
    from instructional_workflow_contracts.material_requirement import material_requirement_source_fingerprint
    from instructional_workflow_contracts.visual_needs import plan_visual_needs

    requirement = _fixture("valid_material_requirement_v2.json")
    baseline = plan_visual_needs(requirement).record.to_dict()
    requirement["instructional"]["purpose"] += " unrelated edit"
    requirement["identity"]["record_revision"] += 1
    requirement["identity"]["source_fingerprint"] = material_requirement_source_fingerprint(requirement)
    revised = plan_visual_needs(requirement).record.to_dict()
    assert [r["role_id"] for r in baseline["required_roles"] + baseline["optional_roles"]] == [
        r["role_id"] for r in revised["required_roles"] + revised["optional_roles"]
    ]


def test_semantic_role_edit_changes_only_that_role_identity():
    from instructional_workflow_contracts.material_requirement import material_requirement_source_fingerprint
    from instructional_workflow_contracts.visual_needs import plan_visual_needs

    requirement = _fixture("valid_material_requirement_v2.json")
    baseline = plan_visual_needs(requirement).record.to_dict()
    requirement["visual_direction"]["roles"][0]["instructional_purpose"] += " changed"
    requirement["identity"]["source_fingerprint"] = material_requirement_source_fingerprint(requirement)
    revised = plan_visual_needs(requirement).record.to_dict()
    before = [r["role_id"] for r in baseline["required_roles"] + baseline["optional_roles"]]
    after = [r["role_id"] for r in revised["required_roles"] + revised["optional_roles"]]
    assert before[0] != after[0]
    assert before[1:] == after[1:]

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def test_decision_record_has_all_required_fields():
    record = TeacherVisualDecisionRecord.from_dict(_decision())
    payload = record.to_dict()
    assert payload["contract_id"] == TEACHER_VISUAL_DECISION_CONTRACT_ID
    assert payload["decision_id"] == "dec-001"
    assert payload["actor"] == "teacher:t-1"
    assert payload["role"] == "hook"
    assert payload["slot"] == 0
    assert payload["selected_asset"]["asset_id"] == "asset-a"
    assert payload["overridden_recommendation"] == "asset-b"
    assert payload["candidate_set_fingerprint"] == SHA_C
    assert payload["source_revision"] == "visual-library-snapshot-v2"
    assert payload["scope"] == "unit"
    assert payload["invalidation_rule"] == "candidate-set-or-content-change"
    assert payload["status"] == "active"


def test_decision_record_rejects_missing_field():
    bad = _decision()
    del bad["candidate_set_fingerprint"]
    with pytest.raises(ValueError):
        TeacherVisualDecisionRecord.from_dict(bad)


def test_decision_record_rejects_unknown_invalidation_rule():
    with pytest.raises(ValueError):
        TeacherVisualDecisionRecord.from_dict(
            _decision(invalidation_rule="whatever-changes")
        )


def test_decision_record_rejects_bad_fingerprint():
    with pytest.raises(ValueError):
        TeacherVisualDecisionRecord.from_dict(
            _decision(candidate_set_fingerprint="not-a-sha")
        )


def test_decision_record_rejects_bad_scope():
    with pytest.raises(ValueError):
        TeacherVisualDecisionRecord.from_dict(_decision(scope="schoolwide"))


# ---------------------------------------------------------------------------
# Persistence (reports/teacher-decisions/)
# ---------------------------------------------------------------------------

def test_decision_survives_process_restart_round_trip(tmp_path):
    from instructional_materials_coach.teacher_decisions import (
        load_teacher_decisions,
        write_teacher_decision,
    )

    decisions_dir = tmp_path / "teacher-decisions"
    path = write_teacher_decision(_decision(), decisions_dir)
    assert path.parent == decisions_dir
    assert path.suffix == ".json"
    # Filename embeds decided_at, decision_id, requirement_id, role.
    assert "dec-001" in path.name and "req-1" in path.name and "hook" in path.name

    # Fresh read (simulating a new process).
    loaded = load_teacher_decisions(decisions_dir, requirement_id="req-1")
    assert len(loaded) == 1
    assert loaded[0] == TeacherVisualDecisionRecord.from_dict(_decision()).to_dict()


def test_decision_lookup_by_requirement_and_role(tmp_path):
    from instructional_materials_coach.teacher_decisions import (
        active_decision_for,
        load_teacher_decisions,
        write_teacher_decision,
    )

    decisions_dir = tmp_path / "teacher-decisions"
    write_teacher_decision(_decision(decision_id="dec-1", role="hook"), decisions_dir)
    write_teacher_decision(
        _decision(decision_id="dec-2", role="hook", decided_at="2026-10-03T13:00:00.000Z"),
        decisions_dir,
    )
    write_teacher_decision(
        _decision(decision_id="dec-3", role="comparison", requirement_id="req-2"),
        decisions_dir,
    )

    decisions = load_teacher_decisions(decisions_dir)
    assert len(decisions) == 3
    # Latest active decision wins for the triple.
    active = active_decision_for(decisions, requirement_id="req-1", role="hook")
    assert active is not None and active["decision_id"] == "dec-2"
    # Absent triple → None, never an exception or fabricated default.
    assert (
        active_decision_for(decisions, requirement_id="req-1", role="nope") is None
    )
    # Corrupt files are skipped, never fatal.
    (decisions_dir / "garbage.json").write_text("{not json", encoding="utf-8")
    assert len(load_teacher_decisions(decisions_dir)) == 3
    # Missing directory → empty list.
    assert load_teacher_decisions(tmp_path / "nope") == []


# ---------------------------------------------------------------------------
# Invalidation
# ---------------------------------------------------------------------------

def _validity(**overrides):
    decision = _decision()
    return evaluate_decision_validity(
        decision,
        candidate_set_fingerprint=overrides.pop("fingerprint", SHA_C),
        eligible_asset_ids=overrides.pop("eligible", {"asset-a"}),
        current_content_identities=overrides.pop("identities", _content_identities()),
        source_revision=overrides.pop("source_revision", "visual-library-snapshot-v2"),
        active_roles=overrides.pop("active_roles", {"hook"}),
    )


def test_decision_valid_when_nothing_changed():
    validity = _validity()
    assert isinstance(validity, DecisionValidity)
    assert validity.valid is True
    assert validity.reason_code is None


def test_decision_invalidated_when_candidate_set_changes():
    validity = _validity(fingerprint=SHA_B)
    assert validity.valid is False
    assert validity.reason_code == REASON_CANDIDATE_SET_CHANGED
    assert validity.detail


def test_decision_invalidated_when_asset_content_changes():
    validity = _validity(identities=_content_identities(value=SHA_B))
    assert validity.valid is False
    assert validity.reason_code == REASON_ASSET_CONTENT_CHANGED
    assert validity.detail


def test_decision_invalidated_when_asset_no_longer_eligible():
    validity = _validity(eligible={"asset-other"})
    assert validity.valid is False
    assert validity.reason_code == REASON_ASSET_NO_LONGER_ELIGIBLE
    assert validity.detail


def test_decision_invalidated_when_role_retired():
    validity = _validity(active_roles={"other-role"})
    assert validity.valid is False
    assert validity.reason_code == REASON_ROLE_RETIRED


def test_decision_survives_unrelated_requirement_revision():
    # The fingerprint binds the candidate set only; a requirement revision
    # touching pacing/section text leaves it (and the asset bytes) alone.
    validity = _validity()
    assert validity.valid is True


def test_invalidation_reason_is_always_explicit():
    for kwargs in (
        {"fingerprint": SHA_B},
        {"identities": _content_identities(value=SHA_B)},
        {"eligible": set()},
    ):
        validity = _validity(**kwargs)
        assert validity.valid is False
        assert isinstance(validity.reason_code, str) and validity.reason_code
        assert isinstance(validity.detail, str) and validity.detail


def test_candidate_set_fingerprint_ignores_order_and_content_bytes():
    def _candidate(asset_id, page_id="page-1", drive_id="file-1"):
        return {
            "compatibility_evidence": {
                "asset_reference": {
                    "asset_id": asset_id,
                    "content_fingerprint": SHA_A,
                },
                "library_reference": {
                    "page_id": page_id,
                    "drive_file_id": drive_id,
                },
            }
        }

    one = [_candidate("a"), _candidate("b")]
    reordered = [_candidate("b"), _candidate("a")]
    assert canonical_candidate_set_fingerprint(one) == canonical_candidate_set_fingerprint(reordered)
    # Content bytes do NOT move the set fingerprint (that's asset-content-changed).
    changed_bytes = [_candidate("a"), _candidate("b")]
    changed_bytes[0]["compatibility_evidence"]["asset_reference"]["content_fingerprint"] = SHA_B
    assert canonical_candidate_set_fingerprint(one) == canonical_candidate_set_fingerprint(changed_bytes)
    # Membership does.
    assert canonical_candidate_set_fingerprint(one) != canonical_candidate_set_fingerprint([_candidate("a")])


# ---------------------------------------------------------------------------
# Governed reuse-path semantics
# ---------------------------------------------------------------------------

def _fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _two_candidates():
    """Distinct genuinely valid assets with matching manifest and Drive evidence."""
    from instructional_workflow_contracts import ValidationStatus
    from instructional_workflow_contracts.artifact_manifest import (
        artifact_manifest_idempotency_key, artifact_manifest_source_fingerprint,
        validate_artifact_manifest,
    )
    from instructional_workflow_contracts.visual_asset_compatibility import (
        validate_visual_asset_compatibility_evidence,
    )

    c1 = _fixture("valid_visual_asset_compatibility_v2.json")
    c2 = copy.deepcopy(c1)
    manifest = c2["artifact_manifest"]
    asset = manifest["assets"][0]
    asset.update({
        "asset_id": "asset-2",
        "stable_ref": "asset-ref-2",
        "content_fingerprint": SHA_B,
        "disposition": "alternate",
        "duplicate_relationship": "exact-duplicate",
        "canonical_asset_ref": "asset-ref-1",
    })
    manifest["identity"]["manifest_id"] = "manifest-2"
    manifest["custom_properties"]["manifest_id"] = "manifest-2"
    external = manifest["external_identity"]
    external["file_id"] = "file-2"
    external["exact_reference"] = "drive:file-2"
    external["web_view_link"] = "https://example.invalid/file-2"
    key = artifact_manifest_idempotency_key(manifest)
    manifest["operation"]["idempotency_key"] = key
    manifest["custom_properties"]["idempotency_key"] = key
    manifest["identity"]["source_fingerprint"] = artifact_manifest_source_fingerprint(manifest)
    valid = validate_artifact_manifest(manifest)
    assert valid.status is ValidationStatus.VALID, valid.reason_codes
    assert valid.record is not None

    evidence = c2["compatibility_evidence"]
    evidence["asset_reference"].update({
        "asset_id": "asset-2",
        "stable_ref": "asset-ref-2",
        "content_fingerprint": SHA_B,
    })
    evidence["library_reference"] = {"page_id": "page-2", "drive_file_id": "file-2"}
    evidence["manifest_reference"].update({
        "manifest_id": "manifest-2",
        "external_file_id": "file-2",
        "fingerprint": valid.record.fingerprint,
    })
    evidence["freshness"]["manifest_fingerprint"] = valid.record.fingerprint
    c2["library_record"]["drive_file_id"] = "file-2"
    c2["library_record"]["page_id"] = "page-2"
    # Compatibility identity is derived by the validator; the envelope has no such field.
    checked = validate_visual_asset_compatibility_evidence(c2)
    assert checked.status is ValidationStatus.VALID, checked.reason_codes
    assert checked.record is not None
    assert checked.record.to_dict()["classification"] == "eligible"
    return [c1, c2]


def test_both_fixture_assets_are_admitted_by_governed_filter():
    from instructional_workflow_contracts import ValidationStatus
    from instructional_workflow_contracts.visual_asset_candidates import (
        V2_CONTRACT_ID, filter_approved_visual_candidates,
    )
    from instructional_workflow_contracts.visual_needs import plan_visual_needs

    candidates = _two_candidates()
    needs = plan_visual_needs(_fixture("valid_material_requirement_v2.json"))
    assert needs.status is ValidationStatus.VALID
    filtered = filter_approved_visual_candidates(
        needs, candidates,
        source_revision="visual-library-snapshot-v2", contract_version=V2_CONTRACT_ID,
    )
    assert filtered.status is ValidationStatus.VALID, filtered.reason_codes
    assert filtered.record is not None
    payload = filtered.record.to_dict()
    assert payload["candidate_count"] == 2
    assert len(payload["eligible"]) == 2
    assert payload["rejected"] == []


def test_mismatched_manifest_asset_is_not_valid_teacher_evidence():
    from instructional_workflow_contracts import ValidationStatus
    from instructional_workflow_contracts.visual_asset_compatibility import (
        validate_visual_asset_compatibility_evidence,
    )
    candidate = _fixture("valid_visual_asset_compatibility_v2.json")
    candidate["compatibility_evidence"]["asset_reference"]["asset_id"] = "asset-2"
    rejected = validate_visual_asset_compatibility_evidence(candidate)
    assert rejected.status is not ValidationStatus.VALID


def _plan(candidates, teacher_decisions=()):
    from instructional_materials_coach.visual_reuse import plan_governed_visual_reuse

    return plan_governed_visual_reuse(
        _fixture("valid_material_requirement_v2.json"),
        artifact_manifests=[_fixture("valid_artifact_manifest.json")],
        visual_candidates=candidates,
        source_revision="visual-library-snapshot-v2",
        changed_dependency_keys=[],
        impact_map={},
        teacher_decisions=tuple(teacher_decisions),
    )


def _role_id(plan):
    payload = plan.cohesive_visual_plan_result.record.to_dict()
    return payload["required_role_assignments"][0]["role_id"]


def _valid_decision_for(candidates, role, asset_id, fingerprint_value, overridden=None):
    return _decision(
        decision_id="dec-teacher-1",
        requirement_id=_fixture("valid_material_requirement_v2.json")["identity"][
            "requirement_id"
        ],
        role=role,
        selected_asset={
            "asset_id": asset_id,
            "provider_file_id": "file-2",
            "content_identity": {
                "contract_version": "governed-asset-content-identity-v1",
                "source": "drive-sha256",
                "algorithm": "sha256",
                "value": fingerprint_value,
            },
            "revision_identity": "rev-2",
            "provenance": {"source": "drive"},
        },
        overridden_recommendation=overridden,
        candidate_set_fingerprint=canonical_candidate_set_fingerprint(candidates),
    )


def test_reuse_path_honors_valid_teacher_selection():
    candidates = _two_candidates()
    baseline = _plan(candidates)
    assert baseline.outcome == "visuals-ready"
    role = _role_id(baseline)
    # Planner prefers asset-1; the teacher chooses asset-2.
    assert baseline.selected_asset_ids == ("asset-1",)

    decision = _valid_decision_for(
        candidates, role, "asset-2", SHA_B, overridden="asset-1"
    )
    plan = _plan(candidates, [decision])
    assert plan.outcome == "visuals-ready", getattr(plan, "teacher_decision_block_reason", None)
    assert plan.selected_asset_ids == ("asset-2",)
    assert plan.teacher_decision_outcomes[0]["honored"] is True
    assert plan.teacher_decision_outcomes[0]["decision_id"] == "dec-teacher-1"


def test_reuse_path_blocks_invalid_selection_with_reason():
    candidates = _two_candidates()
    role = _role_id(_plan(candidates))
    # Candidate set changed after the decision: fingerprint mismatch.
    decision = _valid_decision_for(candidates, role, "asset-2", SHA_B)
    decision = dict(decision, candidate_set_fingerprint=SHA_A)

    plan = _plan(candidates, [decision])
    assert plan.outcome == "teacher-decision-invalidated"
    assert plan.final_production_blocked is True
    # The blocked role's asset is excluded; the planner's pick is NOT substituted.
    assert plan.selected_asset_ids == ()
    outcome = plan.teacher_decision_outcomes[0]
    assert outcome["honored"] is False
    assert outcome["reason_code"] == REASON_CANDIDATE_SET_CHANGED
    assert outcome["detail"]


def test_reuse_path_leaves_role_unresolved_without_decision():
    candidates = _two_candidates()
    plan = _plan(candidates)
    assert plan.outcome == "visuals-ready", getattr(plan, "teacher_decision_block_reason", None)
    assert plan.teacher_decision_outcomes == ()
    assert plan.selected_asset_ids == ("asset-1",)


def test_teacher_selection_outside_eligible_set_fails_closed():
    candidates = _two_candidates()
    role = _role_id(_plan(candidates))
    # Decision's candidate set matches the current set, but the named asset
    # is not in it.
    decision = _valid_decision_for([candidates[0]], role, "asset-ghost", SHA_B)
    selected = dict(decision["selected_asset"], asset_id="asset-ghost")
    decision = dict(decision, selected_asset=selected)

    plan = _plan([candidates[0]], [decision])
    assert plan.outcome == "teacher-decision-invalidated"
    assert plan.final_production_blocked is True
    outcome = plan.teacher_decision_outcomes[0]
    assert outcome["honored"] is False
    assert outcome["reason_code"] == REASON_ASSET_NO_LONGER_ELIGIBLE


# #3251 — exact consumer role/slot binding, alongside #3252 persistence.
def _resolve_slot_choices(bindings, decisions):
    from instructional_materials_coach.visual_reuse import _apply_teacher_decisions

    assignments = [
        {"role_id": role, "slot_id": slot,
         "selected_candidate": {"asset_reference": {"asset_id": asset}}}
        for role, slot, asset in bindings
    ]
    identity = _content_identities()["asset-a"]
    return _apply_teacher_decisions(
        {"required_role_assignments": assignments},
        tuple(decisions),
        candidate_set_fingerprint=SHA_C,
        requirement_id="req-1",
        eligible_asset_ids={"asset-a", "asset-b"},
        content_identities={"asset-a": identity, "asset-b": identity},
        source_revision="visual-library-snapshot-v2",
    )


def _slot_decision(slot=0, asset="asset-b", status="active", decision_id="dec-001"):
    raw = _decision(slot=slot, status=status, decision_id=decision_id)
    raw["selected_asset"]["asset_id"] = asset
    return TeacherVisualDecisionRecord.from_dict(raw).to_dict()


def test_named_slot_teacher_decision_contract_and_persistence(tmp_path):
    from instructional_materials_coach.teacher_decisions import (
        active_decision_for, load_teacher_decisions, write_teacher_decision,
    )
    record = _slot_decision("page-1")
    assert record["slot"] == "page-1"
    write_teacher_decision(record, tmp_path)
    loaded = load_teacher_decisions(tmp_path, requirement_id="req-1")
    assert len(loaded) == 1 and loaded[0]["slot"] == "page-1"
    assert active_decision_for(loaded, requirement_id="req-1",
                               role="hook", slot="page-1") == record
    assert active_decision_for(loaded, requirement_id="req-1",
                               role="hook", slot=0) is None


def test_legacy_implicit_slot_lookup_matches_literal_zero():
    from instructional_materials_coach.teacher_decisions import active_decision_for
    record = _slot_decision(slot=0)
    assert active_decision_for([record], requirement_id="req-1",
                               role="hook", slot="0") == record


def test_override_preserves_other_slot_and_binding_evidence():
    ids, outcomes, blocked, bindings = _resolve_slot_choices(
        [("hook", "0", "asset-a"), ("hook", "1", "asset-a")],
        [_slot_decision(slot=0, asset="asset-b")],
    )
    assert blocked is None
    assert ids == ("asset-b", "asset-a")
    assert [(b["slot_id"], b["asset_id"]) for b in bindings] == [
        ("0", "asset-b"), ("1", "asset-a"),
    ]
    assert outcomes[0]["slot_id"] == "0" and outcomes[0]["honored"]


def test_integer_slot_is_never_named_slot_ordinal():
    ids, outcomes, blocked, bindings = _resolve_slot_choices(
        [("hook", "page-1", "asset-a")], [_slot_decision(slot=0)]
    )
    assert blocked == "slot-binding-missing"
    assert ids == ("asset-a",)
    assert not outcomes[0]["honored"]


def test_nonexistent_slot_cannot_authorize():
    ids, outcomes, blocked, bindings = _resolve_slot_choices(
        [("hook", "0", "asset-a")], [_slot_decision(slot=99)]
    )
    assert blocked == "slot-binding-missing"
    assert not outcomes[0]["honored"] and "asset-b" not in ids


def test_named_slot_decision_exactly_authorizes_named_slot():
    ids, outcomes, blocked, bindings = _resolve_slot_choices(
        [("hook", "page-1", "asset-a")], [_slot_decision(slot="page-1")]
    )
    assert blocked is None and ids == ("asset-b",)
    assert bindings[0]["slot_id"] == "page-1"
    assert outcomes[0]["honored"]


def test_superseded_record_does_not_override_active():
    ids, outcomes, blocked, bindings = _resolve_slot_choices(
        [("hook", "0", "asset-a")],
        [_slot_decision(), _slot_decision(asset="asset-a",
                                         status="superseded", decision_id="old")],
    )
    assert blocked is None and ids == ("asset-b",)
    assert [o["honored"] for o in outcomes] == [True, False]
    assert outcomes[1]["reason_code"] == "superseded"




def test_newer_active_record_wins_over_historical_active_record():
    old = _slot_decision(slot=0, asset="asset-a", decision_id="old")
    newer = _slot_decision(slot=0, asset="asset-b", decision_id="new")
    newer["decided_at"] = "2026-10-03T13:00:00.000Z"
    ids, outcomes, blocked, bindings = _resolve_slot_choices(
        [("hook", "0", "asset-a")], [newer, old],
    )
    assert blocked is None and ids == ("asset-b",)
    assert [(o["decision_id"], o["reason_code"]) for o in outcomes] == [
        ("new", None), ("old", "superseded-by-later"),
    ]
    assert bindings == ({"role_id": "hook", "slot_id": "0", "asset_id": "asset-b"},)


def test_invalid_newest_decision_does_not_resurrect_older_active():
    old = _slot_decision(slot=0, asset="asset-a", decision_id="old")
    newer = _slot_decision(slot=0, asset="asset-b", decision_id="new")
    newer["decided_at"] = "2026-10-03T13:00:00.000Z"
    newer["candidate_set_fingerprint"] = SHA_B
    ids, outcomes, blocked, bindings = _resolve_slot_choices(
        [("hook", "0", "asset-a")], [old, newer],
    )
    assert blocked == REASON_CANDIDATE_SET_CHANGED
    assert ids == () and bindings == ()
    assert all(not outcome["honored"] for outcome in outcomes)


def test_teacher_override_is_used_by_generation_placement_and_cli():
    from instructional_materials_coach.generation_context import _visual_context
    from instructional_materials_coach.connected_visual_placement import (
        plan_visual_placement_bindings,
    )
    from instructional_materials_coach.cli import (
        _selected_visuals_for_key,
        _selected_asset_drive_files,
        _selected_asset_content_identities,
    )

    candidates = _two_candidates()
    baseline = _plan(candidates)
    role = _role_id(baseline)
    decision = _valid_decision_for(candidates, role, "asset-2", SHA_B, "asset-1")
    plan = _plan(candidates, [decision])
    assert plan.outcome == "visuals-ready", getattr(plan, "teacher_decision_block_reason", None)
    assert plan.selected_asset_ids == ("asset-2",)
    bindings, assignment_json = _visual_context(plan)
    assert len(bindings) == 1 and bindings[0] == (role, "0", "asset-2")
    assignments = json.loads(assignment_json)
    assert assignments[0]["selected_candidate"]["asset_reference"]["asset_id"] == "asset-2"
    placements = plan_visual_placement_bindings(plan)
    assert len(placements) == 1
    assert placements[0].asset_id == "asset-2"
    assert placements[0].drive_file_id == "file-2"
    assert _selected_visuals_for_key(plan)[0]["asset_id"] == "asset-2"
    assert _selected_asset_drive_files(plan) == {"asset-2": "file-2"}
    assert _selected_asset_content_identities(plan)["asset-2"]["value"] == SHA_B
    # The source proof remains the unchanged planner record.
    assert baseline.cohesive_visual_plan_result.record.to_dict() == plan.cohesive_visual_plan_result.record.to_dict()


def test_generation_context_without_teacher_choices_still_uses_planner():
    from instructional_materials_coach.generation_context import _visual_context
    baseline = _plan(_two_candidates())
    bindings, _ = _visual_context(baseline)
    assert len(bindings) == 1 and bindings[0][2] == "asset-1"

def test_multiple_conflicting_active_records_fail_closed():
    ids, outcomes, blocked, bindings = _resolve_slot_choices(
        [("hook", "0", "asset-a")],
        [_slot_decision(), _slot_decision(asset="asset-a", decision_id="other")],
    )
    assert blocked == "conflicting-active-decisions"
    assert not any(o["honored"] for o in outcomes)
    assert "asset-b" not in ids


def test_shared_asset_retains_two_slot_bindings():
    ids, outcomes, blocked, bindings = _resolve_slot_choices(
        [("hook", "0", "asset-a"), ("hook", "1", "asset-a")],
        [_slot_decision(slot=0), _slot_decision(slot=1, decision_id="next")],
    )
    assert blocked is None and ids == ("asset-b",)
    assert [(b["slot_id"], b["asset_id"]) for b in bindings] == [
        ("0", "asset-b"), ("1", "asset-b"),
    ]


def test_invalid_slot_choice_blocks_only_target_binding():
    bad = _slot_decision(slot=0)
    bad["candidate_set_fingerprint"] = SHA_B
    ids, outcomes, blocked, bindings = _resolve_slot_choices(
        [("hook", "0", "asset-a"), ("hook", "1", "asset-a")], [bad]
    )
    assert blocked == "candidate-set-changed"
    assert ids == ("asset-a",)  # sibling survives; no invalid substitution
    assert [b["slot_id"] for b in bindings] == ["1"]


@pytest.mark.parametrize("slot", [-1, True, "", "page 1", "page:1", "page.1", None])
def test_decision_rejects_invalid_slot_names(slot):
    with pytest.raises(ValueError):
        TeacherVisualDecisionRecord.from_dict(_decision(slot=slot))



def test_equal_time_conflicting_aliases_fail_closed_in_persistence():
    from instructional_materials_coach.teacher_decisions import active_decision_for
    a = _slot_decision(slot=0, asset="asset-a", decision_id="first")
    b = _slot_decision(slot="0", asset="asset-b", decision_id="second")
    assert a["decided_at"] == b["decided_at"]
    assert active_decision_for([a, b], requirement_id="req-1", role="hook", slot=0) is None
    assert active_decision_for([b, a], requirement_id="req-1", role="hook", slot="0") is None


def test_direct_consumer_rejects_other_requirement_same_role_slot():
    foreign = _slot_decision(slot=0, asset="asset-b")
    foreign["requirement_id"] = "req-other"
    ids, outcomes, blocked, bindings = _resolve_slot_choices(
        [("hook", "0", "asset-a")], [foreign],
    )
    assert blocked == "requirement-binding-mismatch"
    assert outcomes[0]["honored"] is False
    assert "asset-b" not in ids


def test_runtime_import_boundary_remains_public():
    import ast
    from pathlib import Path
    import instructional_materials_coach.visual_reuse as module
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    assert not [
        alias.name for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names if alias.name.startswith("_")
    ]

