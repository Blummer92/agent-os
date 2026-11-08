from instructional_workflow_contracts import (
    CLASSROOM_UNIT_WORKSPACE_CONTRACT_ID,
    DriveFolderMetadataReader,
    WorkspaceDriveState,
    execute_workspace_create,
    plan_classroom_workspace_provisioning,
    resolve_classroom_unit_workspace,
    validate_classroom_unit_workspace,
)

FOLDER = "application/vnd.google-apps.folder"


class FakeDrive:
    def __init__(self, metadata=None):
        self.metadata = dict(metadata or {})
        self.created = []
        self.existing = {}
        self.raise_create = False

    def get_file_metadata(self, file_id):
        return self.metadata.get(file_id)

    def create_folder(self, *, name, parent_folder_id, operation_id):
        self.created.append((name, parent_folder_id, operation_id))
        if self.raise_create:
            raise RuntimeError("transport")
        folder_id = "drive-created-" + operation_id[-8:]
        self.metadata[folder_id] = {"id": folder_id, "name": name, "mimeType": FOLDER, "parents": [parent_folder_id], "trashed": False}
        self.existing[operation_id] = (folder_id,)
        return folder_id

    def find_created_folder(self, *, operation_id, parent_folder_id):
        return self.existing.get(operation_id, ())


def _workspace():
    value = {
        "contract_version": CLASSROOM_UNIT_WORKSPACE_CONTRACT_ID,
        "course_ref": "course-digital-media",
        "unit_ref": "unit-photography-foundations",
        "display_name": "Photography Foundations",
        "role_bindings": [
            {"role": "unit-root", "state": "resolved", "drive_folder_id": "drive-unit-root", "parent_folder_id": None, "display_name": "Photography Foundations", "last_verified": "2026-09-17T20:00:00Z"},
            {"role": "visual-assets", "state": "missing", "drive_folder_id": None, "parent_folder_id": None, "display_name": None, "last_verified": None},
        ],
    }
    result = validate_classroom_unit_workspace(value)
    assert result.record is not None
    return result.record


def _root_metadata(name="Photography Foundations"):
    return {"id": "drive-unit-root", "name": name, "mimeType": FOLDER, "parents": [], "trashed": False}


def _plan():
    workspace = _workspace()
    drive = FakeDrive({"drive-unit-root": _root_metadata()})
    resolution = resolve_classroom_unit_workspace(workspace, DriveFolderMetadataReader(drive))
    assert resolution.record is not None
    planned = plan_classroom_workspace_provisioning(workspace, resolution.record, ["visual-assets"])
    assert planned.record is not None
    return planned.record


def _operation_id(plan):
    return plan.to_dict()["operations"][0]["operation_id"]


def test_exact_id_metadata_normalizes_and_rename_does_not_change_identity():
    drive = FakeDrive({"drive-unit-root": _root_metadata("Renamed Unit")})
    metadata = DriveFolderMetadataReader(drive).get_folder_metadata("drive-unit-root")
    assert metadata["drive_folder_id"] == "drive-unit-root"
    assert metadata["display_name"] == "Renamed Unit"
    assert metadata["mime_type"] == FOLDER


def test_returned_id_mismatch_is_ambiguous_to_existing_resolver():
    workspace = _workspace()
    drive = FakeDrive({"drive-unit-root": {**_root_metadata(), "id": "different-id"}})
    result = resolve_classroom_unit_workspace(workspace, DriveFolderMetadataReader(drive))
    assert result.status.value == "manual-review-required"


def test_multiple_parents_fail_closed_as_ambiguous():
    workspace = _workspace()
    drive = FakeDrive({"drive-unit-root": {**_root_metadata(), "parents": ["parent-a", "parent-b"]}})
    result = resolve_classroom_unit_workspace(workspace, DriveFolderMetadataReader(drive))
    assert result.status.value == "manual-review-required"


def test_wrong_kind_and_trashed_are_preserved_for_drive2():
    workspace = _workspace()
    wrong = FakeDrive({"drive-unit-root": {**_root_metadata(), "mimeType": "text/plain"}})
    trashed = FakeDrive({"drive-unit-root": {**_root_metadata(), "trashed": True}})
    assert resolve_classroom_unit_workspace(workspace, DriveFolderMetadataReader(wrong)).record.to_dict()["role_resolutions"][0]["outcome"] == "wrong-kind"
    assert resolve_classroom_unit_workspace(workspace, DriveFolderMetadataReader(trashed)).record.to_dict()["role_resolutions"][0]["outcome"] == "trashed"


def test_dry_run_performs_zero_create_calls():
    plan = _plan()
    drive = FakeDrive({"drive-unit-root": _root_metadata()})
    result = execute_workspace_create(plan, _operation_id(plan), client=drive, dry_run=True)
    assert result.state is WorkspaceDriveState.DRY_RUN
    assert drive.created == []
    assert result.external_write_performed is False


def test_one_missing_role_creates_once_and_requires_exact_readback():
    plan = _plan()
    drive = FakeDrive({"drive-unit-root": _root_metadata()})
    result = execute_workspace_create(plan, _operation_id(plan), client=drive, dry_run=False)
    assert result.state is WorkspaceDriveState.CREATED_VERIFIED
    assert len(drive.created) == 1
    assert drive.created[0][1] == "drive-unit-root"
    assert result.readback_verified is True
    assert result.external_write_performed is True
    assert not result.approval_authorized
    assert not result.classroom_readiness_authorized
    assert not result.publication_authorized
    assert not result.production_authorized


def test_retry_reconciles_existing_before_second_create():
    plan = _plan()
    drive = FakeDrive({"drive-unit-root": _root_metadata()})
    first = execute_workspace_create(plan, _operation_id(plan), client=drive, dry_run=False)
    second = execute_workspace_create(plan, _operation_id(plan), client=drive, dry_run=False)
    assert first.state is WorkspaceDriveState.CREATED_VERIFIED
    assert second.state is WorkspaceDriveState.RECONCILED_EXISTING
    assert len(drive.created) == 1


def test_transport_failure_reconciles_when_create_actually_happened():
    plan = _plan()
    drive = FakeDrive({"drive-unit-root": _root_metadata()})
    operation_id = _operation_id(plan)

    def ambiguous_create(*, name, parent_folder_id, operation_id):
        folder_id = "drive-after-transport"
        drive.metadata[folder_id] = {"id": folder_id, "name": name, "mimeType": FOLDER, "parents": [parent_folder_id], "trashed": False}
        drive.existing[operation_id] = (folder_id,)
        raise RuntimeError("transport")

    drive.create_folder = ambiguous_create
    result = execute_workspace_create(plan, operation_id, client=drive, dry_run=False)
    assert result.state is WorkspaceDriveState.RECONCILED_EXISTING
    assert result.folder_id == "drive-after-transport"


def test_transport_failure_without_proof_is_ambiguous_not_retry():
    plan = _plan()
    drive = FakeDrive({"drive-unit-root": _root_metadata()})
    drive.raise_create = True
    result = execute_workspace_create(plan, _operation_id(plan), client=drive, dry_run=False)
    assert result.state is WorkspaceDriveState.AMBIGUOUS_WRITE_RESULT
    assert len(drive.created) == 1


def test_parent_is_revalidated_immediately_before_create():
    plan = _plan()
    drive = FakeDrive({"drive-unit-root": {**_root_metadata(), "trashed": True}})
    result = execute_workspace_create(plan, _operation_id(plan), client=drive, dry_run=False)
    assert result.state is WorkspaceDriveState.PRECHECK_FAILED
    assert drive.created == []


def test_wrong_readback_parent_fails_closed():
    plan = _plan()
    drive = FakeDrive({"drive-unit-root": _root_metadata()})

    def create_wrong_parent(*, name, parent_folder_id, operation_id):
        folder_id = "drive-wrong-parent"
        drive.created.append((name, parent_folder_id, operation_id))
        drive.metadata[folder_id] = {"id": folder_id, "name": name, "mimeType": FOLDER, "parents": ["somewhere-else"], "trashed": False}
        return folder_id

    drive.create_folder = create_wrong_parent
    result = execute_workspace_create(plan, _operation_id(plan), client=drive, dry_run=False)
    assert result.state is WorkspaceDriveState.READBACK_FAILED


def test_tampered_operation_fingerprint_fails_closed():
    plan = _plan()
    payload = plan.to_dict()
    payload["operations"][0]["operation_fingerprint"] = "0" * 64
    from instructional_workflow_contracts.common import ValidatedRecord, freeze_json, sha256_hex
    tampered = ValidatedRecord(plan.contract_version, plan.record_id, plan.record_revision, plan.fingerprint_algorithm, sha256_hex(payload), freeze_json(payload))
    drive = FakeDrive({"drive-unit-root": _root_metadata()})
    result = execute_workspace_create(tampered, _operation_id(tampered), client=drive, dry_run=False)
    assert result.state is WorkspaceDriveState.PRECHECK_FAILED
    assert drive.created == []
