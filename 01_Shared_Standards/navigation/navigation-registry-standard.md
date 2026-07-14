# Navigation Registry Standard

## Purpose

Define a governed cross-system lookup layer for Agent OS. The registry helps
agents locate resources through cached identifiers, relationships, aliases, and
metadata while preserving each connected system's source-of-truth boundary.

## Scope

This shared standard covers navigation metadata for Notion, Google Drive,
GitHub, and future approved systems. System-specific navigation standards may
inherit from this standard and add implementation details for one surface.

## Source Of Truth Boundary

GitHub remains the source of truth for Agent OS governance, standards,
overlays, registry schemas, tests, templates, and release notes.

Live operational systems remain authoritative for their own records. A cached
registry result never changes which system owns the live artifact.

## Non-Authoritative Rule

The Navigation Registry is a lookup aid only. Cached records do not authorize
writes, source-of-truth changes, readiness changes, approval changes,
ownership changes, sharing changes, or governed-field edits.

## Two-Step Lookup Pattern

1. Consult the Navigation Registry first for cheap lookup, routing, aliases,
   identifiers, ownership hints, and relationship metadata.
2. Verify live system state before any write, governed-field decision,
   readiness/status update, ownership update, sharing change, or irreversible
   action.

## Registry Areas

Approved registry areas may include System Registry, Database Registry, Page
Registry, Drive Folder Registry, Drive File Registry, GitHub Path Registry,
Template Registry, Workflow Registry, Relationship Registry, Alias Registry,
Drift Watchlist, and Refresh Log.

## Required Entry Fields

Each registry entry should identify system, resource type, display name,
canonical identifier or path, aliases, owner agent, source of truth, related
resources, last verified state, verification method, human-review flag, write
boundary, and notes.

## Ownership

The Integration Manager owns cross-system navigation governance and routing.
System-specific owners retain authority over their live systems and required
approval paths.

## Write Boundary

Agents may read Navigation Registry records for lookup. They may not treat a
registry result as permission to write. Registry refreshes, schema changes, or
operational cache writes require approved ownership and source-of-truth
confirmation.

## Drift Handling

If cached metadata conflicts with live system state, agents stop before
writing, surface the drift, identify the likely source of truth, and recommend
a correction path.

## Version

0.1.0
