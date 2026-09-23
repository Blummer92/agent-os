# DMSC Search-Before-Build Rules

## Purpose

Before creating new DMSC implementation code, agents must search the live DMSC
repo for overlapping behavior.

## Before Notion Sync Or Upsert Work

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

## Before Source Approval Work

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

## Before Dashboard Row Or Detail Work

Search for:

- `getDmscDashboardRows`
- `getDmscDashboardRecord`
- `deriveDashboardFields_`
- `enrichRegistryRows_`
- `buildListRecord_`
- `buildDetailRecord_`
- `matchesQueue_`

## Before Audit Or Safe-Write Work

Search for:

- `appendAuditEntry_`
- `appendDmscSourceApprovalAudit_`
- `updateDmscReviewMetadata`
- `safeEditableHeaders`
