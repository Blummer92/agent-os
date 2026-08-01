# ADR 0003: Cloud Execution Substrate

## Status

Accepted for planning. Documentation only.

## Context

Agent OS is reachable from ChatGPT through `AGENTS.md` and
`02_Agent_Overlays/chatgpt-orchestrator.md`. Reaching additional external clients — ChatGPT
Actions first, a Microsoft 365 Copilot API plugin later — requires a hosted brokering
surface, because those clients cannot read this repository directly. That raises one question
before any code, manifest, or cloud resource exists: **does introducing a cloud runtime
create a new GitHub write authority?**

This ADR answers that question and nothing else. It adds no client, connector family,
manifest, OpenAPI surface, runtime behavior, or cloud resource, and authorizes no external
call, credential, or deployment. Issue #803 is relevant context: it retires the temporary
`agent-os-gateway` and requires that no issue, pull request, operator process, runbook, or
recovery procedure depend exclusively on it.

## Decision

A Cloud Run bridge, when later authorized and built, is an **execution substrate**, not an
Agent OS agent. Specifically:

- The bridge is an execution substrate, not an Agent OS agent.
- The bridge receives no row in `04_Registry/ownership-matrix.md`.
- The bridge executes provider calls on behalf of the authorized Agent OS role.
- The bridge does not independently authorize GitHub repository writes.
- GitHub Service Agent remains the only GitHub repository write authority.
- GitHub remains the authoritative audit record for repository changes.
- Cloud logs are supporting evidence only, never authority.
- The bridge must not depend on `agent-os-gateway`.
- The bridge attaches to the canonical provider line established through #802, #804, #805,
  and #806.

Repository changes requested through any external client continue to route through the
GitHub Change Request handoff in `03_Templates/prompts/github-change-request.md`, unchanged
by the existence of a cloud runtime.

## Non-Authority Statements

The bridge is not: an Agent OS agent; a GitHub write owner; a replacement for GitHub Service
Agent; an audit authority; a dependency on `agent-os-gateway`.

## Identity Boundary

The bridge separates caller identity, execution identity, Agent OS authority, provider
credential identity, and audit authority. A client request does not create Agent OS
authority. A Cloud Run execution identity does not create repository write ownership. A
provider credential authenticates the call but does not replace Agent OS authorization rules.
Provider systems remain authoritative for provider-side changes; Cloud logs are supporting
evidence only.

| Layer | GitHub | Google Drive | Notion |
|---|---|---|---|
| Caller identity | M365 user, ChatGPT user, or approved local runner | same | same |
| Execution identity | Cloud Run service account | Cloud Run service account | Cloud Run service account |
| Agent OS authority | GitHub Service Agent for repository writes | Integration Manager | Integration Manager |
| Provider credential | GitHub App installation token in production; short-lived fine-grained token for local read-only development only | per-user OAuth token | scoped Notion integration token |
| Audit authority | GitHub history, pull requests, issues, workflow runs, and exact SHA | Drive activity and file metadata | Notion page and database activity |
| Cloud logs | supporting execution evidence only | supporting execution evidence only | supporting execution evidence only |

Four distinctions follow, and are binding: request does not equal authority; execution does
not equal ownership; credential does not equal permission policy; Cloud logs do not equal
audit authority.

## Write Path Admissibility

Any later proposed write path must answer all six questions before it ships: who requested
it; what executes it; who authorizes it under Agent OS; what provider credential is used;
where the authoritative audit record lives; and what Cloud logs prove and do not prove. A
write path that cannot answer these does not ship.

## Rejected Alternatives

- Registering the bridge as a canonical agent with its own ownership row: rejected because it
  would create a second GitHub repository write authority and contradict `AGENTS.md`.
- Treating Cloud logs as the audit record: rejected because provider systems, not the
  execution substrate, remain authoritative for provider-side changes.
- Extending `agent-os-gateway`: rejected because #803 retires it and forbids exclusive
  dependence.

## Validation Expectations

- This ADR remains under the Markdown line limit.
- No runtime behavior, cloud resource, credential, or external call is introduced.
- `07_Agent_Tests/validate_registry_consistency.py` passes unmodified, with
  `04_Registry/ownership-matrix.md` still naming GitHub Service Agent as the single GitHub
  repository write owner.

## Version

0.1.0

## Changelog

- 0.1.0 accepted the cloud execution substrate identity and write-authority boundary.
