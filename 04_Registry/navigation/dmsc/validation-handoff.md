# DMSC Validation And Handoff

## Implementation Handoff Rules

- Default DMSC repository review to read-only.
- Use a non-main branch for GitHub changes.
- Do not push directly to `main`.
- Do not alter DMSC production systems from Agent OS registry work.
- Do not write to Notion, Google Sheets, or Google Drive unless explicitly authorized.
- Use existing Visual Asset Library sync services before adding a new writer.
- Treat `DMSC_NotionSyncPacket.gs` as read-only routing unless future governance promotes it.
- For Prompt Library and Icon System sync, verify whether production sync services exist first.
- If they do not exist, create dry-run planners before any writer.

## Required Tests / Validation Entry Points

Known DMSC validation entrypoints:

- `runDmscBackendSmokeSuite`
- `testBuildDmscNotionLibrarySyncPacket`
- `testGetDmscSourceApprovalPreview`
- `testGetDmscSourceApprovalPreviewBatch`
- `testStageDmscSourceApprovalBatch`
- `testApproveDmscSourceForAssetRoundTrip`

Expected backend checkpoint after DMSC cleanup:

- `runDmscBackendSmokeSuite` should report `30 passed / 0 failed`.

## Preferred Future Implementation Route

- For Visual Asset Library sync, adapt or reuse existing services first.
- For Prompt Library and Icon System sync, first verify whether production sync services already exist.
- If no Prompt Library or Icon System services exist, create dry-run planners before any writer.
- Do not create production writers until explicit write authorization exists.
- Keep `DMSC_NotionSyncPacket.gs` read-only unless future governance promotes it into a write adapter.
- Treat cross-system sync as implementation work requiring live repo, schema, and test evidence.

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

If this registry conflicts with the live DMSC repository:

1. Stop before writing.
2. Verify live repo state on `main`.
3. Report the drift.
4. Recommend a registry update or DMSC code review.
5. Do not assume this registry authorizes any implementation change.

## Open Questions

- Should Agent OS keep one external repo navigation registry file per external repo, or one consolidated GitHub Path Registry table?
- Should DMSC sync ownership route by feature area or by repository owner?
- Should Prompt Library and Icon System get dedicated sync services modeled after Visual Asset Library services?
- Should the Navigation Registry include exact function-level anchors, or only file-level search guidance?

## Proposed Acceptance Criteria

- Agents can identify DMSC root dashboard files before implementing.
- Agents can identify existing Visual Asset Library / Notion sync services.
- Agents can identify source approval and smoke-test files before changes.
- Agents can identify local/private files that should not be committed.
- The entry states that it is a navigation aid only, not write authorization.
