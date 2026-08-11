from dataclasses import replace

from visual_asset_notion_writer import (
    IconSystemWriteRequest,
    NotionAssetWriteRequest,
    NotionPageEvidence,
    NotionPropertySpec,
    PropertyBinding,
    WriteState,
    icon_operation_key_for,
    operation_key_for,
    write_asset,
    write_icon,
)

SHA = "a" * 64
ASSET_BINDINGS = (
    PropertyBinding("asset_id", "Asset ID", "title"),
    PropertyBinding("drive_file_id", "Drive File ID", "rich_text"),
)
ICON_BINDINGS = (
    PropertyBinding("icon_name", "Icon Name", "title"),
    PropertyBinding("source_asset_link", "Source / Asset Link", "url"),
)


def asset_request(**changes):
    base = NotionAssetWriteRequest(
        data_source_id="visual-assets",
        asset_id="asset-1",
        routing_reference="route-1",
        routing_state="CONFIRMED",
        teacher_confirmed=True,
        drive_operation_key="drive-op-1",
        drive_file_id="file-1",
        drive_parent_id="folder-1",
        drive_mime_type="image/png",
        drive_content_sha256=SHA,
        drive_state="VERIFIED",
        drive_readback_verified=True,
        bindings=ASSET_BINDINGS,
    )
    return replace(base, **changes)


def icon_request(**changes):
    base = IconSystemWriteRequest(
        data_source_id="icons",
        asset_id="asset-1",
        icon_name="Pause",
        source_asset_link="https://drive.google.com/file/d/file-1/view",
        routing_reference="route-1",
        routing_state="CONFIRMED",
        teacher_confirmed=True,
        reusable_icon_confirmed=True,
        drive_operation_key="drive-op-1",
        drive_file_id="file-1",
        drive_parent_id="folder-1",
        drive_mime_type="image/png",
        drive_content_sha256=SHA,
        drive_state="VERIFIED",
        drive_readback_verified=True,
        bindings=ICON_BINDINGS,
    )
    return replace(base, **changes)


class CreateFailureClient:
    def fetch_schema(self, data_source_id):
        return tuple(NotionPropertySpec(item.property_name, item.property_type) for item in ASSET_BINDINGS)

    def find_exact(self, **kwargs):
        return ()

    def create_page(self, **kwargs):
        raise RuntimeError("provider details must remain sanitized")

    def update_page(self, **kwargs):
        raise AssertionError("unexpected update")

    def fetch_page(self, page_id):
        raise AssertionError("unexpected readback")


class MalformedCandidateClient(CreateFailureClient):
    def find_exact(self, **kwargs):
        return (NotionPageEvidence("page-1", ["malformed"]),)

    def create_page(self, **kwargs):
        raise AssertionError("malformed evidence must block before create")


class MalformedReadbackClient(CreateFailureClient):
    def create_page(self, **kwargs):
        return "page-1"

    def fetch_page(self, page_id):
        return NotionPageEvidence("page-1", ["malformed"])


def test_operation_keys_are_delimiter_safe():
    first = asset_request(asset_id="a\nb", drive_file_id="c")
    second = asset_request(asset_id="a", drive_file_id="b\nc")
    assert operation_key_for(first) != operation_key_for(second)

    # These adjacent hashed fields collide under newline-joined serialization.
    first_icon = icon_request(drive_operation_key="a\nhttps://example.com/b", source_asset_link="https://example.com/c")
    second_icon = icon_request(drive_operation_key="a", source_asset_link="https://example.com/b\nhttps://example.com/c")
    assert icon_operation_key_for(first_icon) != icon_operation_key_for(second_icon)


def test_unknown_post_create_failure_is_conservatively_marked_external():
    result = write_asset(asset_request(dry_run=False), CreateFailureClient())
    assert result.state is WriteState.FAILED
    assert result.reason_codes == ("notion-create-failed",)
    assert result.external_write_performed is True


def test_malformed_candidate_evidence_returns_sanitized_failure():
    result = write_asset(asset_request(dry_run=False), MalformedCandidateClient())
    assert result.state is WriteState.FAILED
    assert result.reason_codes == ("notion-reconcile-read-failed",)
    assert result.external_write_performed is False


def test_malformed_create_readback_returns_mismatch_not_exception():
    result = write_asset(asset_request(dry_run=False), MalformedReadbackClient())
    assert result.state is WriteState.FAILED
    assert result.reason_codes == ("notion-create-readback-mismatch",)
    assert result.external_write_performed is True


def test_icon_source_link_rejects_unsafe_or_non_web_schemes():
    for value in ("javascript:alert(1)", "file:///tmp/icon.png", "mailto:test@example.com"):
        result = write_icon(icon_request(source_asset_link=value))
        assert result.state is WriteState.PRECHECK_FAILED
        assert result.reason_codes == ("notion-icon-source-asset-link-invalid",)
