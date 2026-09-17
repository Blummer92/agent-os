from instructional_workflow_contracts.classroom_unit_workspace import (
    CONTRACT_ID as WORKSPACE_CONTRACT_ID,
    validate_classroom_unit_workspace,
)
from instructional_workflow_contracts.classroom_unit_workspace_resolver import (
    FOLDER_MIME_TYPE,
    resolve_classroom_unit_workspace,
)
from instructional_workflow_contracts import ValidationStatus


class FakeReader:
    def __init__(self, metadata):
        self.metadata = metadata
        self.calls = []

    def get_folder_metadata(self, folder_id):
        self.calls.append(folder_id)
        return self.metadata.get(folder_id)


def _binding(role, state, folder_id=None, parent=None, name=None, verified=None):
    return {
        "role": role,
        "state": state,
        "drive_folder_id": folder_id,
        "parent_folder_id": parent,
        "display_name": name,
        "last_verified": verified,
    }


def _workspace(*bindings):
    result = validate_classroom_unit_workspace(
        {
            "contract_version": WORKSPACE_CONTRACT_ID,
            "course_ref": "course-digital-media",
            "unit_ref": "unit-photography-foundations",
            "display_name": "Photography Foundations",
            "role_bindings": list(bindings),
        }
    )
    assert result.record is not None
    return result.record


def _root(state="unverified", name="Photography Foundations"):
    return _binding("unit-root", state, "drive-unit", None, name, "2026-09-17T13:00:00Z" if state == "resolved" else None)


def _folder(folder_id, parent=None, name="Folder", **extra):
    value = {
        "drive_folder_id": folder_id,
        "parent_folder_id": parent,
        "display_name": name,
        "mime_type": FOLDER_MIME_TYPE,
        "trashed": False,
        "accessible": True,
    }
    value.update(extra)
    return value


def test_exact_ids_resolve_and_renames_do_not_cause_drift():
    workspace = _workspace(
        _root(name="Old Unit Name"),
        _binding("slides", "stale", "drive-slides", "drive-unit", "Old Slides", "2026-08-01"),
    )
    reader = FakeReader(
        {
            "drive-unit": _folder("drive-unit", name="New Unit Name"),
            "drive-slides": _folder("drive-slides", "drive-unit", "Presentation Decks"),
        }
    )
    result = resolve_classroom_unit_workspace(workspace, reader)
    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    payload = result.record.to_dict()
    assert payload["overall_state"] == "resolved"
    slides = next(item for item in payload["role_resolutions"] if item["role"] == "slides")
    assert slides["outcome"] == "resolved"
    assert slides["current_display_name"] == "Presentation Decks"
    assert reader.calls == ["drive-unit", "drive-slides"]


def test_lazy_missing_role_does_not_trigger_name_search_or_reader_call():
    workspace = _workspace(_root(), _binding("visual-assets", "missing", name="Visual Assets"))
    reader = FakeReader({"drive-unit": _folder("drive-unit")})
    result = resolve_classroom_unit_workspace(workspace, reader)
    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    assert result.record.to_dict()["overall_state"] == "partial"
    assert reader.calls == ["drive-unit"]


def test_manual_child_move_is_detected():
    workspace = _workspace(_root(), _binding("slides", "unverified", "drive-slides", "drive-unit"))
    reader = FakeReader(
        {
            "drive-unit": _folder("drive-unit"),
            "drive-slides": _folder("drive-slides", "different-parent"),
        }
    )
    result = resolve_classroom_unit_workspace(workspace, reader)
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert result.record is not None
    assert result.record.to_dict()["overall_state"] == "stale"
    assert "workspace-resolution-drift" in result.reason_codes


def test_missing_root_fails_to_manual_review_without_replacement_search():
    workspace = _workspace(_root(), _binding("slides", "missing"))
    reader = FakeReader({})
    result = resolve_classroom_unit_workspace(workspace, reader)
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert result.record is not None
    assert result.record.to_dict()["overall_state"] == "missing"
    assert reader.calls == ["drive-unit"]


def test_trashed_inaccessible_and_wrong_kind_are_explicit_drift():
    cases = [
        _folder("drive-slides", "drive-unit", trashed=True),
        _folder("drive-slides", "drive-unit", accessible=False),
        _folder("drive-slides", "drive-unit", mime_type="application/pdf"),
    ]
    expected = ["trashed", "inaccessible", "wrong-kind"]
    for metadata, outcome in zip(cases, expected):
        workspace = _workspace(_root(), _binding("slides", "unverified", "drive-slides", "drive-unit"))
        result = resolve_classroom_unit_workspace(
            workspace,
            FakeReader({"drive-unit": _folder("drive-unit"), "drive-slides": metadata}),
        )
        assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
        assert result.record is not None
        role = next(item for item in result.record.to_dict()["role_resolutions"] if item["role"] == "slides")
        assert role["outcome"] == outcome


def test_contradictory_exact_id_metadata_requires_review():
    workspace = _workspace(_root())
    reader = FakeReader({"drive-unit": _folder("different-id")})
    result = resolve_classroom_unit_workspace(workspace, reader)
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert result.record is not None
    assert result.record.to_dict()["overall_state"] == "ambiguous"


def test_result_is_non_authorizing():
    workspace = _workspace(_root())
    result = resolve_classroom_unit_workspace(workspace, FakeReader({"drive-unit": _folder("drive-unit")}))
    assert result.record is not None
    assert all(value is False for value in result.record.to_dict()["authority"].values())


def test_invalid_or_tampered_workspace_is_rejected_before_reader_use():
    workspace = _workspace(_root())
    reader = FakeReader({"drive-unit": _folder("drive-unit")})
    from instructional_workflow_contracts.common import ValidatedRecord

    tampered = ValidatedRecord(
        contract_version=workspace.contract_version,
        record_id=workspace.record_id,
        record_revision=workspace.record_revision,
        fingerprint_algorithm=workspace.fingerprint_algorithm,
        fingerprint="0" * 64,
        payload=workspace.payload,
    )
    result = resolve_classroom_unit_workspace(tampered, reader)
    assert result.status is ValidationStatus.INVALID
    assert reader.calls == []
