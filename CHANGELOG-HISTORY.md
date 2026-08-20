# Changelog History

Archived historical changelog content. For current and recent history, see [CHANGELOG.md](CHANGELOG.md).

## 0.1.1-draft — archived entries
- Added `00_Governance/agent-os-advisory-mode.md` and a Current Operating Mode section in `CLAUDE.md` so Agent OS is advisory during pilot review for low-risk work while preserving strict approval gates for sensitive writes.
- Added Instructional Materials Coach as a canonical agent, registered it, added tests, added a prompt-index entry, and added a runnable Python package at `08_Tooling/instructional-materials-coach/` for Slides decks and Docs worksheets from approved templates.
- Fixed `validate-repo-structure.sh` registry and empty-folder checks, added missing module-version records, and fixed a wrong path plus inconsistent shorthand in CLAUDE.md troubleshooting examples.
- Clarified dashboard sync routing and prevented duplicate standalone Dashboard Sync Agent ownership.
- Retired Apps Script Sync Test Agent as a standalone canonical agent name.
- Preserved Apps Script Sync Test Overlay as specialist sync-validation behavior.
- Renamed `00_Governance/agent-inheritance-registry.md` to `agent-creation-policy.md` and made `04_Registry/agent-inheritance-registry.md` the sole source for the agent list and inheritance mapping.

## 0.1.0
- Created modular Agent OS Markdown knowledge base.
- Split shared rules by domain.
- Added canonical agent overlays and specialist overlays.
- Added registry, templates, examples, archive notes, manifest, and validation report.
- Added routed dashboard sync combinations to registry guidance.
- Extracted `02_Agent_Overlays/_common-overlay-rules.md` from duplicated overlay blocks; overlays now reference it instead of repeating shared content.
- Added `07_Agent_Tests/`: compliance test prompts, a shared pass/fail checklist, and `validate-repo-structure.sh` structural regression tests.
- Gave Instructional Materials Coach a Notion learning loop that writes local lesson-candidate records matching the real Lessons Learned field schema and documented the schema in `01_Shared_Standards/notion/notion-learning-databases.md`.
- Added `03_Templates/prompts/daily-agent-shortcuts.md` with low-friction daily lanes for dashboard drafts, QA reviews, Python local fixes, and instructional material drafts without weakening safety gates.
