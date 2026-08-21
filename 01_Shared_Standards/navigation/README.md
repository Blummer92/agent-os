# Navigation Shared Standards

## Purpose

This folder contains the Navigation Registry documentation stack. Read the
governing standard before implementation planning. Navigation is a shared
cross-system capability, not a canonical technical agent.

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
- GitHub Service Agent owns repository implementation of navigation code/governance.
- QA / Test Agent owns independent validation evidence.
- System owners retain live-system approval authority.
- Historical `Integration Manager` references resolve through the legacy alias registry and do not recreate an executable agent.

## Bounded Notion Intent Projection

`src/navigation_registry/connectors/notion_intent_context.py` projects already
normalized, live-read Notion evidence into a small immutable context. The
projection preserves source identity, source revision, bounded references, owner
/status/gate/blocker/next-step evidence, and explicit approval/scope-change stop
evidence. It is pure-local and relation-bounded; malformed/stale/conflicting
identity or bound violations fail closed.

Neither the projection, Navigation Registry evidence, nor Memory Manager context
authorizes writes, readiness, approval, implementation, merge, deployment, or
production action.

## Live Curriculum Evidence Orchestration

Existing curriculum evidence orchestration remains subordinate to the canonical
source-of-truth, cache, ownership, and write-authority rules in
`navigation-registry-standard.md`; this README does not redefine them.

## Version

0.2.0

## Changelog

- 0.2.0 replaces Integration Manager execution ownership with ChatGPT Orchestrator + shared Navigation capability routing (#1324).
- 0.1.0 initial navigation index.
