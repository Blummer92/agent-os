# DMSC Navigation Overview

## Status

| Field | Value |
|---|---|
| Status | Active split registry |
| Review owner | Integration Manager |
| GitHub write owner | GitHub Service Agent |
| Authority | Navigation aid only |
| External repo | `Blummer92/dmsc_apps_script_bundle` |
| External branch | `main` |
| Last reviewed | Issue #150 split/index cleanup |

## Purpose

Help Agent OS agents navigate the DMSC Apps Script bundle before changing
dashboard, source approval, Notion sync, or validation behavior.

The DMSC repo contains both root Apps Script dashboard code and nested app
services. Agents must inspect existing code zones before creating new paths.

## Governance Placement

- Registry type: GitHub Path Registry / external repository navigation map
- Agent OS location: `04_Registry/navigation/dmsc/`
- Owner agent: Integration Manager
- GitHub write owner: GitHub Service Agent
- Source of truth for this registry entry: Agent OS GitHub
- Source of truth for DMSC code: `Blummer92/dmsc_apps_script_bundle` on `main`
- Runtime systems remain authoritative for live records and execution state.

## Canonical External Repository

| Field | Value |
|---|---|
| Repository | `Blummer92/dmsc_apps_script_bundle` |
| Branch | `main` |
| System | DMSC Apps Script Bundle |
| Primary source of truth | GitHub repository |
| Primary execution surface | Google Apps Script / clasp |
| Human owner | Zachary Blumstein |

## Non-Authoritative Boundary

This registry entry is a lookup aid only. It does not authorize:

- DMSC production writes
- Google Sheets governed-field edits
- Google Drive file edits or sharing changes
- Notion writes
- source approval changes
- classroom readiness changes
- deletion or migration of DMSC code

Agents must verify live repository state before any implementation or write.

## Do Not Assume

- Do not assume root Apps Script files are the only active code.
- Do not assume nested apps are inactive.
- Do not create new Notion writer logic before reviewing existing services.
- Do not treat cached metadata as current if the live repository changed.
