from instructional_workflow_contracts import (
    CLASSROOM_UNIT_WORKSPACE_CONTRACT_ID,
    ValidationStatus,
    validate_classroom_unit_workspace,
)


def _binding(role, state, folder_id=None, parent_id=None, name=None, verified=None):
    return {
        "role": role,
        "state": state,
        "drive_folder_id": folder_id,
        "parent_folder_id": parent_id,
        "display_name": name,
        "last_verified": verified,
    }


def _workspace(*bindings, course="course-digital-media", unit="unit-photography-foundations", name="Photography Foundations"):
    return {
        "contract_version": CLASSROOM_UNIT_WORKSPACE_CONTRACT_ID,
        "course_ref": course,
        "unit_ref": unit,
        "display_name": name,
        "role_bindings": list(bindings),
    }


def _root(name="Photography Foundations"):
    return _binding("unit-root", "resolved", "drive-folder-unit-pf", None, name, "2026-09-17T13:00:00Z")


def test_complete_workspace_is_id_backed_and_non_authorizing():
    result = validate_classroom_unit_workspace(
        _workspace(
            _root(),
            _binding("slides", "resolved", "drive-folder-slides", "drive-folder-unit-pf", "Slides", "2026-09-17T13:01:00Z"),
            _binding("student-materials", "unverified", "drive-folder-student", "drive-folder-unit-pf", "Student Materials"),
            _binding("teacher-models", "missing"),
            _binding("visual-assets", "stale", "drive-folder-visuals", "drive-folder-unit-pf", "Visual Assets", "2026-09-01T12:00:00Z"),
        )
    )
    assert result.status is ValidationStatus.VALID
    record = result.record
    assert record is not None
    payload = record.to_dict()
    assert payload["workspace_id"].startswith("classroom-unit-workspace-")
    assert payload["authority"] == {
        "execution_authorized": False,
        "external_write_authorized": False,
        "approval_authorized": False,
        "classroom_readiness_authorized": False,
        "publication_authorized": False,
        "production_authorized": False,
    }


def test_display_name_rename_does_not_change_workspace_identity():
    first = validate_classroom_unit_workspace(_workspace(_root("Photography Foundations"), name="Photography Foundations"))
    renamed = validate_classroom_unit_workspace(_workspace(_root("Photo Foundations"), name="Photo Foundations"))
    assert first.record is not None and renamed.record is not None
    assert first.record.record_id == renamed.record.record_id
    assert first.record.fingerprint != renamed.record.fingerprint


def test_identical_display_names_can_have_distinct_unit_identity():
    one = validate_classroom_unit_workspace(_workspace(_root(), unit="unit-photo-a", name="Photography"))
    two = validate_classroom_unit_workspace(_workspace(_root(), unit="unit-photo-b", name="Photography"))
    assert one.record is not None and two.record is not None
    assert one.record.record_id != two.record.record_id


def test_duplicate_semantic_role_fails_closed():
    result = validate_classroom_unit_workspace(_workspace(_root(), _binding("slides", "missing"), _binding("slides", "missing")))
    assert result.status is ValidationStatus.INVALID
    assert "workspace-role-duplicate" in result.reason_codes


def test_same_folder_cannot_satisfy_incompatible_roles():
    result = validate_classroom_unit_workspace(
        _workspace(
            _root(),
            _binding("slides", "unverified", "drive-folder-shared", "drive-folder-unit-pf"),
            _binding("student-materials", "unverified", "drive-folder-shared", "drive-folder-unit-pf"),
        )
    )
    assert result.status is ValidationStatus.INVALID
    assert "workspace-folder-identity-conflict" in result.reason_codes


def test_missing_and_lazy_roles_are_valid():
    result = validate_classroom_unit_workspace(_workspace(_root(), _binding("teacher-reference", "missing")))
    assert result.status is ValidationStatus.VALID


def test_ambiguous_role_requires_manual_review_without_claiming_id():
    result = validate_classroom_unit_workspace(_workspace(_root(), _binding("visual-assets", "ambiguous")))
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert result.record is not None
    assert "workspace-role-review-required" in result.reason_codes


def test_ambiguous_role_cannot_claim_exact_folder_id():
    result = validate_classroom_unit_workspace(
        _workspace(_root(), _binding("visual-assets", "ambiguous", "drive-folder-maybe"))
    )
    assert result.status is ValidationStatus.INVALID
    assert "workspace-binding-contradiction" in result.reason_codes


def test_resolved_role_requires_currentness_evidence():
    result = validate_classroom_unit_workspace(
        _workspace(_root(), _binding("slides", "resolved", "drive-folder-slides", "drive-folder-unit-pf"))
    )
    assert result.status is ValidationStatus.INVALID
    assert "workspace-currentness-missing" in result.reason_codes


def test_child_parent_contradiction_fails_closed():
    result = validate_classroom_unit_workspace(
        _workspace(
            _root(),
            _binding("slides", "unverified", "drive-folder-slides", "different-parent"),
        )
    )
    assert result.status is ValidationStatus.INVALID
    assert "workspace-parent-contradiction" in result.reason_codes


def test_root_is_required_and_must_have_exact_identity():
    no_root = validate_classroom_unit_workspace(_workspace(_binding("slides", "missing")))
    assert no_root.status is ValidationStatus.INVALID
    missing_root = validate_classroom_unit_workspace(_workspace(_binding("unit-root", "missing")))
    assert missing_root.status is ValidationStatus.INVALID


def test_unsupported_role_fails_closed():
    result = validate_classroom_unit_workspace(_workspace(_root(), _binding("random-folder", "missing")))
    assert result.status is ValidationStatus.INVALID
    assert "workspace-role-unsupported" in result.reason_codes


def test_binding_order_is_canonicalized_for_fingerprint():
    a = validate_classroom_unit_workspace(
        _workspace(_root(), _binding("slides", "missing"), _binding("assessment", "missing"))
    )
    b = validate_classroom_unit_workspace(
        _workspace(_binding("assessment", "missing"), _root(), _binding("slides", "missing"))
    )
    assert a.record is not None and b.record is not None
    assert a.record.fingerprint == b.record.fingerprint
