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
