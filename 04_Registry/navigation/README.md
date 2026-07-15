# Navigation Registry

## Purpose

This folder stores governed navigation registry entries for external repositories and systems.

Navigation registry entries help Agent OS agents locate known files, code zones, identifiers, ownership hints, related resources, and search-before-build rules before implementation work begins.

## Authority Boundary

Navigation registry entries are lookup aids only. They do not authorize:

- repository writes
- production system changes
- Google Sheets governed-field edits
- Google Drive file edits or sharing changes
- Notion writes
- readiness, approval, ownership, or source-of-truth changes
- irreversible artifact changes

Live systems remain authoritative for live records, runtime state, source records, repository contents, and execution results.

Agents must verify live repository or system state before implementation, writes, governed-field decisions, approval changes, readiness changes, sharing changes, or irreversible actions.

## Ownership

Navigation Registry governance is owned by the Integration Manager.

GitHub file changes are executed by the GitHub Service Agent through the governed GitHub workflow. Registry updates should use a non-main branch and pull request unless a separate governance-approved process says otherwise.

## Entry Expectations

Each entry should clearly identify:

- system or repository name
- canonical identifier, path, or URL
- source-of-truth boundary
- owner agent or review owner
- known code zones or resource zones
- search-before-build rules
- write boundary
- drift handling notes
- last-known verification context when available

## Drift Handling

If a navigation registry entry conflicts with live system state, agents must stop before writing, report the drift, verify the live source of truth, and recommend a registry correction path.
