# DMSC Function Connection Map

## Boundary

This map is a navigation aid only. It is not write authorization.

Agents must verify live repository state in `Blummer92/dmsc_apps_script_bundle` on `main` before implementation. Cached function relationships in this map may drift when files move, functions are renamed, clasp deployments change, or nested app services are reorganized.

This map does not authorize:

- DMSC production writes
- Google Sheets governed-field edits
- Google Drive file edits or sharing changes
- Notion writes
- source approval changes
- classroom readiness changes
- production writer creation

## DMSC Dashboard Read Flow

Likely read flow:

```text
Code.gs
  -> getDmscDashboardRows()
      -> enrichRegistryRows_()
      -> deriveDashboardFields_()
      -> list records for DashboardJs.html

Code.gs
  -> getDmscDashboardRecord()
      -> enrichRegistryRows_()
      -> deriveDashboardFields_()
      -> detail record for DashboardJs.html

DashboardJs.html
  -> calls backend read functions
  -> renders queues, selected assets, and detail panels
```

Use this flow to orient, not to implement blindly. Before changing dashboard read behavior, inspect live `Code.gs`, `DashboardJs.html`, and `DMSC_BackendSmokeSuite.gs` on `main`.

## Source Approval Flow

Likely guarded source approval flow:

```text
Dashboard selected asset or file id
  -> getDmscSourceApprovalPreview()
      -> read current source approval state
      -> return blockers, warnings, and proposed changes

Batch or queue request
  -> getDmscSourceApprovalPreviewBatch()
      -> collect per-asset previews
      -> summarize ready/error states

Batch staging request
  -> stageDmscSourceApprovalBatch()
      -> produce read-only staging packet
      -> require evidence placeholders

Explicit approved payload with evidence
  -> approveDmscSourceForAsset()
      -> update allowed DM Source Library Pilot fields only
      -> appendDmscSourceApprovalAudit_()

DMSC_BackendSmokeSuite.gs
  -> validates preview, staging, round-trip restore, and audit boundaries
```

Source approval requires explicit human approval and approval evidence. Do not promote assets to production-ready, source-cleared, classroom-ready, or reusable without explicit evidence and authorization.

## Read-Only Notion Packet Flow

Likely read-only packet flow:

```text
Dashboard/source rows or getDmscDashboardRows()
  -> buildDmscNotionLibrarySyncPacket()
      -> visualAssetLibrary packet items
      -> iconSystem packet items
      -> promptLibrary packet items
      -> summary counts and skipped records
```

`DMSC_NotionSyncPacket.gs` is treated as a read-only routing packet unless a future governed change promotes it into a write adapter.

Do not treat packet generation as Notion write permission. Any future Notion writer must be separately authorized and must verify target schemas, duplicate behavior, write guards, and source-of-truth boundaries.

## Existing Visual Asset Library Sync Flow

Likely existing Visual Asset Library sync/service flow in the nested app:

```text
NotionDryRun.gs
  -> dry-run routing and write guard checks

NotionSyncService.gs
  -> buildNotionPropertyPlan()
  -> prepare schema-aware sync/update plans

VisualAssetLibraryValidationService.gs
  -> validate Visual Asset Library payloads and required fields

VisualAssetLibraryWriteService.gs
  -> execute guarded property writes when explicitly authorized

VisualAssetLibraryProductionSyncService.gs
  -> findNotionPagesByFileId()
  -> upsertVisualAssetPage()
  -> duplicate page detection
  -> create/update behavior
  -> post-write verification

VisualAssetLibraryPromptMetadataService.gs
  -> prompt-source selection and prompt metadata preparation

PropertyAliasService.gs
  -> field/property alias resolution
```

High-value anchors:

- `validateAndWriteVisualAssetLibraryBatch`
- `buildNotionPropertyPlan`
- `findNotionPagesByFileId`
- `upsertVisualAssetPage`
- `PropertyAliasService`

Future Visual Asset Library sync work should adapt or reuse the existing Visual Asset Library services before creating new writer logic.

## Preferred Future Implementation Route

- For Visual Asset Library sync, adapt or reuse existing Visual Asset Library services first.
- For Prompt Library and Icon System sync, first verify whether production sync services already exist.
- If no existing Prompt Library or Icon System services exist, create dry-run planners before any writer.
- Do not create production writers until explicit write authorization exists.
- Keep `DMSC_NotionSyncPacket.gs` read-only unless a future governed change promotes it into a write adapter.
- Treat any cross-system sync as implementation work requiring live repo verification, schema verification, and test evidence.

## Unknowns To Verify In Live Repo

Before implementation, verify:

- exact call relationships between functions
- whether functions are globally available in the same Apps Script deployment
- whether nested app services are included in the deployed clasp project
- whether Prompt Library and Icon System have existing production sync services
- current smoke suite status
- whether current `.claspignore` excludes nested services from the root deployment
- whether Visual Asset Library services expect a different input record shape than `DMSC_NotionSyncPacket.gs` emits
- whether Notion database schemas still match cached registry assumptions

## Drift Handling

If this map conflicts with the live DMSC repository:

1. Stop before writing.
2. Inspect the live DMSC repo on `main`.
3. Identify the conflicting file, function, or deployment boundary.
4. Report the drift.
5. Recommend a registry update or implementation handoff.

Do not use this map to override live source-of-truth state.
