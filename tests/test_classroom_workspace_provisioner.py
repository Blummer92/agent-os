from instructional_workflow_contracts import (
    CLASSROOM_UNIT_WORKSPACE_CONTRACT_ID,
    CLASSROOM_WORKSPACE_FOLDER_MIME_TYPE,
    ValidationStatus,
    plan_classroom_workspace_provisioning,
    resolve_classroom_unit_workspace,
    validate_classroom_unit_workspace,
)


class Reader:
    def __init__(self, rows):
        self.rows = rows

    def get_folder_metadata(self, folder_id):
        return self.rows.get(folder_id)


def binding(role, state, folder_id=None, parent=None, verified=None):
    return {
        "role": role,
        "state": state,
        "drive_folder_id": folder_id,
        "parent_folder_id": parent,
        "display_name": None,
        "last_verified": verified,
    }


def workspace(*children):
    result = validate_classroom_unit_workspace(
        {
            "contract_version": CLASSROOM_UNIT_WORKSPACE_CONTRACT_ID,
            "course_ref": "course-digital-media",
            "unit_ref": "unit-photography-foundations",
            "display_name": "Photography Foundations",
            "role_bindings": [
                binding("unit-root", "resolved", "drive-unit-root", verified="2026-09-17T14:00:00Z"),
                *children,
            ],
        }
    )
    assert result.record is not None
    return result.record


def folder(folder_id, parent=None, *, name="Folder", accessible=True, trashed=False, mime=None):
    return {
        "drive_folder_id": folder_id,
        "parent_folder_id": parent,
        "display_name": name,
        "mime_type": mime or CLASSROOM_WORKSPACE_FOLDER_MIME_TYPE,
        "accessible": accessible,
        "trashed": trashed,
    }


def resolved(ws, rows):
    result = resolve_classroom_unit_workspace(ws, Reader(rows))
    assert result.record is not None
    return result.record


def test_current_roles_are_no_op_and_never_duplicate_create():
    ws = workspace(binding("slides", "unverified", "drive-slides", "drive-unit-root"))
    resolution = resolved(ws, {"drive-unit-root": folder("drive-unit-root"), "drive-slides": folder("drive-slides", "drive-unit-root")})
    result = plan_classroom_workspace_provisioning(ws, resolution, ["slides"])
    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    assert result.reason_codes == ()
    payload = result.record.to_dict()
    assert payload["overall_state"] == "no-op"
    assert payload["operations"][0]["operation_type"] == "no-op"


def test_missing_role_plans_one_exact_parent_create():
    ws = workspace(binding("visual-assets", "missing"))
    resolution = resolved(ws, {"drive-unit-root": folder("drive-unit-root")})
    result = plan_classroom_workspace_provisioning(ws, resolution, ["visual-assets"])
    assert result.status is ValidationStatus.VALID
    assert result.reason_codes == ()
    assert result.record is not None
    payload = result.record.to_dict()
    op = payload["operations"][0]
    assert payload["overall_state"] == "planned"
    assert op["operation_type"] == "create-folder"
    assert op["parent_folder_id"] == "drive-unit-root"
    assert op["display_name"] == "Visual Assets"
    assert op["expected_postconditions"]["requires_exact_id_readback"] is True


def test_same_inputs_produce_same_plan_and_operation_identity():
    ws = workspace(binding("slides", "missing"), binding("assessment", "missing"))
    resolution = resolved(ws, {"drive-unit-root": folder("drive-unit-root")})
    a = plan_classroom_workspace_provisioning(ws, resolution, ["slides", "assessment"])
    b = plan_classroom_workspace_provisioning(ws, resolution, ["assessment", "slides"])
    assert a.record is not None and b.record is not None
    assert a.record.record_id == b.record.record_id
    assert a.record.fingerprint == b.record.fingerprint


def test_display_name_override_does_not_change_operation_identity():
    ws = workspace(binding("student-materials", "missing"))
    resolution = resolved(ws, {"drive-unit-root": folder("drive-unit-root")})
    default = plan_classroom_workspace_provisioning(ws, resolution, ["student-materials"])
    custom = plan_classroom_workspace_provisioning(
        ws, resolution, ["student-materials"], display_name_overrides={"student-materials": "Worksheets & Handouts"}
    )
    assert default.record is not None and custom.record is not None
    d = default.record.to_dict()["operations"][0]
    c = custom.record.to_dict()["operations"][0]
    assert d["operation_id"] == c["operation_id"]
    assert d["operation_fingerprint"] != c["operation_fingerprint"]


def test_moved_role_requires_review_and_never_plans_replacement():
    ws = workspace(binding("slides", "unverified", "drive-slides", "drive-unit-root"))
    resolution = resolved(ws, {"drive-unit-root": folder("drive-unit-root"), "drive-slides": folder("drive-slides", "other-parent")})
    result = plan_classroom_workspace_provisioning(ws, resolution, ["slides"])
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert result.record.to_dict()["operations"][0]["operation_type"] == "manual-review"


def test_inaccessible_role_blocks_and_never_plans_replacement():
    ws = workspace(binding("visual-assets", "unverified", "drive-visuals", "drive-unit-root"))
    resolution = resolved(ws, {"drive-unit-root": folder("drive-unit-root"), "drive-visuals": folder("drive-visuals", "drive-unit-root", accessible=False)})
    result = plan_classroom_workspace_provisioning(ws, resolution, ["visual-assets"])
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert result.record.to_dict()["operations"][0]["operation_type"] == "blocked"


def test_unhealthy_root_blocks_every_requested_create():
    ws = workspace(binding("slides", "missing"))
    resolution = resolved(ws, {})
    result = plan_classroom_workspace_provisioning(ws, resolution, ["slides"])
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    payload = result.record.to_dict()
    assert payload["unit_root_folder_id"] is None
    assert payload["operations"][0]["operation_type"] == "blocked"


def test_unsupported_or_duplicate_requested_role_fails_closed():
    ws = workspace(binding("slides", "missing"))
    resolution = resolved(ws, {"drive-unit-root": folder("drive-unit-root")})
    unsupported = plan_classroom_workspace_provisioning(ws, resolution, ["unit-root"])
    duplicate = plan_classroom_workspace_provisioning(ws, resolution, ["slides", "slides"])
    assert unsupported.status is ValidationStatus.INVALID
    assert duplicate.status is ValidationStatus.INVALID


def test_resolution_from_different_workspace_fails_lineage_check():
    ws = workspace(binding("slides", "missing"))
    other_result = validate_classroom_unit_workspace(
        {
            "contract_version": CLASSROOM_UNIT_WORKSPACE_CONTRACT_ID,
            "course_ref": "course-digital-media",
            "unit_ref": "unit-other",
            "display_name": "Other",
            "role_bindings": [binding("unit-root", "resolved", "other-root", verified="2026-09-17T14:00:00Z"), binding("slides", "missing")],
        }
    )
    other = other_result.record
    assert other is not None
    resolution = resolved(other, {"other-root": folder("other-root")})
    result = plan_classroom_workspace_provisioning(ws, resolution, ["slides"])
    assert result.status is ValidationStatus.INVALID
    assert "destination-workspace-plan-lineage-mismatch" in result.reason_codes


def test_plan_authority_is_always_false():
    ws = workspace(binding("teacher-reference", "missing"))
    resolution = resolved(ws, {"drive-unit-root": folder("drive-unit-root")})
    result = plan_classroom_workspace_provisioning(ws, resolution, ["teacher-reference"])
    assert result.record is not None
    assert not any(result.record.to_dict()["authority"].values())
