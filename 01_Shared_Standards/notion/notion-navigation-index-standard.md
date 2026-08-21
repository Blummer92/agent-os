# Notion Navigation Index Standard

An external Google Sheet, refreshed on demand by a read-only Apps Script
scan of live Notion, that mirrors Notion schema, ownership, and routing
into cached lookup tabs: Dashboard Registry, Database Registry, Property
Dictionary, Relations Map, Status and Readiness Fields, Source of Truth
Matrix, Agent Navigation Guide, Workflow Map, Duplicate/Drift Watchlist,
Agent Prompt Library, and a Refresh Log. Every tab carries the same
banner:

> Navigation aid only. Verify live state in Notion before updating
> readiness, status, ownership, or curriculum decisions.

## Non-Authoritative Rule

The sheet is a cache, never the source of truth. Its own README tab states
the standard agent rule: **"When uncertain, do not edit. Flag for human
review."** Treat every row the same way this standard's sibling file,
`notion-record-update-safety.md`, treats a live Notion record: confirm
before acting, don't infer. A cached value never grants write, readiness,
approval, or ownership authority.

## Two-Step Lookup Pattern

1. **Consult the navigation index first** for owner, routing,
   duplicate-risk, or schema questions. This is the cheap step — no live
   Notion call needed.
2. **Verify live Notion before any write, readiness/status change, or
   governed-field decision.** The sheet's own Agent Navigation Guide and
   Source of Truth Matrix tabs already encode this per agent type ("Then
   Check", "Do Not Edit", "Verification Step Before Edit" columns) — do
   not skip step 2 because step 1 returned an answer.

## Cache Rule

A fetched tab is fresh for one agent session; do not re-fetch mid-session
unless the governing consumer explicitly requires current live verification.
Do not silently trust a row where `Human Review Needed?` is `Yes` — surface
it instead of treating the cached value as settled.

## Write Boundary

Agents never write to this sheet as part of lookup — refreshing it is an
approved Apps Script capability operation, not an implication of cached
lookup. A lookup result is never itself authorization to write to Notion;
it only tells you where to look and who owns it.

## Overlay Mapping

The sheet's own "Agent Type" column uses names that don't match Agent OS's
canonical overlays. These values are compatibility labels, not a canonical
Agent OS executable-agent registry:

| Sheet Agent Type | Current Agent OS Route |
|---|---|
| Curriculum Agent | `02_Agent_Overlays/unit-alignment-agent.md` |
| Modeling / Governance Agent | `02_Agent_Overlays/modeling-dashboard-governance-agent.md` |
| Dashboard Agent | `02_Agent_Overlays/dashboard-builder-overlay.md` plus current routing rules |
| QA Agent | `02_Agent_Overlays/qa-test-agent.md` |
| PM Agent / Reporting Agent | `02_Agent_Overlays/chatgpt-orchestrator.md` plus Navigation Registry standards |
| Integration Manager | legacy alias -> ChatGPT Orchestrator plus Navigation Registry standards |

## Tooling

`08_Tooling/notion-navigation-client/` implements the read client agents
use to query the cached tabs. It has no write capability of any kind.

## Version

0.2.0

## Changelog

- 0.2.0 preserves the full cache, lookup, and write-boundary contract while mapping historical Integration/PM routing labels to ChatGPT Orchestrator plus shared Navigation Registry standards (#1324).
- 0.1.0 initial standard.
