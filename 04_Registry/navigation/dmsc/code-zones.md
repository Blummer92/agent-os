# DMSC Code Zones

## Root Apps Script Dashboard

Inspect these files for current DMSC dashboard behavior:

- `Code.gs`
- `Dashboard.html`
- `DashboardCss.html`
- `DashboardJs.html`
- `appsscript.json`
- `DMSC_BackendSmokeSuite.gs`
- `DMSC_BackendTest.gs`
- `DMSC_SourceApproval.gs`
- `DMSC_NotionSyncPacket.gs`

Responsibilities commonly found here:

- dashboard bootstrap
- dashboard rows and detail lookup
- registry enrichment
- safe review-routing writes
- source approval preview and staging
- read-only Notion library sync packet generation
- backend smoke tests

## Existing Drive Metadata Dashboard App

Inspect this nested app before adding DMSC sync or dashboard logic:

- `drive-metadata-dashboard/`
- `drive-metadata-dashboard/src/`

This app contains existing read-only dashboard, governance, Notion sync, Visual
Asset Library validation, and write services.

## Existing Notion Sync Services

Before adding Notion sync, upsert, create, update, duplicate-page detection, or
validation logic, inspect:

- `drive-metadata-dashboard/src/NotionDryRun.gs`
- `drive-metadata-dashboard/src/NotionSyncService.gs`
- `drive-metadata-dashboard/src/VisualAssetLibraryValidationService.gs`
- `drive-metadata-dashboard/src/VisualAssetLibraryWriteService.gs`
- `drive-metadata-dashboard/src/VisualAssetLibraryProductionSyncService.gs`
- `drive-metadata-dashboard/src/VisualAssetLibraryPromptMetadataService.gs`
- `drive-metadata-dashboard/src/VisualAssetLibraryDryRunProofService.gs`
- `drive-metadata-dashboard/src/PropertyAliasService.gs`

Known existing capabilities include guarded dry-run/write modes, script-property
approvals, alias resolution, prompt metadata extraction, duplicate detection by
`file_id`, create/update upsert behavior, and post-write verification.

## Source Approval Files

Inspect before changing source approval behavior:

- `DMSC_SourceApproval.gs`
- `DMSC_BackendSmokeSuite.gs`
- `drive-metadata-dashboard/src/GovernanceService.gs`
- `VAM_SourceApprovedAudit.js`
- `VAM_SourceApprovedAuditExport.js`
- `VAM_SourceApprovedAuditSmokeTest.js`
- `VAM_SourceApprovedAuditTests.js`

Source approval behavior must remain guarded. Do not promote assets to
production-ready, source-cleared, classroom-ready, or reusable without explicit
human approval and evidence.

## Search / Metadata Support Apps

Nested apps may contain related utilities but should not be assumed to be the
active DMSC dashboard path:

- `apps-script-builder-dashboard/`
- `drive-metadata-dashboard/`
- `search-feature-app/`

## Local-Only / Private Files

Do not commit local execution bindings or temporary scratch artifacts unless
explicitly approved:

- `.clasp.json`
- local pasted text files
- temporary logs
- scratch files

The VAM source-approved audit files may exist as local scratch or ignored files.
Verify live repo and `.claspignore` before changing them.
