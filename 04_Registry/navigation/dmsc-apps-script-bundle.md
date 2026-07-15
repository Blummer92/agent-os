# DMSC Apps Script Bundle Navigation Registry Proposal

## Status

| Field | Value |
|---|---|
| Status | Proposed |
| Review owner | Integration Manager |
| GitHub write owner | GitHub Service Agent |
| Authority | Navigation aid only |
| External repo | `Blummer92/dmsc_apps_script_bundle` |
| External branch | `main` |
| Last reviewed | PR #96 during DMSC navigation registry setup |

## Purpose

Help Agent OS agents navigate `Blummer92/dmsc_apps_script_bundle` before implementing DMSC Apps Script, dashboard, source approval, or Notion sync changes.

This proposal exists because the DMSC repository contains both root Apps Script dashboard code and nested app-specific sync services. Agents must inspect existing code zones before creating new implementation paths.

## How Agents Should Use This Entry

1. Read this entry before implementing DMSC changes.
2. Identify the relevant work area: Notion sync, source approval, dashboard rows/details, audit/safe writes, or tests.
3. Inspect the listed files in the live DMSC repo on `main`.
4. Search for listed functions before adding new code.
5. Stop and report drift if the live repo differs from this entry.
6. Treat this entry as navigation only, not write authorization.

## Governance Placement

- Registry type: GitHub Path Registry / external repository navigation map
- Agent OS location: `04_Registry/navigation/`
- Owner agent: Integration Manager
- GitHub write owner: GitHub Service Agent
- Source of truth for this registry entry: Agent OS GitHub
- Source of truth for DMSC code: `Blummer92/dmsc_apps_script_bundle` on `main`
- Runtime systems remain authoritative for live records and execution state.

## Non-Authoritative Boundary

This registry entry is a lookup aid only. It does not authorize:

- DMSC production writes
- Google Sheets governed-field edits
- Google Drive file edits or sharing changes
- Notion writes
- source approval changes
- classroom readiness changes
- deletion or migration of DMSC code

Agents must verify live repository state before any implementation or write.

## Canonical External Repository

| Field | Value |
|---|---|
| Repository | `Blummer92/dmsc_apps_script_bundle` |
| Branch | `main` |
| System | DMSC Apps Script Bundle |
| Primary source of truth | GitHub repository |
| Primary execution surface | Google Apps Script / clasp |
| Human owner | Zachary Blumstein |

## Required Preflight Before DMSC Implementation

Before implementing DMSC changes, agents must inspect the relevant existing code zones first. This preflight is required because DMSC code exists in both root Apps Script files and nested app folders.

### Before Notion sync or upsert work

Inspect:

- `drive-metadata-dashboard/src/NotionDryRun.gs`
- `drive-metadata-dashboard/src/NotionSyncService.gs`
- `drive-metadata-dashboard/src/VisualAssetLibraryValidationService.gs`
- `drive-metadata-dashboard/src/VisualAssetLibraryWriteService.gs`
- `drive-metadata-dashboard/src/VisualAssetLibraryProductionSyncService.gs`
- `drive-metadata-dashboard/src/VisualAssetLibraryPromptMetadataService.gs`
- `drive-metadata-dashboard/src/PropertyAliasService.gs`

Do not create new Notion writer, upsert, duplicate-page, prompt-mapping, or Visual Asset Library sync logic before this review is complete.

### Before source approval work

Inspect:

- `DMSC_SourceApproval.gs`
- `DMSC_BackendSmokeSuite.gs`
- `drive-metadata-dashboard/src/GovernanceService.gs`

Do not promote assets to production-ready, source-cleared, classroom-ready, or reusable without explicit human approval and evidence.

### Before dashboard row/detail work

Inspect:

- `Code.gs`
- `DashboardJs.html`
- `DMSC_BackendSmokeSuite.gs`

Do not assume dashboard display behavior, detail lookup, queue definitions, or safe-write behavior without checking these files.

## High-Value Function Anchors

Search these function or service anchors before adding new DMSC code.

### Notion / Visual Asset Library

- `findNotionPagesByFileId`
- `upsertVisualAssetPage`
- `buildNotionPropertyPlan`
- `validateAndWriteVisualAssetLibraryBatch`
- `PropertyAliasService`

### DMSC source approval

- `approveDmscSourceForAsset`
- `getDmscSourceApprovalPreview`
- `getDmscSourceApprovalPreviewBatch`
- `stageDmscSourceApprovalBatch`

### Dashboard rows/details

- `getDmscDashboardRows`
- `getDmscDashboardRecord`
- `deriveDashboardFields_`
- `enrichRegistryRows_`

### Audit / safe writes

- `appendAuditEntry_`
- `appendDmscSourceApprovalAudit_`
- `updateDmscReviewMetadata`

## Do Not Assume

- Do not assume root Apps Script files are the only active code.
- Do not assume nested apps are inactive.
- Do not create new Notion writer logic before reviewing existing Visual Asset Library sync services.
- Do not treat this registry entry as permission to write to DMSC, Notion, Sheets, Drive, or governed fields.
- Do not treat cached navigation metadata as current if the live repository has changed.

## Known Code Zones

### Root Apps Script Dashboard

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

### Existing Drive Metadata Dashboard App

Inspect this nested app before adding DMSC sync or dashboard logic:

- `drive-metadata-dashboard/`
- `drive-metadata-dashboard/src/`

This app contains existing read-only dashboard, governance, Notion sync, Visual Asset Library validation, and write services.

### Existing Notion Sync Services

Before adding any Notion sync, upsert, create, update, duplicate-page detection, or validation logic, inspect:

- `drive-metadata-dashboard/src/NotionDryRun.gs`
- `drive-metadata-dashboard/src/NotionSyncService.gs`
- `drive-metadata-dashboard/src/VisualAssetLibraryValidationService.gs`
- `drive-metadata-dashboard/src/VisualAssetLibraryWriteService.gs`
- `drive-metadata-dashboard/src/VisualAssetLibraryProductionSyncService.gs`
- `drive-metadata-dashboard/src/VisualAssetLibraryPromptMetadataService.gs`
- `drive-metadata-dashboard/src/VisualAssetLibraryDryRunProofService.gs`
- `drive-metadata-dashboard/src/PropertyAliasService.gs`

Known existing capabilities include:

- Visual Asset Library target validation
- guarded Notion dry-run mode
- guarded Notion write mode
- script-property write approvals
- field alias resolution
- prompt metadata extraction
- rich-text / alt-text limits
- duplicate Notion page detection by `file_id`
- create/update upsert behavior
- post-write verification
- dry-run proof checking

### Source Approval Files

Inspect before changing source approval behavior:

- `DMSC_SourceApproval.gs`
- `DMSC_BackendSmokeSuite.gs`
- `drive-metadata-dashboard/src/GovernanceService.gs`
- `VAM_SourceApprovedAudit.js`
- `VAM_SourceApprovedAuditExport.js`
- `VAM_SourceApprovedAuditSmokeTest.js`
- `VAM_SourceApprovedAuditTests.js`

Source approval behavior must remain guarded. Do not promote assets to production-ready, source-cleared, classroom-ready, or reusable without explicit human approval and evidence.

### Search / Metadata Support Apps

Nested apps may contain related utilities but should not be assumed to be the active DMSC dashboard path:

- `apps-script-builder-dashboard/`
- `drive-metadata-dashboard/`
- `search-feature-app/`

## Local-Only / Private Files

Do not commit local execution bindings or temporary scratch artifacts unless explicitly approved:

- `.clasp.json`
- local pasted text files
- temporary logs
- scratch files

The VAM source-approved audit files may exist as local scratch or ignored files depending on the current branch state. Verify live repo and `.claspignore` before changing them.

## Search-Before-Build Rules

Before creating new DMSC implementation code, agents must search the DMSC repo for overlapping behavior.

### Before Notion sync or upsert work

Search for:

- `NotionSyncService`
- `VisualAssetLibraryProductionSyncService`
- `VisualAssetLibraryWriteService`
- `VisualAssetLibraryValidationService`
- `VisualAssetLibraryPromptMetadataService`
- `PropertyAliasService`
- `findNotionPagesByFileId`
- `upsertVisualAssetPage`
- `buildNotionPropertyPlan`
- `Prompt Library`
- `Icon System`
- `Visual Asset Library`

### Before source approval work

Search for:

- `approveDmscSourceForAsset`
- `getDmscSourceApprovalPreview`
- `getDmscSourceApprovalPreviewBatch`
- `stageDmscSourceApprovalBatch`
- `source_approval_status`
- `approval_evidence_url`
- `pilot_review_status`
- `GovernanceService`
- `SourceApprovedAudit`

### Before dashboard row/detail work

Search for:

- `getDmscDashboardRows`
- `getDmscDashboardRecord`
- `deriveDashboardFields_`
- `enrichRegistryRows_`
- `buildListRecord_`
- `buildDetailRecord_`
- `matchesQueue_`

### Before audit or safe-write work

Search for:

- `appendAuditEntry_`
- `appendDmscSourceApprovalAudit_`
- `updateDmscReviewMetadata`
- `safeEditableHeaders`

## Implementation Handoff Rules

- Default DMSC repository review to read-only.
- Use a non-main branch for GitHub changes.
- Do not push directly to `main`.
- Do not alter DMSC production systems from Agent OS registry work.
- Do not write to Notion, Google Sheets, or Google Drive unless explicitly authorized for that system and that field set.
- Use the existing Visual Asset Library sync services before adding any new Visual Asset Library writer.
- Treat `DMSC_NotionSyncPacket.gs` as a read-only routing packet unless a future governed change promotes it into a write adapter.
- For Prompt Library and Icon System sync, first verify whether production sync services already exist. If not, create dry-run planners before any writer.

## Required Tests / Validation Entry Points

Known DMSC validation entrypoints:

- `runDmscBackendSmokeSuite`
- `testBuildDmscNotionLibrarySyncPacket`
- `testGetDmscSourceApprovalPreview`
- `testGetDmscSourceApprovalPreviewBatch`
- `testStageDmscSourceApprovalBatch`
- `testApproveDmscSourceForAssetRoundTrip`

Expected current backend checkpoint after DMSC cleanup:

- `runDmscBackendSmokeSuite` should report `30 passed / 0 failed`.

## Drift Handling

If this registry entry conflicts with the live DMSC repository:

1. Stop before writing.
2. Verify live repo state on `main`.
3. Report the drift.
4. Recommend a registry update or DMSC code review.
5. Do not assume this registry entry authorizes any implementation change.

## Open Questions

- Should Agent OS keep one external repo navigation registry file per external repo, or one consolidated GitHub Path Registry table?
- Should DMSC sync ownership route by feature area or by repository owner?
- Should Prompt Library and Icon System get dedicated sync services modeled after Visual Asset Library services?
- Should the Navigation Registry include exact function-level anchors, or only file-level search guidance?

## Proposed Acceptance Criteria

- Agents can identify the DMSC root dashboard files before implementing.
- Agents can identify existing Visual Asset Library / Notion sync services before creating new code.
- Agents can identify source approval and smoke-test files before changing source approval behavior.
- Agents can identify local/private files that should not be committed.
- The entry clearly states that it is a navigation aid only, not write authorization.
