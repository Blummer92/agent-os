# DMSC Implementation Preflight

## Required Preflight

Before implementing DMSC changes, inspect the relevant existing code zones first.
DMSC code exists in both root Apps Script files and nested app folders.

## Before Notion Sync Or Upsert Work

Inspect:

- `drive-metadata-dashboard/src/NotionDryRun.gs`
- `drive-metadata-dashboard/src/NotionSyncService.gs`
- `drive-metadata-dashboard/src/VisualAssetLibraryValidationService.gs`
- `drive-metadata-dashboard/src/VisualAssetLibraryWriteService.gs`
- `drive-metadata-dashboard/src/VisualAssetLibraryProductionSyncService.gs`
- `drive-metadata-dashboard/src/VisualAssetLibraryPromptMetadataService.gs`
- `drive-metadata-dashboard/src/PropertyAliasService.gs`

Do not create new Notion writer, upsert, duplicate-page, prompt-mapping, or
Visual Asset Library sync logic before this review is complete.

## Before Source Approval Work

Inspect:

- `DMSC_SourceApproval.gs`
- `DMSC_BackendSmokeSuite.gs`
- `drive-metadata-dashboard/src/GovernanceService.gs`

Do not promote assets to production-ready, source-cleared, classroom-ready, or
reusable without explicit human approval and evidence.

## Before Dashboard Row Or Detail Work

Inspect:

- `Code.gs`
- `DashboardJs.html`
- `DMSC_BackendSmokeSuite.gs`

Do not assume dashboard display behavior, detail lookup, queue definitions, or
safe-write behavior without checking these files.

## High-Value Function Anchors

Notion / Visual Asset Library:

- `findNotionPagesByFileId`
- `upsertVisualAssetPage`
- `buildNotionPropertyPlan`
- `validateAndWriteVisualAssetLibraryBatch`
- `PropertyAliasService`

DMSC source approval:

- `approveDmscSourceForAsset`
- `getDmscSourceApprovalPreview`
- `getDmscSourceApprovalPreviewBatch`
- `stageDmscSourceApprovalBatch`

Dashboard rows/details:

- `getDmscDashboardRows`
- `getDmscDashboardRecord`
- `deriveDashboardFields_`
- `enrichRegistryRows_`

Audit / safe writes:

- `appendAuditEntry_`
- `appendDmscSourceApprovalAudit_`
- `updateDmscReviewMetadata`
