from dataclasses import replace

from visual_asset_notion_writer import (
    IconSystemWriteRequest,
    NotionAssetSyncRequest,
    NotionAssetWriteRequest,
    NotionPageEvidence,
    NotionPropertySpec,
    NotionRateLimitError,
    NotionTransientError,
    PropertyBinding,
    SyncState,
    WorkingMetadata,
    WriteState,
    sync_asset,
    write_asset,
    write_icon,
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

ICON_BINDINGS = (
    PropertyBinding("icon_name", "Icon Name", "title"),
    PropertyBinding("source_asset_link", "Source / Asset Link", "url"),
    PropertyBinding("meaning", "Meaning", "rich_text"),
    PropertyBinding("icon_category", "Icon Category", "select"),
    PropertyBinding("reusable_across_units", "Reusable Across Units?", "checkbox"),
    PropertyBinding("reuse_boundary", "Reuse Boundary", "rich_text"),
    PropertyBinding("reuse_notes", "Reuse Notes", "rich_text"),
    PropertyBinding("teacher_use_note", "Teacher-Use Note", "rich_text"),
    PropertyBinding("vocabulary_concept_supported", "Vocabulary / Concept Supported", "rich_text"),
    PropertyBinding("do_not_confuse_with", "Do Not Confuse With", "rich_text"),
)

ICON_META = (
    WorkingMetadata("meaning", "Pause, look, compose, or make an intentional photography choice."),
    WorkingMetadata("icon_category", "Plan"),
    WorkingMetadata("reusable_across_units", True),
    WorkingMetadata("reuse_boundary", "Reusable for photography and visual-composition instruction."),
    WorkingMetadata("reuse_notes", "Drive import 2026-08-10; working metadata only."),
    WorkingMetadata("teacher_use_note", "Use before students press the shutter."),
    WorkingMetadata("vocabulary_concept_supported", "pause; intention; photography; composition"),
    WorkingMetadata("do_not_confuse_with", "Look/observe icon; this cue means pause before acting."),
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


def icon_request(**changes):
    base = IconSystemWriteRequest(
        data_source_id="icons",
        asset_id="AUR-1001",
        icon_name="Pause before shooting — IMG_2523.PNG",
        source_asset_link="https://drive.google.com/file/d/file-123/view",
        routing_reference="route-1",
        routing_state="CONFIRMED",
        teacher_confirmed=True,
        reusable_icon_confirmed=True,
        drive_operation_key="drive-op-1",
        drive_file_id="file-123",
        drive_parent_id="folder-456",
        drive_mime_type="image/png",
        drive_content_sha256=SHA,
        drive_state="VERIFIED",
        drive_readback_verified=True,
        bindings=ICON_BINDINGS,
        working_metadata=ICON_META,
    )
    return replace(base, **changes)


class FakeNotion:
    def __init__(self):
        self.calls = []
        self.pages = {"visual-assets": {}, "icons": {}}
        self.page_sources = {}
        self.schemas = {
            "visual-assets": tuple(NotionPropertySpec(b.property_name, b.property_type) for b in BINDINGS),
            "icons": tuple(NotionPropertySpec(b.property_name, b.property_type) for b in ICON_BINDINGS),
        }
        self.raise_after_create = set()
        self.fail_create = set()
        self.schema_rate_limits = {}
        self._counter = 0

    def fetch_schema(self, data_source_id):
        self.calls.append(("schema", data_source_id))
        if self.schema_rate_limits.get(data_source_id, 0):
            self.schema_rate_limits[data_source_id] -= 1
            raise NotionRateLimitError(0.25)
        return self.schemas[data_source_id]

    def find_exact(self, *, data_source_id, property_name, value):
        self.calls.append(("find", data_source_id, property_name, value))
        return tuple(page for page in self.pages[data_source_id].values() if dict(page.properties).get(property_name) == value)

    def create_page(self, *, data_source_id, properties, operation_key):
        self.calls.append(("create", data_source_id, operation_key))
        if data_source_id in self.fail_create:
            raise RuntimeError("provider detail must not escape")
        self._counter += 1
        page_id = f"{data_source_id}-page-{self._counter}"
        page = NotionPageEvidence(page_id, properties)
        self.pages[data_source_id][page_id] = page
        self.page_sources[page_id] = data_source_id
        if data_source_id in self.raise_after_create:
            raise NotionTransientError()
        return page_id

    def update_page(self, *, page_id, properties):
        data_source_id = self.page_sources[page_id]
        self.calls.append(("update", data_source_id, page_id))
        self.pages[data_source_id][page_id] = NotionPageEvidence(page_id, properties)

    def fetch_page(self, page_id):
        data_source_id = self.page_sources.get(page_id)
        self.calls.append(("fetch", data_source_id, page_id))
        if data_source_id is None:
            return None
        return self.pages[data_source_id].get(page_id)

    def seed(self, data_source_id, page_id, properties):
        self.pages[data_source_id][page_id] = NotionPageEvidence(page_id, properties)
        self.page_sources[page_id] = data_source_id


def intended(req):
    binding = {b.logical_field: b.property_name for b in req.bindings}
    values = [("asset_id", req.asset_id), ("drive_file_id", req.drive_file_id)]
    values += [(m.logical_field, m.value) for m in req.working_metadata]
    return tuple((binding[field], value) for field, value in values)


def icon_intended(req):
    binding = {b.logical_field: b.property_name for b in req.bindings}
    values = [("icon_name", req.icon_name), ("source_asset_link", req.source_asset_link)]
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
    fake.schemas["visual-assets"] = tuple(spec for spec in fake.schemas["visual-assets"] if spec.name != "Asset title")
    result = write_asset(request(dry_run=False), fake)
    assert result.state is WriteState.PRECHECK_FAILED
    assert result.reason_codes == ("notion-schema-property-missing",)
    assert all(call[0] not in {"create", "update"} for call in fake.calls)


def test_create_requires_exact_readback():
    fake = FakeNotion()
    result = write_asset(request(dry_run=False), fake)
    assert result.state is WriteState.CREATED
    assert result.readback_verified is True
    assert result.external_write_performed is True
    assert [call[0] for call in fake.calls] == ["schema", "find", "find", "create", "fetch"]


def test_retry_reconciles_existing_without_duplicate_create():
    fake = FakeNotion()
    req = request(dry_run=False)
    fake.seed("visual-assets", "existing", intended(req))
    result = write_asset(req, fake)
    assert result.state is WriteState.RECONCILED_EXISTING
    assert result.page_id == "existing"
    assert result.readback_verified is True
    assert all(call[0] != "create" for call in fake.calls)


def test_conflicting_asset_and_drive_identity_fails_closed():
    fake = FakeNotion()
    req = request(dry_run=False)
    props = dict(intended(req))
    fake.seed("visual-assets", "asset-page", tuple({**props, "Drive File ID": "other-file"}.items()))
    fake.seed("visual-assets", "drive-page", tuple({**props, "Asset ID": "OTHER-ASSET"}.items()))
    result = write_asset(req, fake)
    assert result.state is WriteState.PRECHECK_FAILED
    assert result.reason_codes == ("notion-conflicting-existing-identity",)
    assert all(call[0] not in {"create", "update"} for call in fake.calls)


def test_existing_record_is_updated_then_verified():
    fake = FakeNotion()
    req = request(dry_run=False)
    props = dict(intended(req))
    props["Asset title"] = "Old title"
    fake.seed("visual-assets", "existing", tuple(props.items()))
    result = write_asset(req, fake)
    assert result.state is WriteState.UPDATED
    assert result.readback_verified is True
    assert [call[0] for call in fake.calls].count("update") == 1


def test_ambiguous_create_reconciles_before_any_second_create():
    fake = FakeNotion()
    fake.raise_after_create.add("visual-assets")
    result = write_asset(request(dry_run=False), fake)
    assert result.state is WriteState.RECONCILED_EXISTING
    assert result.readback_verified is True
    assert [call[0] for call in fake.calls].count("create") == 1
    assert [call[0] for call in fake.calls][-3:] == ["find", "find", "fetch"]


def test_rate_limit_retry_is_bounded_and_uses_retry_after():
    fake = FakeNotion()
    fake.schema_rate_limits["visual-assets"] = 1
    sleeps = []
    result = write_asset(request(dry_run=False), fake, sleep=sleeps.append)
    assert result.state is WriteState.CREATED
    assert sleeps == [0.25]


def test_retry_exhaustion_is_sanitized():
    fake = FakeNotion()
    fake.schema_rate_limits["visual-assets"] = 3
    result = write_asset(request(dry_run=False, maximum_retries=1), fake, sleep=lambda _: None)
    assert result.state is WriteState.FAILED
    assert result.reason_codes == ("notion-schema-retry-exhausted",)


def test_asset_authority_flags_are_always_false():
    result = write_asset(request())
    assert not result.approval_authorized
    assert not result.classroom_readiness_authorized
    assert not result.rights_authorized
    assert not result.privacy_authorized
    assert not result.publication_authorized
    assert not result.production_authorized


def test_icon_dry_run_is_zero_call_and_does_not_require_visual_asset_only_fields():
    fake = FakeNotion()
    result = write_icon(icon_request(), fake)
    assert result.state is WriteState.DRY_RUN
    assert "icon_name" in result.written_fields
    assert "source_asset_link" in result.written_fields
    assert fake.calls == []


def test_icon_allowlist_blocks_governed_fields():
    bad = icon_request(bindings=ICON_BINDINGS + (PropertyBinding("source_authority", "Source Authority", "select"),))
    assert write_icon(bad).reason_codes == ("notion-field-not-allowlisted",)
    renamed = replace(ICON_BINDINGS[2], property_name="Production Route")
    bindings = (ICON_BINDINGS[0], ICON_BINDINGS[1], renamed, *ICON_BINDINGS[3:])
    assert write_icon(icon_request(bindings=bindings)).reason_codes == ("notion-governed-property-blocked",)


def test_icon_create_and_readback_use_its_distinct_schema():
    fake = FakeNotion()
    result = write_icon(icon_request(dry_run=False), fake)
    assert result.state is WriteState.CREATED
    assert result.readback_verified is True
    assert all(call[1] == "icons" for call in fake.calls if call[0] in {"schema", "find", "create"})


def test_icon_duplicate_identity_conflict_fails_closed():
    fake = FakeNotion()
    req = icon_request(dry_run=False)
    props = dict(icon_intended(req))
    fake.seed("icons", "name-page", tuple({**props, "Source / Asset Link": "https://drive.google.com/file/d/other/view"}.items()))
    fake.seed("icons", "source-page", tuple({**props, "Icon Name": "Different icon"}.items()))
    result = write_icon(req, fake)
    assert result.state is WriteState.PRECHECK_FAILED
    assert result.reason_codes == ("notion-icon-conflicting-existing-identity",)
    assert all(call[0] not in {"create", "update"} for call in fake.calls)


def test_non_icon_sync_writes_visual_asset_only():
    fake = FakeNotion()
    result = sync_asset(NotionAssetSyncRequest(visual_asset=request(dry_run=False)), fake)
    assert result.state is SyncState.VERIFIED
    assert result.fully_synchronized is True
    assert result.icon_system_result is None
    assert [call[1] for call in fake.calls if call[0] == "create"] == ["visual-assets"]


def test_reusable_icon_sync_preflights_both_schemas_before_mutation_and_writes_both():
    fake = FakeNotion()
    sync = NotionAssetSyncRequest(request(dry_run=False), True, icon_request(dry_run=False))
    result = sync_asset(sync, fake)
    assert result.state is SyncState.VERIFIED
    assert result.fully_synchronized is True
    assert [call[1] for call in fake.calls if call[0] == "create"] == ["visual-assets", "icons"]
    first_create = next(i for i, call in enumerate(fake.calls) if call[0] == "create")
    preflight_sources = [call[1] for call in fake.calls[:first_create] if call[0] == "schema"]
    assert "visual-assets" in preflight_sources and "icons" in preflight_sources


def test_icon_schema_drift_blocks_before_visual_asset_mutation():
    fake = FakeNotion()
    fake.schemas["icons"] = tuple(spec for spec in fake.schemas["icons"] if spec.name != "Meaning")
    sync = NotionAssetSyncRequest(request(dry_run=False), True, icon_request(dry_run=False))
    result = sync_asset(sync, fake)
    assert result.state is SyncState.PRECHECK_FAILED
    assert result.icon_system_result.reason_codes == ("notion-icon-schema-property-missing",)
    assert all(call[0] not in {"create", "update"} for call in fake.calls)


def test_reusable_icon_requires_icon_request_and_non_icon_rejects_one():
    visual = request()
    missing = sync_asset(NotionAssetSyncRequest(visual, reusable_icon_confirmed=True))
    assert missing.state is SyncState.PRECHECK_FAILED
    assert missing.reason_codes == ("notion-icon-request-required",)
    extra = sync_asset(NotionAssetSyncRequest(visual, reusable_icon_confirmed=False, icon_system=icon_request()))
    assert extra.state is SyncState.PRECHECK_FAILED
    assert extra.reason_codes == ("notion-icon-request-not-authorized",)


def test_cross_destination_drive_identity_mismatch_fails_before_calls():
    fake = FakeNotion()
    sync = NotionAssetSyncRequest(request(dry_run=False), True, icon_request(dry_run=False, drive_file_id="other-file"))
    result = sync_asset(sync, fake)
    assert result.state is SyncState.PRECHECK_FAILED
    assert result.reason_codes == ("notion-cross-destination-evidence-mismatch",)
    assert fake.calls == []


def test_partial_icon_failure_is_explicit_and_retry_reconciles_visual_asset():
    fake = FakeNotion()
    sync = NotionAssetSyncRequest(request(dry_run=False), True, icon_request(dry_run=False))
    fake.fail_create.add("icons")
    first = sync_asset(sync, fake)
    assert first.state is SyncState.PARTIAL_REPAIR_REQUIRED
    assert first.fully_synchronized is False
    assert len(fake.pages["visual-assets"]) == 1
    assert len(fake.pages["icons"]) == 0
    assert sum(1 for call in fake.calls if call[0] == "create" and call[1] == "visual-assets") == 1

    fake.fail_create.clear()
    second = sync_asset(sync, fake)
    assert second.state is SyncState.VERIFIED
    assert second.visual_asset_result.state is WriteState.RECONCILED_EXISTING
    assert second.icon_system_result.state is WriteState.CREATED
    assert sum(1 for call in fake.calls if call[0] == "create" and call[1] == "visual-assets") == 1
    assert len(fake.pages["icons"]) == 1


def test_sync_dry_run_zero_calls_for_both_destinations():
    fake = FakeNotion()
    result = sync_asset(NotionAssetSyncRequest(request(), True, icon_request()), fake)
    assert result.state is SyncState.DRY_RUN
    assert result.fully_synchronized is False
    assert fake.calls == []


def test_all_icon_and_sync_authority_flags_are_false():
    icon = write_icon(icon_request())
    sync = sync_asset(NotionAssetSyncRequest(request(), True, icon_request()))
    for result in (icon, sync):
        assert not result.approval_authorized
        assert not result.classroom_readiness_authorized
        assert not result.rights_authorized
        assert not result.privacy_authorized
        assert not result.publication_authorized
        assert not result.production_authorized
