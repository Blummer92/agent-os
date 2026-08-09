from dataclasses import replace

from visual_asset_drive_writer import (
    DriveAssetWriteRequest, DriveFileEvidence, Representation, WriteState,
    operation_key_for, write_asset,
)

SHA = "a" * 64


def request(**changes):
    base = DriveAssetWriteRequest("intake-1", Representation.ORIGINAL, "/safe/image.jpg", SHA, "image/jpeg", "folder-123", "CONFIRMED", True, True)
    return replace(base, **changes)


class FakeDrive:
    def __init__(self):
        self.calls = []
        self.files = {}
        self.raise_after_create = False

    def find_by_operation_key(self, key):
        self.calls.append(("find", key))
        return tuple(v for v in self.files.values() if v.operation_key == key)

    def reserve_file_id(self):
        self.calls.append(("reserve",))
        return "file-1"

    def create_file(self, *, file_id, request, operation_key):
        self.calls.append(("create", file_id))
        self.files[file_id] = DriveFileEvidence(file_id, request.parent_folder_id, request.mime_type, request.content_sha256, operation_key)
        if self.raise_after_create:
            raise RuntimeError("transport")

    def fetch_file(self, file_id):
        self.calls.append(("fetch", file_id))
        return self.files.get(file_id)


def test_dry_run_makes_zero_drive_calls():
    fake = FakeDrive()
    result = write_asset(request(), fake)
    assert result.state is WriteState.DRY_RUN
    assert result.external_write_performed is False
    assert fake.calls == []


def test_operation_key_ignores_filename_and_is_destination_bound():
    a = request(local_reference="/a/one.jpg")
    b = request(local_reference="/b/two.jpg")
    assert operation_key_for(a) == operation_key_for(b)
    assert operation_key_for(a) != operation_key_for(request(parent_folder_id="folder-456"))


def test_unconfirmed_or_stale_route_fails_before_client_call():
    fake = FakeDrive()
    assert write_asset(request(routing_state="RECOMMENDED"), fake).state is WriteState.PRECHECK_FAILED
    assert write_asset(request(destination_current=False), fake).state is WriteState.PRECHECK_FAILED
    assert fake.calls == []


def test_invalid_fields_return_typed_safe_defaults():
    result = write_asset(request(parent_folder_id=1, dry_run=1))
    assert result.state is WriteState.PRECHECK_FAILED
    assert result.dry_run is True
    assert result.parent_folder_id is None
    assert result.mime_type is None
    assert result.content_sha256 is None


def test_non_dry_write_requires_injected_client():
    result = write_asset(request(dry_run=False))
    assert result.state is WriteState.PRECHECK_FAILED
    assert result.reason_codes == ("drive-client-required",)


def test_create_requires_exact_readback_to_verify():
    fake = FakeDrive()
    result = write_asset(request(dry_run=False), fake)
    assert result.state is WriteState.VERIFIED
    assert result.file_id == "file-1"
    assert result.readback_verified is True
    assert result.external_write_performed is True
    assert [c[0] for c in fake.calls] == ["find", "reserve", "create", "fetch"]


def test_retry_reconciles_existing_with_readback_without_second_create():
    fake = FakeDrive()
    req = request(dry_run=False)
    key = operation_key_for(req)
    fake.files["existing"] = DriveFileEvidence("existing", req.parent_folder_id, req.mime_type, req.content_sha256, key)
    result = write_asset(req, fake)
    assert result.state is WriteState.RECONCILED_EXISTING
    assert result.file_id == "existing"
    assert result.readback_verified is True
    assert [c[0] for c in fake.calls] == ["find", "fetch"]
    assert all(c[0] != "create" for c in fake.calls)


def test_timeout_after_success_reconciles_then_reads_back():
    fake = FakeDrive()
    fake.raise_after_create = True
    result = write_asset(request(dry_run=False), fake)
    assert result.state is WriteState.RECONCILED_EXISTING
    assert result.readback_verified is True
    assert [c[0] for c in fake.calls].count("create") == 1
    assert [c[0] for c in fake.calls][-2:] == ["find", "fetch"]


def test_conflicting_existing_identity_fails_closed():
    fake = FakeDrive()
    req = request(dry_run=False)
    key = operation_key_for(req)
    fake.files["one"] = DriveFileEvidence("one", req.parent_folder_id, req.mime_type, req.content_sha256, key)
    fake.files["two"] = DriveFileEvidence("two", req.parent_folder_id, req.mime_type, req.content_sha256, key)
    result = write_asset(req, fake)
    assert result.state is WriteState.PRECHECK_FAILED
    assert result.reason_codes == ("drive-conflicting-existing-identity",)


def test_authority_flags_are_always_false():
    result = write_asset(request())
    assert not result.approval_authorized
    assert not result.classroom_readiness_authorized
    assert not result.publication_authorized
    assert not result.production_authorized
