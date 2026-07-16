# DMSC Apps Script Bundle Navigation Registry

## Status

| Field | Value |
|---|---|
| Status | Active index |
| Review owner | Integration Manager |
| GitHub write owner | GitHub Service Agent |
| Authority | Navigation aid only |
| External repo | `Blummer92/dmsc_apps_script_bundle` |
| External branch | `main` |
| Last reviewed | Issue #150 split/index cleanup |

## Purpose

Help Agent OS agents navigate `Blummer92/dmsc_apps_script_bundle` before
implementing DMSC Apps Script, dashboard, source approval, or Notion sync
changes.

This index replaces the former oversized single-file map. Use the linked
subfiles for focused navigation, then inspect the live DMSC repo on `main`.

## How Agents Should Use This Entry

1. Identify the relevant work area.
2. Read the matching subfile below.
3. Inspect listed files in the live DMSC repo on `main`.
4. Search listed anchors before adding new code.
5. Stop and report drift if live code differs from this registry.
6. Treat all entries as navigation only, not write authorization.

## Split Navigation Files

| Need | File |
|---|---|
| Boundary, ownership, repo facts | `dmsc/overview.md` |
| Required implementation preflight | `dmsc/preflight.md` |
| Root and nested code zones | `dmsc/code-zones.md` |
| Search-before-build anchors | `dmsc/search-rules.md` |
| Tests, handoffs, drift handling | `dmsc/validation-handoff.md` |
| Flow-level function map | `dmsc/function-flow-map.md` |

## Related Function Map

The former `dmsc-function-connection-map.md` is now a compact index that points
to `dmsc/function-flow-map.md`.

## Non-Authoritative Boundary

This registry is a lookup aid only. It does not authorize:

- DMSC production writes
- Google Sheets governed-field edits
- Google Drive file edits or sharing changes
- Notion writes
- source approval changes
- classroom readiness changes
- deletion or migration of DMSC code

Agents must verify live repository state before any implementation or write.

## Version

0.2.0

## Changelog

- 0.2.0 split the oversized DMSC map into indexed subfiles for Issue #150.
- 0.1.0 initial DMSC Apps Script bundle navigation proposal.
