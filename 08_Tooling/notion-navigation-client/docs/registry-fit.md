# Registry Fit

`notion-navigation-client` is the read-only Notion adapter for Agent OS navigation lookups.

It is not the full cross-system Navigation Registry.

## Governance layers

- `01_Shared_Standards/navigation/navigation-registry-standard.md` defines cross-system Navigation Registry governance for Notion, Google Drive, GitHub, and future approved systems.
- `01_Shared_Standards/notion/notion-navigation-index-standard.md` defines the Notion-specific cached index standard.
- Integration Manager owns Navigation Registry governance and cross-system lookup routing.
- Google Workspace Automation Engineer may support implementation work for Workspace tooling when approved.
- GitHub Service Agent owns repository writes, branches, commits, pull requests, and release validation.
- `08_Tooling/notion-navigation-client/` implements the Notion-specific read client for cached Google Sheet tabs.

## Source-of-truth boundary

The client may return cached navigation metadata such as dashboards, databases, fields, workflows, prompts, source-of-truth hints, duplicate-risk rows, URLs, ownership hints, and human-review flags.

A lookup result is never authorization to write, change readiness or status, change ownership, make source-of-truth decisions, change source authority, authorize production, change sharing, or edit governed fields.

Agents must verify live Notion before any write, readiness/status change, ownership change, source-of-truth decision, production-authorization decision, or governed-field decision.

## Safe use

Use this client to find where to look first.

Then verify the live system of record before acting.
