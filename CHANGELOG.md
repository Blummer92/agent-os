# Changelog

## 0.1.1-draft

- Added `00_Governance/agent-os-advisory-mode.md` and a Current Operating Mode section in `CLAUDE.md` so Agent OS is advisory during pilot review for low-risk day-to-day work while preserving strict approval gates for external writes, production changes, governed fields, source-of-truth records, sharing/permissions, sensitive student/private data, and irreversible actions.
- Added `03_Templates/prompts/daily-agent-shortcuts.md` with low-friction daily lanes for dashboard drafts, QA reviews, Python local fixes, and instructional material drafts so Tier 0/Tier 1 work can proceed after lightweight intake without weakening safety gates for external writes, production systems, governed fields, sharing/permissions, source-of-truth records, or irreversible actions.
- Gave Instructional Materials Coach a Notion learning loop: on a failed build, `08_Tooling/instructional-materials-coach/` now writes a local lesson-candidate record (matching the real "Lessons Learned" Notion database's field schema) instead of failing silently, plus a `--log-lesson` mode for manual QA-feedback entries. The tool never writes to Notion directly -- a human applies the record using the field-mapping table in its README, since no agent in this repo has documented Notion write authority. Documented the real Lessons Learned schema in `01_Shared_Standards/notion/notion-learning-databases.md` (bumped to 0.1.1) so it doesn't need re-discovering via live Notion fetches, and added an "Instructional Materials" option to the live database's Applies To field to match.
- Added Instructional Materials Coach as a new canonical agent (`02_Agent_Overlays/instructional-materials-coach.md`), registered in `04_Registry/agent-inheritance-registry.md`, `ownership-matrix.md`, and `responsibility-matrix.md`, with a matching `07_Agent_Tests/instructional-materials-coach.tests.md`, a prompt-index entry, and a runnable Python package at `08_Tooling/instructional-materials-coach/` that builds Slides decks and Docs worksheets by duplicating an approved template and replacing placeholder tokens. Added a supporting rule to `01_Shared_Standards/google-workspace/drive-docs-sheets-safety.md` ("never write to a template or master file directly; duplicate it first") and bumped Google Workspace Standards to 0.1.1.
- Fixed `validate-repo-structure.sh`: the registry-coverage check silently reported PASS if `04_Registry/agent-inheritance-registry.md` was deleted entirely (now an explicit FAIL); overlay/test-coverage checks left raw shell-glob errors on screen if a folder was emptied (now `nullglob` plus an explicit empty-folder FAIL). Added `Read-Only Default` and `Source-of-Truth Checks` to `04_Registry/module-version-map.md`, which every overlay cites with a version but which had no version record. Fixed a wrong file path and inconsistent shorthand in CLAUDE.md's troubleshooting examples.
- Added `07_Agent_Tests/`: a compliance test-prompt file per overlay (4 prompts each covering in-scope requests, blocked write surfaces, ambiguous targets, and final report format), a shared pass/fail checklist, and `validate-repo-structure.sh`, an automated script that checks line limits, overlay deduplication, governance/registry filename collisions, and overlay/test coverage.
- Extracted `02_Agent_Overlays/_common-overlay-rules.md` from the four blocks (Inherited Standards, Required Human Approval Points, Required Final Report Format, Stop Conditions) that were duplicated verbatim across all 8 overlay files; overlays now reference this file instead of repeating it, cutting each overlay from 37 to 19 lines.
- Renamed `00_Governance/agent-inheritance-registry.md` to `agent-creation-policy.md` and removed its duplicate agent list, which conflicted with `04_Registry/agent-inheritance-registry.md`; the registry file is now the sole source for the agent list and inheritance mapping.
- Clarified dashboard sync routing and prevented duplicate standalone Dashboard Sync Agent ownership.
- Retired Apps Script Sync Test Agent as a standalone canonical agent name.
- Preserved Apps Script Sync Test Overlay as specialist sync-validation behavior.
- Added routed dashboard sync combinations to registry guidance.

## 0.1.0

- Created modular Agent OS Markdown knowledge base.
- Split shared rules by domain.
- Added canonical agent overlays and specialist overlays.
- Added registry, templates, examples, archive notes, manifest, and validation report.
