# DMSC Navigation Registry Index

## Purpose

This folder contains the split DMSC navigation registry formerly held in two
oversized files under `04_Registry/navigation/`.

## Parent Indexes

- `../dmsc-apps-script-bundle.md`
- `../dmsc-function-connection-map.md`

## Files

| File | Use |
|---|---|
| `overview.md` | Ownership, source-of-truth, and boundary facts |
| `preflight.md` | Required inspections before implementation |
| `code-zones.md` | Root dashboard and nested app zones |
| `search-rules.md` | Search-before-build anchors |
| `function-flow-map.md` | Flow-level function relationships |
| `validation-handoff.md` | Tests, handoff rules, drift handling, open questions |

## Use Rule

Read the smallest file needed for the DMSC task, then inspect the live
`Blummer92/dmsc_apps_script_bundle` repo on `main`.

## Boundary

These files are navigation aids only. They do not authorize DMSC production
writes, Notion writes, Google Drive writes, governed-field edits, or external
repo changes.
