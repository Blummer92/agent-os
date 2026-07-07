# Changelog

## 0.1.1-draft

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
