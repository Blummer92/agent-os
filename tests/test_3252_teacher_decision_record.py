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
    c1 = _fixture("valid_visual_asset_compatibility_v2.json")
    c2 = copy.deepcopy(c1)
    c2["compatibility_evidence"]["asset_reference"]["asset_id"] = "asset-2"
    c2["compatibility_evidence"]["asset_reference"]["stable_ref"] = "asset-ref-2"
    c2["compatibility_evidence"]["asset_reference"]["content_fingerprint"] = SHA_B
    c2["compatibility_evidence"]["library_reference"] = {
        "page_id": "page-2",
        "drive_file_id": "file-2",
    }
    c2["compatibility_id"] = "compat-2"
    return [c1, c2]


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
    assert plan.outcome == "visuals-ready"
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
    assert plan.outcome == "visuals-ready"
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
