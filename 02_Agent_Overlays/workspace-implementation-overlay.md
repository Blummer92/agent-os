# Workspace Implementation Overlay

## Status

Specialist Workspace capability guidance; not a canonical executable agent.

## Inherited Standards

See `_common-overlay-rules.md` plus:
- `01_Shared_Standards/google-workspace/workspace-automation-builder.md`
- `01_Shared_Standards/google-workspace/workspace-write-authorization.md`

## Mission

Preserve scoped Workspace implementation and external-operation constraints
without creating a separate technical execution role.

## Routing

- Repository source, tests, package metadata, and implementation documentation -> GitHub Service Agent plus Google Workspace standards.
- Cross-system/target/operation classification -> ChatGPT Orchestrator plus Google Workspace standards.
- Independent validation evidence -> QA / Test Agent.
- Approved live Workspace mutation -> an available approved connector/capability only after `01_Shared_Standards/google-workspace/workspace-write-authorization.md` is satisfied.

## Allowed Capability Surfaces

Scoped dry-run plans, target inventories, mocked/fixture requests, and separately
authorized exact Workspace operations through the approved connected capability.

## Blocked Authority

This overlay never grants repository writes, live Workspace writes, production,
credentials, sharing, permission, trigger, deployment, governed-field, or
source-of-truth authority by itself. No legacy agent name can widen these limits.

## Required Handoff Targets

Changed repository files when applicable, target checks, exact operation, tests,
external-write authorization still needed, rollback/reconciliation notes, and
remaining blockers.

## Version

0.2.0

## Changelog

- 0.2.0 converts the former specialist execution overlay into agent-independent capability guidance after retirement of the Workspace-specific canonical technical agent (#1324).
- 0.1.0 initial overlay.
