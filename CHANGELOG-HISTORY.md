# Changelog History

Archived historical changelog content. For current and recent history, see [CHANGELOG.md](CHANGELOG.md).

## 0.1.1-draft — archived entries
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
