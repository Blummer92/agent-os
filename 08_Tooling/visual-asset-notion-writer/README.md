# Visual Asset Notion Writer

Bounded, offline-first repository contract for Issue #959.

The package writes only caller-supplied **working metadata** for one Visual Asset
Library record after upstream routing is teacher-confirmed and the Drive writer
has returned verified identity. It does not inspect images, classify assets,
invent metadata, mint Asset IDs, migrate Notion schema, or grant approval,
readiness, rights, privacy, publication, or production authority.

## Boundary

- Separate from `src/visual_asset_sync/notion_adapter.py`; that adapter remains read-only.
- No Notion SDK and no credentials.
- `dry_run=True` by default and makes zero client calls.
- Non-dry execution requires an injected `NotionClient` supplied by a separately authorized runtime.
- Stable `asset_id` plus exact verified `drive_file_id` are reconciliation anchors.
- Schema is fetched before mutation and every bound property name/type must match exactly.
- Only `ALLOWED_WORKING_FIELDS` may be written; sensitive/governed property names fail closed.
- A create with an ambiguous transient outcome reconciles before any further create attempt.
- Successful create/update/reconciliation requires exact readback of identity and intended values.
- Rate-limit and transient retries are bounded; returned errors are sanitized reason codes.

## Working metadata allowlist

The writer can carry supplied values for Asset ID/title/type, alt text,
instructional purpose, unit/concept references, material type, keywords, style
family, reuse notes/status, accessibility notes, source/import notes, AI metadata
status, import version, Drive file ID/link, and review-needed state.

Support for a logical field is not approval to mutate any live Notion property.
The caller must supply an exact binding to an existing property, and the live
schema preflight must confirm its name and type. Schema migration is not supported.

## Example

```python
request = NotionAssetWriteRequest(
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
result = write_asset(request)  # DRY_RUN; zero Notion calls
```

Live Notion adapter implementation, credentials, live pilots, and production
activation are outside #959's offline repository implementation.
