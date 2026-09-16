# Navigation Shared Standards

## Purpose

This folder contains the Version 0.9 Navigation Registry documentation stack.
Read these files in order before implementation planning. Navigation remains a
shared cross-system capability, not a separate canonical technical agent.

## Document Order

1. `navigation-registry-standard.md` — governing standard and boundaries.
2. `navigation-registry-architecture.md` — component flow and workflows.
3. `navigation-registry-data-model.md` — canonical entities, fields, and states.
4. `connector-adapter-framework.md` — connector interface contract.
5. `workspace-discovery-service.md` — discovery and repair recommendations.

## Canonical Authority Map

| Topic | Authoritative file |
|---|---|
| Source of truth | `navigation-registry-standard.md` |
| Write boundary | `navigation-registry-standard.md` |
| Registry routing ownership | `navigation-registry-standard.md` and `04_Registry/responsibility-matrix.md` |
| Component workflow | `navigation-registry-architecture.md` |
| Cache lifecycle | `navigation-registry-architecture.md` |
| Entities and fields | `navigation-registry-data-model.md` |
| Lifecycle states | `navigation-registry-data-model.md` |
| Validation rules | `navigation-registry-data-model.md` |
| Connector interface | `connector-adapter-framework.md` |
| Connector health and errors | `connector-adapter-framework.md` |
| Discovery workflow | `workspace-discovery-service.md` |
| Drift and repair recommendations | `workspace-discovery-service.md` |

## Conformance Rules

Implementation work must preserve these rules:

- The Navigation Registry is a lookup layer, not a source of truth.
- Cached records never authorize writes or governed-field changes.
- Live systems remain authoritative for their own resources.
- Connector output is evidence, not authority.
- Discovery recommends changes; it does not change live systems by default.
- ChatGPT Orchestrator owns cross-system navigation routing by consuming the shared standard.
- GitHub Service Agent owns repository implementation of navigation code and governance.
- QA / Test Agent owns independent validation evidence.
- System owners retain live-system approval authority.
- Historical `Integration Manager` references resolve through the legacy alias registry and do not recreate an executable agent.

## Bounded Notion Intent Projection

`src/navigation_registry/connectors/notion_intent_context.py` projects already
normalized, live-read Notion page evidence into a small immutable context for
Tasks/Issues, Decision Log/ADRs, Lessons Learned, and Reusable Patterns. The
projection preserves Data Source identity separately from database-container
identity, source revision, bounded references, owner/status/gate/blocker/next
step evidence, and explicit approval/scope-change stop evidence.

The projection is pure-local and relation-bounded. Callers resolve known records
and explicit relations before any search; incomplete relations may request one
bounded continuation step, never a recursive graph crawl. Missing canonical
identity, stale/non-live evidence, conflicting identity, wrong types, or bound
violations fail closed. Unknown additive metadata is ignored.

The Memory Manager seam stays unchanged: the projection exposes only existing
`objective`, `known_facts`, `prior_decisions`, and `stop_conditions` concepts.
Fingerprints are deterministic equality evidence only. Neither the projection,
Navigation Registry evidence, nor Memory Manager context authorizes writes,
readiness, approval, implementation, merge, deployment, or production action.

## Live Curriculum Evidence Orchestration

`src/navigation_registry/connectors/curriculum_evidence_orchestrator.py` consumes
already-resolved intent and canonical unit identity, then plans request-sensitive
reads through injected existing identity and read seams. Read plans are minimal by
request class, and Visual Asset Library lookup is relation-first by `Canonical
Unit`; provider-specific compact Notion IDs stay inside the provider/read seam.

The orchestrator normalizes bounded owner/asset evidence for the #975 assembler,
which then feeds the #973 current-state resolver. Malformed identity metadata,
provider failure states, aggregate handoff overflow, and malformed asset approval
booleans fail closed; relative-time requests do not invent current-day context.

For source-of-truth, cache, ownership, and write-authority rules, inherit the
canonical `navigation-registry-standard.md`; this README does not redefine them.

## Curriculum Execution-Surface Routing

`src/navigation_registry/connectors/curriculum_execution_surface_router.py`
provides the single governed Agent OS read seam for bounded curriculum and visual-
asset reads. Agent OS no longer models the native/direct ChatGPT Notion connector
as an execution route. ChatGPT and other Agent OS callers reach Notion through the
GitHub-controlled #2283 path, which injects bounded read-only Scheduler tasks for
the canonical `NotionReadOnlyAdapter` path.

This single-seam rule does not make Notion the transport for every provider and
does not prohibit future Google Drive reads. A separately governed Drive read
adapter may be added as a sibling provider behind the same Agent OS request,
admission, evidence, and source-of-truth boundaries. Provider-specific credentials
and actions remain isolated, and read capability never implies write authority.
Drive, Docs, Slides, or Classroom mutation remains separately authorized under
the applicable Google Workspace write contracts.

The router re-plans nothing. Request sensitivity, relation-first Visual Asset
Library lookup by `Canonical Unit`, provider-id hiding, owner/asset
classification, currentness, provenance, approved-use/reuse/human-review
evidence, and every non-authority boundary stay owned by the existing
orchestration, assembler, and resolver. Only `get_page` and `query_data_source`
may reach the current Notion Scheduler seam; any other Notion action, a missing
class source binding, an out-of-bound result request, a malformed Scheduler
envelope, or any non-success Scheduler state fails closed rather than assembling
partial evidence.

Consistent with the connector boundary above, the router never imports the
Workflow Scheduler: the Scheduler remains the canonical live-read executor and is
injected. Providing a live executor, its credentials, and its Notion source
sharing is a separate excluded-surface decision and is not granted here. The
existing `agent-os-notion-reader` route value is retained as evidence-format
compatibility; it no longer means "fallback from a native connector."

## V1 Cleanup Notes

Before declaring Version 1.0, QA should decide whether long files must be split.
If splitting is required, keep this README as the index and move detailed tables
into companion files without changing the canonical authority map.

## Version

0.4.0

## Changelog

- 0.4.0 removes native/direct ChatGPT Notion connector routing, documents the GitHub-controlled Agent OS reader as the single current Notion execution path, and preserves a provider-neutral boundary for separately governed sibling reads such as future Google Drive access without granting Drive write authority (#2303).
- 0.3.0 documented the former dual execution-surface routing introduced by #2282.
- 0.2.0 preserves the detailed Navigation Registry contracts while replacing Integration Manager execution ownership with ChatGPT Orchestrator + shared Navigation capability routing (#1324).
- 0.1.0 initial navigation index.
