# Changelog
## 0.1.1-draft
- Added ChatGPT implementation bridge: root `AGENTS.md`, ChatGPT Orchestrator overlay, GitHub Service Agent overlay, GitHub Change Request template, matching overlay tests, registry ownership/responsibility updates, and manual validation notes for Issue #59.
- Docs accuracy: fixed `08_Tooling/workflow-scheduler/docs/` (USER_GUIDE, ARCHITECTURE, API_REFERENCE) still calling shipped Phase 2A-2E features unimplemented; also fixed a stale diagram and missing max_workers docs. Docs only.
- Repo cleanup (PR 3 of 3): moved four completed Workflow Scheduler planning docs out of the repo root into `06_Archive/workflow-scheduler-planning/` -- `PART_A_FINAL_SUMMARY.md`, `PART_A_TO_PART_B_HANDOFF.md`, `PHASE_0_BASELINE_CORRECTED.md`, `PHASE_B_SCOPE.md`. Files moved, not deleted or rewritten.
- Repo cleanup (PR 2 of 3): documented `08_Tooling/workflow-scheduler/` in `CLAUDE.md`'s `08_Tooling/` Contents list. Short, factual entry only; no scheduler docs rewritten, no scheduler code touched, no line-limit fixes.
- Repo cleanup (PR 1 of 3): deleted six stale one-time GitHub-upload/bootstrap files that referenced ephemeral local staging paths or one-time setup steps from before this repo existed on GitHub. No code or behavior changes.
- Documented a known limitation in `08_Tooling/notion-navigation-client/README.md`: live-sheet structural validation is blocked by a platform-side Claude.ai connector-approval bug; fixture/mock tests remain the only validated test path until resolved externally or run locally with OAuth credentials.
- Added `01_Shared_Standards/notion/notion-navigation-index-standard.md` and `08_Tooling/notion-navigation-client/`, documenting the user-provided Notion navigation-index Google Sheet as a non-authoritative navigation aid and adding a read-only Python client with fixture-backed tests.
- Added an `## Agent Compute Profiles` section to `01_Shared_Standards/instructional-design/production-gates-and-compute.md`, updated three prompt templates, tightened tests, and bumped Instructional Design Standards to 0.5.0.
- Added `00_Governance/agent-os-advisory-mode.md` and a Current Operating Mode section in `CLAUDE.md` so Agent OS is advisory during pilot review for low-risk work while preserving strict approval gates for sensitive writes.
- Added `03_Templates/prompts/daily-agent-shortcuts.md` with low-friction daily lanes for dashboard drafts, QA reviews, Python local fixes, and instructional material drafts without weakening safety gates.
- Gave Instructional Materials Coach a Notion learning loop that writes local lesson-candidate records matching the real Lessons Learned field schema and documented the schema in `01_Shared_Standards/notion/notion-learning-databases.md`.
- Added Instructional Materials Coach as a canonical agent, registered it, added tests, added a prompt-index entry, and added a runnable Python package at `08_Tooling/instructional-materials-coach/` for Slides decks and Docs worksheets from approved templates.
- Fixed `validate-repo-structure.sh` registry and empty-folder checks, added missing module-version records, and fixed a wrong path plus inconsistent shorthand in CLAUDE.md troubleshooting examples.
- Added `07_Agent_Tests/`: compliance test prompts, a shared pass/fail checklist, and `validate-repo-structure.sh` structural regression tests.
- Extracted `02_Agent_Overlays/_common-overlay-rules.md` from duplicated overlay blocks; overlays now reference it instead of repeating shared content.
- Renamed `00_Governance/agent-inheritance-registry.md` to `agent-creation-policy.md` and made `04_Registry/agent-inheritance-registry.md` the sole source for the agent list and inheritance mapping.
- Clarified dashboard sync routing and prevented duplicate standalone Dashboard Sync Agent ownership.
- Retired Apps Script Sync Test Agent as a standalone canonical agent name.
- Preserved Apps Script Sync Test Overlay as specialist sync-validation behavior.
- Added routed dashboard sync combinations to registry guidance.
## 0.1.0
- Created modular Agent OS Markdown knowledge base.
- Split shared rules by domain.
- Added canonical agent overlays and specialist overlays.
- Added registry, templates, examples, archive notes, manifest, and validation report.