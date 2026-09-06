# Agent OS ChatGPT MCP Facade — #1966

## Purpose

This is the explicit ChatGPT-facing Agent OS app surface selected as the bounded successor to #1237. It does not replace ChatGPT's hidden/global router. The v1 contract applies when the Agent OS app is explicitly selected or invoked.

```text
ChatGPT + Agent OS app
-> two bounded MCP tools
-> existing Agent OS route/continuation owners
-> existing GitHub connector for any authorized repository write
-> existing GitHub -> GCE transport
-> server-side #1242/#1218 discovery/currentness
-> existing Scheduler/lease owners
```

## MCP tools

`plan_agent_os_continuation_tool(repository, issue_number, canonical_handoff_id=None)` accepts only bounded repository/issue identity plus an optional handoff that must already have been produced by canonical Agent OS evidence. Without a handoff it returns `discover-current-handoff`; with one canonical `executor-handoff:<64hex>` it preserves the identity exactly and returns the existing `/agent-os resume <id>` ingress. It never scans a checkpoint store or invents an identity.

`classify_agent_os_continuation_tool(...)` adapts structured attempt evidence into the existing #1237 `post_selection_continuation` contract. It adds no classification or routing vocabulary. `CAPABILITY_ALTERNATIVE_AVAILABLE` remains automatic same-lineage continuation; ambiguous effects require readback; cross-surface compatibility remains #1201-owned; repeated equivalent recovery remains #1200-owned; red CI, base drift, and stale gates remain with #1251/#1209/#1235.

Both tools are non-authorizing. Their result models cannot grant execution, GitHub writes, merge, closure, external writes, Scheduler admission, or lease acquisition.

## Discovery and write boundaries

#1284 remains unchanged: MCP never reads `<checkpoint_store>/invocations/*.json` directly. The app requests the existing server-side discovery operation through the governed GitHub/GCE path. Zero matches remain `not-found`; multiple/corrupt/unavailable evidence remains `needs-decision`; no newest/latest heuristic is added.

The MCP server has no GitHub repository-write credential in this phase. GitHub mutations remain GitHub Service Agent-owned and use the existing connected GitHub surface. The MCP facade does not invoke GitHub, Scheduler, shell, provider, cloud, VM, publication, authorized validation, activation, resume, or replay itself.

## Protocol binding

`agent_os_execution_service.mcp_server` uses the official Python MCP SDK (`mcp>=2.1.1,<2.2`) and registers exactly the two tools above with `MCPServer`. The repository phase does not start a network listener or choose a deployment transport.

`mcp_facade` imports the #1237 owner from `scripts.agent_os_execution_interface.post_selection_continuation`. That package is already distributed by `workflow-scheduler` (#1426), and this distribution declares `workflow-scheduler>=0.18.0,<0.19.0`, so a clean host installation resolves the continuation owner through the existing single-owner distribution boundary. It is deliberately not re-packaged here: #1300 requires that no runtime module be carried by two distributions.

The SDK supports stdio and Streamable HTTP, but hosting, authentication/principal validation, origin/host policy, TLS/network exposure, ChatGPT Developer Mode/app installation, Secure MCP Tunnel, credentials, and production activation are separate external/configuration decisions and are not authorized by #1966.

## #1233 regression intent

With the Agent OS app explicitly selected:

```text
Work on #1233
-> plan_agent_os_continuation_tool(Blummer92/agent-os, 1233)
-> discover-current-handoff (server-side governed path)
-> canonical handoff, if exactly one/current, is preserved
-> existing governed resume ingress
```

Local `gh` is not an input to the MCP plan and therefore cannot become a global Agent OS availability gate. If local CLI is later explicitly selected for a different operation, its prerequisites remain relevant only to that selected surface.

## #1239 boundary

This facade does not solve or fake the canonical `AuthorizedValidationLifecycleRequest` v1.1 producer path. It does not serialize `SingleIssuePilotInput`, put validation evidence in prompt/comment text, invoke #1929/#1830, create a source capsule, activate #1959, resume, or replay. After the MCP app is externally activated and the #1233 route regression is proven, return to #1237 and then separately reconcile the remaining #1239 source-envelope integration.

## Rollback

Remove `mcp_facade.py`, `mcp_server.py`, their focused tests/docs, and the `mcp` dependency. Existing #1237 policy, #1284 server-side discovery, #1203/#1217 transport, #1218 currentness, GitHub connector, Scheduler state, and all external systems remain unchanged.
