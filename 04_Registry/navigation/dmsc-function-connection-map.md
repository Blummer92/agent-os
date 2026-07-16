# DMSC Function Connection Map

## Purpose

This file is the compact index for DMSC function-flow navigation. It replaces
the former oversized flow map while preserving its routing intent in smaller
subfiles.

## Boundary

This map is a navigation aid only. It is not write authorization.

Agents must verify live repository state in `Blummer92/dmsc_apps_script_bundle`
on `main` before implementation. Cached function relationships may drift when
files move, functions are renamed, clasp deployments change, or nested app
services are reorganized.

This map does not authorize:

- DMSC production writes
- Google Sheets governed-field edits
- Google Drive file edits or sharing changes
- Notion writes
- source approval changes
- classroom readiness changes
- production writer creation

## Flow Map

See `dmsc/function-flow-map.md` for:

- DMSC dashboard read flow
- guarded source approval flow
- read-only Notion packet flow
- existing Visual Asset Library sync flow
- preferred future implementation route
- unknowns to verify in the live repo

## Drift Handling

If this map conflicts with the live DMSC repository:

1. Stop before writing.
2. Inspect the live DMSC repo on `main`.
3. Identify the conflicting file, function, or deployment boundary.
4. Report the drift.
5. Recommend a registry update or implementation handoff.

Do not use this map to override live source-of-truth state.

## Version

0.2.0

## Changelog

- 0.2.0 converted the oversized map into an index for Issue #150.
- 0.1.0 initial DMSC function connection map.
