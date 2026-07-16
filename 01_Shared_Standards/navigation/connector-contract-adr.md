# ADR: Canonical Read-Only Connector Contract

## Status

Accepted.

## Context

M2 Unified Connectors needs one read-only contract before B2, B3, B4, and B5 implement or migrate connector behavior. Agent OS currently has Notion-specific lookup tooling and standards, plus shared Navigation Registry governance for cross-system lookup. Without a named canonical contract, new work can accidentally preserve multiple access shapes and make later migration ambiguous.

GitHub remains the source of truth for Agent OS governance, standards, overlays, registry schemas, tests, templates, and release notes. Live connected systems remain authoritative for their own records. Connector reads and registry lookups do not authorize writes, readiness changes, approval changes, sharing changes, ownership changes, governed-field edits, or source-of-truth changes.

## Decision

The canonical read-only connector contract for Agent OS is named **Navigation Registry Read Contract**.

The Navigation Registry Read Contract is the stable target for Agent OS connector read paths. It provides lookup and routing data using the common Navigation Registry model: system, resource type, canonical identifier or path, display name, aliases, owner, source of truth, relationship metadata, last verified state, verification method, human-review flag, write boundary, and navigation warnings.

All implementations of this contract must be read-only. They may expose cached lookup results, relationship traversal, alias resolution, owner/routing hints, freshness metadata, drift warnings, and human-review flags. They must not expose write methods, mutate live systems, refresh operational caches without approved ownership, or treat lookup results as authority for live-system changes.

## Compatibility and Rejected Alternative

Rejected: making the existing Notion navigation client shape the cross-system contract.

The Notion client remains valid as a system-specific adapter and compatibility layer, but it is not the canonical cross-system contract. Promoting the Notion-specific shape would couple future Drive, GitHub, Sheets, Calendar, and other connectors to Notion tab names, Notion field terminology, and Notion-only lookup commands.

Compatibility approach: existing Notion-specific read paths may continue temporarily. New M2 connector work should target the Navigation Registry Read Contract. System-specific adapters may translate from live APIs, cached tabs, or existing client output into the canonical read result shape while preserving warnings and source-of-truth boundaries.

## Migration Note For Existing Notion Call Sites

Existing Notion call sites should migrate in two steps:

1. Keep current Notion navigation reads in place where they are already read-only and preserve `navigation_warning` and human-review flags.
2. Add or route through an adapter that returns Navigation Registry Read Contract records instead of exposing Notion-specific tab or field shapes directly.

During migration, do not add write behavior, do not change live Notion verification requirements, and do not treat cached Notion results as authorization for readiness, status, ownership, curriculum, sharing, or governed-field decisions.

## Consequences

B2, B3, B4, and B5 can reference a single canonical read contract without implementing the shared client in this ADR. This ADR does not implement the client, change runtime connector behavior, modify production systems, or write to Notion, Google Drive, Google Sheets, or other external systems.
