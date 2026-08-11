# Visual Asset Notion Writer

Bounded, offline-first repository contract for Issue #959.

The package writes only caller-supplied **working metadata** after upstream
routing is teacher-confirmed and the Drive writer has returned verified identity.
Every routed visual asset can be synchronized to the Visual Asset Library. When
upstream routing/classification explicitly confirms that the asset is a reusable
icon, the same bounded operation additionally synchronizes the Icon System using
its own schema and allowlist.

It does not inspect images, decide whether an asset is an icon, invent metadata,
mint Asset IDs, migrate Notion schema, or grant approval, readiness, rights,
privacy, publication, production, source-authority, safe-use, modeling, or
unit-alignment authority.

## Boundary

- Separate from `src/visual_asset_sync/notion_adapter.py`; that adapter remains read-only.
- No Notion SDK and no credentials.
- `dry_run=True` by default and makes zero client calls.
- Non-dry execution requires an injected `NotionClient` supplied by a separately authorized runtime.
- Visual Asset Library and Icon System use independent explicit property bindings and live-schema preflight.
- A reusable-icon sync preflights **both required schemas before the first mutation**.
- Visual Asset Library reconciliation uses stable `asset_id` plus exact verified `drive_file_id`.
- Icon System reconciliation uses the exact icon name plus exact source/Drive asset link supplied by upstream; filenames alone are never treated as identity.
- A create with an ambiguous transient outcome reconciles before any further create attempt.
- Successful create and update require exact page readback of identity and intended values.
- Reconciliation of an already-matching record requires exact identity and intended-value agreement in the returned search evidence; an ambiguous create is reconciled with exact page readback.
- If the Visual Asset Library succeeds but a required Icon System write fails, the coordinator returns `PARTIAL_REPAIR_REQUIRED`; retry reconciles the completed destination before attempting the incomplete destination.
- Rate-limit and transient retries are bounded; returned errors are sanitized reason codes.

## Separate working-metadata allowlists

### Visual Asset Library

`ALLOWED_WORKING_FIELDS` supports caller-supplied working values for Asset
ID/title/type, alt text, instructional purpose, unit/concept references,
material type, keywords, style family, reuse notes/status, accessibility notes,
source/import notes, AI metadata status, import version, Drive file ID/link, and
review-needed state.

### Icon System

`ICON_SYSTEM_WORKING_FIELDS` is deliberately different and supports only:

- Icon Name
- Meaning
- Icon Category
- Source / Asset Link
- Reusable Across Units?
- Reuse Boundary
- Reuse Notes
- Teacher-Use Note
- Vocabulary / Concept Supported
- Do Not Confuse With

The Icon System path does **not** require Visual Asset Library-only fields such as
`file_id` or `AI Metadata Status`.

Support for a logical field is not approval to mutate any live Notion property.
The caller must supply an exact binding to an existing property, and live schema
preflight must confirm its name and type. Schema migration is not supported.
Governed fields such as Source Approved?, Source Authority, Production Route,
Safe-Use Permissions, review/modeling approval, and unit-alignment approval are
outside both writer allowlists.

## Examples

Visual Asset Library dry-run:

```python
asset = NotionAssetWriteRequest(
    data_source_id="...",
    asset_id="AUR-1001",
    routing_reference="route-1",
    routing_state="CONFIRMED",
    teacher_confirmed=True,
    drive_operation_key="...",
    drive_file_id="...",
    drive_parent_id="...",
    drive_mime_type="image/png",
    drive_content_sha256="a" * 64,
    drive_state="VERIFIED",
    drive_readback_verified=True,
    bindings=(
        PropertyBinding("asset_id", "Asset ID", "title"),
        PropertyBinding("drive_file_id", "Drive File ID", "rich_text"),
        PropertyBinding("alt_text", "Alt text", "rich_text"),
    ),
    working_metadata=(WorkingMetadata("alt_text", "..."),),
)
result = write_asset(asset)  # DRY_RUN; zero Notion calls
```

Conditional reusable-icon coordination:

```python
icon = IconSystemWriteRequest(
    data_source_id="...",
    asset_id=asset.asset_id,
    icon_name="Pause before shooting",
    source_asset_link="https://drive.google.com/file/d/.../view",
    routing_reference=asset.routing_reference,
    routing_state=asset.routing_state,
    teacher_confirmed=asset.teacher_confirmed,
    reusable_icon_confirmed=True,
    drive_operation_key=asset.drive_operation_key,
    drive_file_id=asset.drive_file_id,
    drive_parent_id=asset.drive_parent_id,
    drive_mime_type=asset.drive_mime_type,
    drive_content_sha256=asset.drive_content_sha256,
    drive_state=asset.drive_state,
    drive_readback_verified=asset.drive_readback_verified,
    bindings=(
        PropertyBinding("icon_name", "Icon Name", "title"),
        PropertyBinding("source_asset_link", "Source / Asset Link", "url"),
        PropertyBinding("meaning", "Meaning", "rich_text"),
    ),
    working_metadata=(WorkingMetadata("meaning", "Pause before capture."),),
)

sync = sync_asset(NotionAssetSyncRequest(asset, True, icon))
# DRY_RUN; zero Notion calls to either destination
```

## Tests

From this package directory:

```bash
PYTHONPATH=src pytest -q
```

The focused suite uses only injected in-memory fakes and covers Visual Asset
Library behavior, Icon System behavior, distinct schema drift, non-icon bypass,
dual-destination readback, partial success, and idempotent repair retry.

Live Notion adapter implementation, credentials, live pilots, schema mutation,
and production activation are outside #959's offline repository implementation.
