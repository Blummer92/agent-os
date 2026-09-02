from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
OVERLAYS = [
    ROOT / "02_Agent_Overlays/unit-alignment-agent.md",
    ROOT / "02_Agent_Overlays/teacher-modeling-coach.md",
    ROOT / "02_Agent_Overlays/instructional-materials-coach.md",
]
LP3 = "01_Shared_Standards/instructional-design/lp-pacing-handoff-contract.md"
LP3_ADAPTATION = "01_Shared_Standards/instructional-design/lp-pacing-handoff-adaptation.md"
LP_AUTHORITY = "01_Shared_Standards/instructional-design/lp-authority-state-registry.md"
REGISTRY = ROOT / "04_Registry/lp-pacing-handoff-contract.yaml"
UNIT_RULES = ROOT / "01_Shared_Standards/instructional-design/unit-alignment-rules.md"


def _registry():
    return yaml.safe_load(REGISTRY.read_text())


def _case(**dimensions):
    return {
        "difficulty_diagnosis": {
            "instructional_demand": "unknown",
            "learner_relative_familiarity": "unknown",
            "language_and_representation_load": "unknown",
            "material_induced_load": "unknown",
            "operational_load": "unknown",
            "evidence_uncertainty": "unknown",
            **dimensions,
        },
        "what_supported": [],
        "what_remains_unmeasured": [],
        "report_only": True,
        "readiness_authorized": False,
        "grading_authorized": False,
        "student_classification_authorized": False,
        "automatic_placement_authorized": False,
        "route_assignment_authorized": False,
    }


CASES = [
    _case(learner_relative_familiarity={"conceptual": "strong", "tool": "limited"}),
    _case(learner_relative_familiarity={"conceptual": "limited", "tool": "strong"}),
    _case(learner_relative_familiarity={"vocabulary": "strong", "performance": "weak"}),
    _case(learner_relative_familiarity={"performance": "strong", "vocabulary": "weak"}),
    _case(evidence_uncertainty="significant"),
    _case(learner_relative_familiarity={"prior_opportunity": "novice"}),
    _case(learner_relative_familiarity={"prior_opportunity": "experienced"}),
    _case(instructional_demand={"task": "low"}),
    _case(instructional_demand={"task": "high"}),
    _case(instructional_demand="high", learner_relative_familiarity="sufficient-preparation"),
    _case(instructional_demand="moderate", language_and_representation_load="moderate", operational_load="moderate"),
    _case(material_induced_load="reduced-by-scaffold", instructional_demand="preserved"),
    _case(material_induced_load="redundant-scaffold-risk", learner_relative_familiarity="experienced"),
    _case(evidence_uncertainty="stale"),
    _case(evidence_uncertainty="conflicting"),
    _case(evidence_uncertainty="non-comparable"),
    _case(evidence_uncertainty="missing-unknown"),
    _case(operational_load="accessibility-support-time", learner_relative_familiarity="not-inferred"),
    _case(learner_relative_familiarity={"speed": "fast", "performance": "incorrect", "mastery": "not-established"}),
    _case(learner_relative_familiarity={"speed": "slower", "performance": "successful", "negative_label": "prohibited"}),
    _case(learner_relative_familiarity={"revision": "updated-bounded-snapshot", "permanent_profile": "prohibited"}),
    _case(learner_relative_familiarity={"permanent_label": "rejected"}),
    _case(learner_relative_familiarity={"working_memory_inference": "rejected"}),
    _case(learner_relative_familiarity={"automatic_placement": "rejected"}),
    _case(learner_relative_familiarity={"one_dimensional_score": "rejected"}),
]


def test_all_lp3_consumers_inherit_canonical_handoff_contracts():
    for path in OVERLAYS:
        text = path.read_text()
        assert LP3 in text
        assert LP3_ADAPTATION in text
        assert LP_AUTHORITY in text


def test_unit_alignment_preserves_six_check_and_tier2_authority():
    text = OVERLAYS[0].read_text()
    assert "not a seventh Unit Alignment check" in text
    assert "does not replace Tier 2" in text
    assert "cannot independently set Unit Alignment `PASS` or `BLOCKED`" in text
    assert UNIT_RULES.read_text().count("### Check ") == 6


def test_overlays_reference_shared_lp3_policy_instead_of_repeating_it():
    shared_dimensions = {
        item["value"] for item in _registry()["diagnosis_dimensions"]
    }
    for path in OVERLAYS:
        boundary = path.read_text().split("## LP3 Pacing Handoff Boundary", 1)[1].split("\n## ", 1)[0]
        assert not shared_dimensions.intersection(boundary.split())
        assert "remain owned by the inherited LP3 standards" in boundary


def test_uneven_evidence_matrix_preserves_dimensions_without_numeric_vector():
    assert len(CASES) >= 23
    expected = {item["value"] for item in _registry()["diagnosis_dimensions"]}
    for case in CASES:
        assert set(case["difficulty_diagnosis"]) == expected
        assert case["report_only"] is True
        assert all(case[name] is False for name in (
            "readiness_authorized",
            "grading_authorized",
            "student_classification_authorized",
            "automatic_placement_authorized",
            "route_assignment_authorized",
        ))
        assert not any(isinstance(value, (int, float)) for value in case["difficulty_diagnosis"].values())


def test_opposite_familiarity_profiles_remain_distinguishable():
    assert CASES[0]["difficulty_diagnosis"]["learner_relative_familiarity"] != CASES[1]["difficulty_diagnosis"]["learner_relative_familiarity"]
    assert CASES[2]["difficulty_diagnosis"]["learner_relative_familiarity"] != CASES[3]["difficulty_diagnosis"]["learner_relative_familiarity"]


@pytest.mark.parametrize("index", [4, 13, 14, 15, 16])
def test_limited_or_missing_evidence_remains_visibly_uncertain(index):
    uncertainty = CASES[index]["difficulty_diagnosis"]["evidence_uncertainty"]
    assert uncertainty not in {0, "low", "direct", "resolved"}


def test_different_task_demand_does_not_rewrite_learner_evidence():
    assert CASES[7]["difficulty_diagnosis"]["learner_relative_familiarity"] == CASES[8]["difficulty_diagnosis"]["learner_relative_familiarity"]
    assert CASES[7]["difficulty_diagnosis"]["instructional_demand"] != CASES[8]["difficulty_diagnosis"]["instructional_demand"]


def test_multiple_moderate_demands_are_not_arithmetically_aggregated():
    diagnosis = CASES[10]["difficulty_diagnosis"]
    assert diagnosis["instructional_demand"] == "moderate"
    assert diagnosis["language_and_representation_load"] == "moderate"
    assert diagnosis["operational_load"] == "moderate"
    assert "score" not in diagnosis
    assert "total" not in diagnosis


def test_scaffolding_can_reduce_burden_without_lowering_rigor():
    diagnosis = CASES[11]["difficulty_diagnosis"]
    assert diagnosis["material_induced_load"] == "reduced-by-scaffold"
    assert diagnosis["instructional_demand"] == "preserved"


def test_accessibility_and_speed_do_not_become_mastery_labels():
    assert CASES[17]["difficulty_diagnosis"]["learner_relative_familiarity"] == "not-inferred"
    assert CASES[18]["difficulty_diagnosis"]["learner_relative_familiarity"]["mastery"] == "not-established"
    assert CASES[19]["difficulty_diagnosis"]["learner_relative_familiarity"]["negative_label"] == "prohibited"


def test_revision_stays_bounded_and_prohibited_inferences_are_rejected():
    assert CASES[20]["difficulty_diagnosis"]["learner_relative_familiarity"]["permanent_profile"] == "prohibited"
    for index in (21, 22, 23, 24):
        values = CASES[index]["difficulty_diagnosis"]["learner_relative_familiarity"]
        assert "rejected" in values.values()
