# Notion Navigation Index Standard

An external Google Sheet, refreshed on demand by a read-only Apps Script scan of
live Notion, that mirrors schema, ownership, and routing into cached lookup tabs.
Every tab carries the same non-authoritative warning: verify live Notion before
updating readiness, status, ownership, or curriculum decisions.

## Non-Authoritative Rule

The sheet is a cache, never the source of truth. When uncertain, do not edit;
flag for human review. A cached value never grants write, readiness, approval, or
ownership authority.

## Two-Step Lookup Pattern

1. Consult the navigation index first for owner, routing, duplicate-risk, or schema questions.
2. Verify live Notion before any write, readiness/status change, or governed-field decision.

## Cache Rule

A fetched tab is fresh for one agent session; do not re-fetch mid-session unless
the governing consumer explicitly requires current live verification. Do not
silently trust a row where human review is required.

## Write Boundary

Agents never write to this sheet as part of lookup. Refreshing it is an approved
Apps Script capability operation, not an implication of cached lookup. A lookup
result is never itself authorization to write to Notion.

## Overlay Mapping

The sheet's historical "Agent Type" values are compatibility labels, not a
canonical Agent OS executable-agent registry:

| Sheet Agent Type | Current Agent OS Route |
|---|---|
| Curriculum Agent | `02_Agent_Overlays/unit-alignment-agent.md` |
| Modeling / Governance Agent | `02_Agent_Overlays/modeling-dashboard-governance-agent.md` |
| Dashboard Agent | `02_Agent_Overlays/dashboard-builder-overlay.md` plus current routing rules |
| QA Agent | `02_Agent_Overlays/qa-test-agent.md` |
| PM Agent / Reporting Agent | `02_Agent_Overlays/chatgpt-orchestrator.md` plus Navigation Registry standards |
| Integration Manager | legacy alias -> ChatGPT Orchestrator plus Navigation Registry standards |

## Tooling

`08_Tooling/notion-navigation-client/` implements the read client used to query
cached tabs. It has no write capability.

## Version

0.2.0

## Changelog

- 0.2.0 maps historical Integration/PM routing labels to ChatGPT Orchestrator plus shared Navigation Registry standards (#1324).
- 0.1.0 initial standard.
