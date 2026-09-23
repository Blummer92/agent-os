# DMSC Function Flow Map

## Boundary

This map is a navigation aid only. It is not write authorization.

Agents must verify live repository state in `Blummer92/dmsc_apps_script_bundle`
on `main` before implementation.

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

Before changing dashboard reads, inspect live `Code.gs`, `DashboardJs.html`,
and `DMSC_BackendSmokeSuite.gs` on `main`.

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

Source approval requires explicit human approval and approval evidence.

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

`DMSC_NotionSyncPacket.gs` remains read-only unless future governance promotes
it into a write adapter.

## Existing Visual Asset Library Sync Flow

Likely existing nested-app service flow:

```text
NotionDryRun.gs -> dry-run routing and write guard checks
NotionSyncService.gs -> buildNotionPropertyPlan()
VisualAssetLibraryValidationService.gs -> validate payloads and fields
VisualAssetLibraryWriteService.gs -> guarded property writes
VisualAssetLibraryProductionSyncService.gs -> upsert and verify pages
VisualAssetLibraryPromptMetadataService.gs -> prompt metadata preparation
PropertyAliasService.gs -> field/property alias resolution
```

High-value anchors: `validateAndWriteVisualAssetLibraryBatch`,
`buildNotionPropertyPlan`, `findNotionPagesByFileId`, `upsertVisualAssetPage`,
and `PropertyAliasService`.
