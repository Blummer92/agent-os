from copy import deepcopy

GOVERNED_FIELDS = {
    "source_evidence",
    "confirmation_state",
    "material_safety",
    "assessment_eligibility",
    "readiness",
    "production_authorized",
}


def consume_handoff(
    payload: dict,
    *,
    consumer: str,
    required_fields: tuple[str, ...],
    route_back: str,
    proposed_changes: dict | None = None,
) -> dict:
    """Test-local semantic boundary checker; never used as runtime routing code."""
    result = deepcopy(payload)
    proposed_changes = proposed_changes or {}
    changed_governed = sorted(
        field
        for field, value in proposed_changes.items()
        if field in GOVERNED_FIELDS and result.get(field) != value
    )
    if changed_governed:
        return {
            **result,
            "status": "REJECTED",
            "consumer": consumer,
            "rejected_fields": changed_governed,
            "next_owner": route_back,
        }

    missing = sorted(field for field in required_fields if not result.get(field))
    if missing:
        return {
            **result,
            "status": "BLOCKED",
            "consumer": consumer,
            "missing_fields": missing,
            "next_owner": route_back,
        }

    result.update(proposed_changes)
    result.update(
        {
            "status": "ACCEPTED",
            "consumer": consumer,
            "rerun_upstream": False,
            "rebuild_upstream": False,
        }
    )
    return result


UNIT_ALIGNMENT_HANDOFF = {
    "lesson_goal": "Compose a balanced thumbnail sketch.",
    "student_task": "Create three thumbnail variations.",
    "source_evidence": "canonical-confirmed",
    "confirmation_state": "confirmed",
    "material_safety": "approved-for-modeling",
    "assessment_eligibility": "not-yet",
    "readiness": "ready-for-modeling",
    "production_authorized": False,
    "artifact_authorized": False,
    "execution_authorized": False,
    "blockers": [],
}

TEACHER_MODELING_EXTRACT = {
    **UNIT_ALIGNMENT_HANDOFF,
    "teacher_says": "I will compare the shapes before I add detail.",
    "teacher_does": "Sketches three small boxes and varies the focal point.",
    "students_do": "Notice how each version changes the visual hierarchy.",
    "check": "Students can point to the focal point in each thumbnail.",
    "support_move": "Return to shape and contrast before adding detail.",
    "next_owner": "Instructional Materials Coach",
}


def test_complete_unit_alignment_handoff_is_accepted_without_rerun() -> None:
    result = consume_handoff(
        UNIT_ALIGNMENT_HANDOFF,
        consumer="Teacher Modeling Coach",
        required_fields=("lesson_goal", "student_task", "source_evidence", "readiness"),
        route_back="Unit Alignment Agent",
    )
    assert result["status"] == "ACCEPTED"
    assert result["rerun_upstream"] is False
    assert result["source_evidence"] == "canonical-confirmed"


def test_complete_modeling_extract_is_accepted_without_rebuild() -> None:
    result = consume_handoff(
        TEACHER_MODELING_EXTRACT,
        consumer="Instructional Materials Coach",
        required_fields=("teacher_says", "teacher_does", "students_do", "check"),
        route_back="Teacher Modeling Coach",
    )
    assert result["status"] == "ACCEPTED"
    assert result["rebuild_upstream"] is False
    assert result["teacher_says"] == TEACHER_MODELING_EXTRACT["teacher_says"]


def test_missing_required_modeling_field_routes_back_with_exact_name() -> None:
    incomplete = {**TEACHER_MODELING_EXTRACT, "check": ""}
    result = consume_handoff(
        incomplete,
        consumer="Instructional Materials Coach",
        required_fields=("teacher_says", "teacher_does", "students_do", "check"),
        route_back="Teacher Modeling Coach",
    )
    assert result["status"] == "BLOCKED"
    assert result["missing_fields"] == ["check"]
    assert result["next_owner"] == "Teacher Modeling Coach"


def test_downstream_attempt_to_change_governed_fields_is_rejected() -> None:
    for field in sorted(GOVERNED_FIELDS):
        changed_value = "mutated" if field != "production_authorized" else True
        result = consume_handoff(
            TEACHER_MODELING_EXTRACT,
            consumer="Instructional Materials Coach",
            required_fields=("teacher_says",),
            route_back="Teacher Modeling Coach",
            proposed_changes={field: changed_value},
        )
        assert result["status"] == "REJECTED"
        assert result["rejected_fields"] == [field]
        assert result[field] == TEACHER_MODELING_EXTRACT[field]


def test_content_only_handoff_preserves_artifact_non_authorization() -> None:
    result = consume_handoff(
        TEACHER_MODELING_EXTRACT,
        consumer="Instructional Materials Coach",
        required_fields=("teacher_says",),
        route_back="Teacher Modeling Coach",
        proposed_changes={"worksheet_note": "Use the approved sentence frame."},
    )
    assert result["status"] == "ACCEPTED"
    assert result["artifact_authorized"] is False


def test_blockers_and_execution_non_authorization_survive_handoff() -> None:
    payload = {
        **TEACHER_MODELING_EXTRACT,
        "blockers": ["Confirm the visual anchor before production."],
        "execution_authorized": False,
    }
    result = consume_handoff(
        payload,
        consumer="Instructional Materials Coach",
        required_fields=("teacher_says",),
        route_back="Teacher Modeling Coach",
    )
    assert result["status"] == "ACCEPTED"
    assert result["blockers"] == payload["blockers"]
    assert result["execution_authorized"] is False
