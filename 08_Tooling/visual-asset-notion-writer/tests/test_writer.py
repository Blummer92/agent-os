from dataclasses import replace

from visual_asset_notion_writer import (
    NotionAssetWriteRequest,
    NotionPageEvidence,
    NotionPropertySpec,
    NotionRateLimitError,
    NotionTransientError,
    PropertyBinding,
    WorkingMetadata,
    WriteState,
    write_asset,
)

SHA = "a" * 64

BINDINGS = (
    PropertyBinding("asset_id", "Asset ID", "title"),
    PropertyBinding("drive_file_id", "Drive File ID", "rich_text"),
    PropertyBinding("asset_title", "Asset title", "rich_text"),
    PropertyBinding("asset_type", "Asset type", "select"),
    PropertyBinding("alt_text", "Alt text", "rich_text"),
    PropertyBinding("keywords", "Keywords", "multi_select"),
    PropertyBinding("reuse_status", "Reuse status", "select"),
    PropertyBinding("accessibility_notes", "Accessibility notes", "rich_text"),
    PropertyBinding("ai_metadata_status", "AI Metadata Status", "status"),
    PropertyBinding("import_version", "Import version", "rich_text"),
)

META = (
    WorkingMetadata("asset_title", "Leading lines campus example"),
    WorkingMetadata("asset_type", "Photo"),
    WorkingMetadata("alt_text", "A walkway creates diagonal leading lines toward a building."),
    WorkingMetadata("keywords", ("Photography", "Composition")),
    WorkingMetadata("reuse_status", "Draft"),
    WorkingMetadata("accessibility_notes", "Describe the diagonal walkway before discussing composition."),
    WorkingMetadata("ai_metadata_status", "Done"),
    WorkingMetadata("import_version", "Drive import - 2026-08-10 - v1"),
)


def request(**changes):
    base = NotionAssetWriteRequest(
        data_source_id="visual-assets",
        asset_id="AUR-1001",
        routing_reference="route-1",
        routing_state="CONFIRMED",
        teacher_confirmed=True,
        drive_operation_key="drive-op-1",
        drive_file_id="file-123",
        drive_parent_id="folder-456",
        drive_mime_type="image/png",
        drive_content_sha256=SHA,
        drive_state="VERIFIED",
        drive_readback_verified=True,
        bindings=BINDINGS,
        working_metadata=META,
    )
    return replace(base, **changes)


class FakeNotion:
    def __init__(self):
        self.calls = []
        self.pages = {}
        self.schema = tuple(NotionPropertySpec(b.property_name, b.property_type) for b in BINDINGS)
        self.raise_after_create = False
        self.schema_rate_limits = 0

    def fetch_schema(self, data_source_id):
        self.calls.append(("schema", data_source_id))
        if self.schema_rate_limits:
            self.schema_rate_limits -= 1
            raise NotionRateLimitError(0.25)
        return self.schema

    def find_exact(self, *, data_source_id, property_name, value):
        self.calls.append(("find", property_name, value))
        return tuple(page for page in self.pages.values() if dict(page.properties).get(property_name) == value)

    def create_page(self, *, data_source_id, properties, operation_key):
        self.calls.append(("create", operation_key))
        page = NotionPageEvidence("page-1", properties)
        self.pages[page.page_id] = page
        if self.raise_after_create:
            raise NotionTransientError()
        return page.page_id

    def update_page(self, *, page_id, properties):
        self.calls.append(("update", page_id))
        self.pages[page_id] = NotionPageEvidence(page_id, properties)

    def fetch_page(self, page_id):
        self.calls.append(("fetch", page_id))
        return self.pages.get(page_id)


def intended(req):
    binding = {b.logical_field: b.property_name for b in req.bindings}
    values = [("asset_id", req.asset_id), ("drive_file_id", req.drive_file_id)]
    values += [(m.logical_field, m.value) for m in req.working_metadata]
    return tuple((binding[field], value) for field, value in values)


def test_dry_run_makes_zero_notion_calls_and_writes_nothing():
    fake = FakeNotion()
    result = write_asset(request(), fake)
    assert result.state is WriteState.DRY_RUN
    assert result.external_write_performed is False
    assert fake.calls == []


def test_unconfirmed_routing_or_unverified_drive_fails_before_client_call():
    fake = FakeNotion()
    assert write_asset(request(routing_state="RECOMMENDED"), fake).state is WriteState.PRECHECK_FAILED
    assert write_asset(request(drive_readback_verified=False), fake).state is WriteState.PRECHECK_FAILED
    assert fake.calls == []


def test_allowlist_and_governed_property_name_are_enforced():
    bad_field = request(bindings=BINDINGS + (PropertyBinding("teacher_approval", "Teacher Approval", "status"),))
    assert write_asset(bad_field).reason_codes == ("notion-field-not-allowlisted",)
    bad_name = replace(BINDINGS[2], property_name="Teacher Approval")
    bindings = (BINDINGS[0], BINDINGS[1], bad_name, *BINDINGS[3:])
    assert write_asset(request(bindings=bindings)).reason_codes == ("notion-governed-property-blocked",)


def test_schema_drift_blocks_before_mutation():
    fake = FakeNotion()
    fake.schema = tuple(spec for spec in fake.schema if spec.name != "Asset title")
    result = write_asset(request(dry_run=False), fake)
    assert result.state is WriteState.PRECHECK_FAILED
    assert result.reason_codes == ("notion-schema-property-missing",)
    assert all(call[0] not in {"create", "update"} for call in fake.calls)


def test_create_requires_exact_readback():
    fake = FakeNotion()
    result = write_asset(request(dry_run=False), fake)
    assert result.state is WriteState.CREATED
    assert result.page_id == "page-1"
    assert result.readback_verified is True
    assert result.external_write_performed is True
    assert [call[0] for call in fake.calls] == ["schema", "find", "find", "create", "fetch"]


def test_retry_reconciles_existing_without_duplicate_create():
    fake = FakeNotion()
    req = request(dry_run=False)
    fake.pages["existing"] = NotionPageEvidence("existing", intended(req))
    result = write_asset(req, fake)
    assert result.state is WriteState.RECONCILED_EXISTING
    assert result.page_id == "existing"
    assert result.readback_verified is True
    assert all(call[0] != "create" for call in fake.calls)


def test_conflicting_asset_and_drive_identity_fails_closed():
    fake = FakeNotion()
    req = request(dry_run=False)
    props = dict(intended(req))
    fake.pages["asset-page"] = NotionPageEvidence("asset-page", tuple({**props, "Drive File ID": "other-file"}.items()))
    fake.pages["drive-page"] = NotionPageEvidence("drive-page", tuple({**props, "Asset ID": "OTHER-ASSET"}.items()))
    result = write_asset(req, fake)
    assert result.state is WriteState.PRECHECK_FAILED
    assert result.reason_codes == ("notion-conflicting-existing-identity",)
    assert all(call[0] not in {"create", "update"} for call in fake.calls)


def test_existing_record_is_updated_then_verified():
    fake = FakeNotion()
    req = request(dry_run=False)
    props = dict(intended(req))
    props["Asset title"] = "Old title"
    fake.pages["existing"] = NotionPageEvidence("existing", tuple(props.items()))
    result = write_asset(req, fake)
    assert result.state is WriteState.UPDATED
    assert result.readback_verified is True
    assert [call[0] for call in fake.calls].count("update") == 1


def test_ambiguous_create_reconciles_before_any_second_create():
    fake = FakeNotion()
    fake.raise_after_create = True
    result = write_asset(request(dry_run=False), fake)
    assert result.state is WriteState.RECONCILED_EXISTING
    assert result.readback_verified is True
    assert [call[0] for call in fake.calls].count("create") == 1
    assert [call[0] for call in fake.calls][-3:] == ["find", "find", "fetch"]


def test_rate_limit_retry_is_bounded_and_uses_retry_after():
    fake = FakeNotion()
    fake.schema_rate_limits = 1
    sleeps = []
    result = write_asset(request(dry_run=False), fake, sleep=sleeps.append)
    assert result.state is WriteState.CREATED
    assert sleeps == [0.25]


def test_retry_exhaustion_is_sanitized():
    fake = FakeNotion()
    fake.schema_rate_limits = 3
    result = write_asset(request(dry_run=False, maximum_retries=1), fake, sleep=lambda _: None)
    assert result.state is WriteState.FAILED
    assert result.reason_codes == ("notion-schema-retry-exhausted",)


def test_authority_flags_are_always_false():
    result = write_asset(request())
    assert not result.approval_authorized
    assert not result.classroom_readiness_authorized
    assert not result.rights_authorized
    assert not result.privacy_authorized
    assert not result.publication_authorized
    assert not result.production_authorized
