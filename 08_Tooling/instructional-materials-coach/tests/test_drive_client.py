from unittest.mock import MagicMock

import pytest

from instructional_materials_coach.drive_client import duplicate_template, get_file_link


def test_duplicate_template_requires_target_folder():
    with pytest.raises(ValueError, match="target_folder_id is required"):
        duplicate_template(MagicMock(), "template-id", "", "New file")


def test_duplicate_template_never_writes_to_template_id():
    service = MagicMock()
    service.files.return_value.copy.return_value.execute.return_value = {
        "id": "new-file-id",
        "webViewLink": "https://example/new-file-id",
    }

    new_id = duplicate_template(service, "template-id", "folder-id", "New file")

    assert new_id == "new-file-id"
    service.files.return_value.copy.assert_called_once_with(
        fileId="template-id",
        body={"name": "New file", "parents": ["folder-id"]},
        fields="id, webViewLink",
    )


def test_get_file_link():
    service = MagicMock()
    service.files.return_value.get.return_value.execute.return_value = {"webViewLink": "https://example/doc"}
    assert get_file_link(service, "file-id") == "https://example/doc"
    service.files.return_value.get.assert_called_once_with(fileId="file-id", fields="webViewLink")


# --- #3256 -----------------------------------------------------------------

from instructional_materials_coach.drive_client import (
    DriveLookupError,
    classify_drive_error,
    describe_drive_file_outcome,
    get_file_metadata,
)


def test_get_file_metadata_requests_hash_and_revision_fields():
    service = MagicMock()
    service.files.return_value.get.return_value.execute.return_value = {"id": "f1"}
    get_file_metadata(service, "f1")
    _, kwargs = service.files.return_value.get.call_args
    for field in ("md5Checksum", "sha256Checksum", "headRevisionId"):
        assert field in kwargs["fields"]


def _http_error(status):
    class FakeResp:
        def __init__(self, status):
            self.status = status
            self.reason = "x"

    class FakeHttpError(Exception):
        def __init__(self):
            self.resp = FakeResp(status)
            super().__init__(f"HTTP {status}")

    return FakeHttpError()


def test_classify_drive_error_distinguishes_not_found_and_no_access():
    assert classify_drive_error("f1", _http_error(404)).outcome == "not-found"
    assert classify_drive_error("f1", _http_error(403)).outcome == "no-access"
    assert classify_drive_error("f1", _http_error(500)).outcome == "lookup-failed"
    assert classify_drive_error("f1", RuntimeError("boom")).outcome == "lookup-failed"


def test_classify_drive_error_preserves_drive_outcome_attribute():
    err = DriveLookupError("f1", "not-found", "gone")
    assert classify_drive_error("f1", err).outcome == "not-found"


def test_describe_drive_file_outcome_envelope():
    service = MagicMock()
    service.files.return_value.get.return_value.execute.return_value = {"id": "f1", "sha256Checksum": "a" * 64}
    result = describe_drive_file_outcome(service, "f1")
    assert result["outcome"] == "ok"
    assert result["metadata"]["sha256Checksum"] == "a" * 64

    service.files.return_value.get.return_value.execute.side_effect = _http_error(404)
    result = describe_drive_file_outcome(service, "gone")
    assert result["outcome"] == "not-found"
    assert result["metadata"] is None

    service.files.return_value.get.return_value.execute.side_effect = _http_error(403)
    assert describe_drive_file_outcome(service, "secret")["outcome"] == "no-access"
