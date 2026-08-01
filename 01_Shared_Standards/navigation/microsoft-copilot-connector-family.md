# Microsoft 365 Copilot Connector Family

## Purpose

This document defines vocabulary only. It describes the integration patterns
available for connecting Agent OS to Microsoft 365 Copilot and other external
clients, and names the selected path. It does not define a framework
extension, a manifest, an OpenAPI spec, deployment guidance, or code.

## Integration Patterns

**Indexed connector** — admin-deployed ingestion, such as Microsoft's
Google Drive or GitHub Issues/Pull Requests connectors. Indexes content into
a search or knowledge surface. Does not execute, gate, or route requests.

**Federated MCP** — a Microsoft-hosted, query-time integration reachable
through Model Context Protocol, enabled by a tenant administrator.

**Custom MCP plugin** — points at a remote MCP server. Tools are discovered
dynamically at connection time, so a manifest cannot restrict them as
tightly as a static OpenAPI allowlist can.

**Custom API plugin** — points at an OpenAPI spec. The plugin manifest's
`run_for_functions` list is a hard allowlist of callable operations.

**External-client OpenAPI bridge** — the pattern this repository is
adopting: one hosted OpenAPI contract, consumed by multiple clients.

## Selected Path

Agent OS adopts the external-client OpenAPI bridge pattern: one hosted
OpenAPI contract, proved through ChatGPT Actions first, and consumable by a
Microsoft 365 Copilot API plugin later.

## Authority Boundary

The identity and write-authority boundary for any bridge implementing this
pattern is defined in
`00_Governance/architecture-decisions/adr-0003-cloud-execution-substrate.md`.
This document does not restate, re-decide, or reinterpret that boundary.

## Non-Goals

This document does not describe how to deploy a Microsoft 365 connector, a
Teams app, a Copilot plugin, an OAuth client, a cloud resource, or an MCP
server. Deployment and framework extension are separate, later decisions.

## Version

0.1.0

## Changelog

- 0.1.0 defined the integration-pattern vocabulary and named the
  external-client OpenAPI bridge as the selected path.
