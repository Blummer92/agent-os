# ADR 0004: Hosted Bridge Runtime Non-Authority

## Status

Accepted.

This ADR defines the authority boundary for a future hosted external-client bridge
runtime. It is a repository governance decision only. It does not deploy a
runtime, select a vendor, create credentials, authorize tenant access, perform a
live call, or grant any external-system write authority.

## Context

Agent OS may later need a hosted runtime that receives requests from an external
client and routes bounded work toward existing Agent OS capabilities. Earlier
bridge exploration coupled runtime placement too closely to authority, named a
specific implementation path too early, and used retired ownership terminology.

Those concerns must remain separate:

- **runtime** is where code executes;
- **execution identity** is how that runtime authenticates to infrastructure;
- **credentials** are technical access material;
- **ownership** identifies the canonical Agent OS role responsible for a governed
  responsibility; and
- **authorization** is the explicit permission required for a particular write or
  protected action.

None of those concepts substitutes for another.

## Decision

### 1. Runtime is not authority

A hosted bridge runtime is an execution location, not an Agent OS authority
source. Running code in Cloud Run, another hosted compute product, or any future
runtime does not grant implementation, repository, merge, approval, production,
tenant, or external-write authority.

Cloud Run is one possible implementation of the abstraction. This ADR does not
select Cloud Run or any other provider/runtime as the required implementation.

### 2. Execution identity is not ownership

A service account, workload identity, API principal, process identity, or similar
execution identity proves only the identity used by an execution environment. It
does not become an Agent OS owner and does not inherit an agent's governed
responsibilities.

Architecture and cross-system routing remain owned by **ChatGPT Orchestrator**.
Repository implementation and GitHub repository writes remain owned by the
**GitHub Service Agent**. System-specific live-system owners and approval paths
remain unchanged.

### 3. Credentials are not authorization

Possession of an API key, OAuth token, service-account credential, delegated
identity, session, secret, or other authentication material does not authorize an
Agent OS action. Each write or protected action still requires the authorization
contract of the destination system and the applicable Agent OS governance.

This ADR deliberately selects no authentication mechanism, credential type,
secret store, tenant capability, delegated permission, or token format.

### 4. Logs are supporting evidence only

Runtime logs, traces, provider job records, and execution metadata may support
investigation and validation, but they are not canonical approval, readiness,
ownership, merge, source-of-truth, or authorization records unless a separately
governed contract explicitly says otherwise.

### 5. GitHub authority remains unchanged

The GitHub Service Agent remains the sole canonical Agent OS repository-write
owner. A bridge runtime must not create an independent GitHub write path, merge
path, issue-lifecycle authority, review authority, protected-setting authority, or
source-of-truth override.

Any future bridge call that would result in GitHub mutation must pass through the
existing GitHub Service Agent authorization and delivery contracts.

### 6. The bridge is provider-neutral and not gateway-exclusive

`hosted bridge runtime` is the governing abstraction. The implementation must not
be defined as exclusively attached to `agent-os-gateway`, and the architecture
must remain capable of using another bounded hosted execution substrate when
separately selected and authorized.

The Cloud Build provider line and the external-client bridge are separate
concepts. Existing Cloud Build validation/provider infrastructure does not become
the bridge merely because both may use hosted cloud execution.

### 7. Blocked Cloud work remains separate

Issue #806 (canonical Cloud Build provider activation and bounded live smoke
verification) remains separately blocked and separately authorized. This ADR does
not satisfy, bypass, or activate any of #806's Cloud, IAM, credential, or
production prerequisites.

Issue #803 (retirement of the temporary Cloud validation gateway) also remains
separately blocked. This ADR does not authorize retirement, decommissioning,
resource deletion, IAM removal, evidence deletion, or any other #803 action.

No bridge implementation should claim that this ADR attaches the bridge to
#802-#806 as an already-available execution path.

## Consequences

- Future external-client bridge work has one explicit authority boundary to cite.
- Runtime choice can evolve without transferring Agent OS ownership or write
  authority.
- Provider and authentication decisions remain deferred until a separately
  governed implementation issue needs them.
- External-client ingress can be designed independently from Navigation Registry
  resource connectors and independently from Cloud Build validation/provider
  infrastructure.
- A future runtime may collect bounded execution evidence, but such evidence
  remains non-authorizing unless another canonical contract deliberately consumes
  it.

## Non-Goals

This ADR does not:

- implement an external client;
- define an OpenAPI contract;
- create an MCP or plugin manifest;
- define a package skeleton;
- select Cloud Run, Cloud Build, or another runtime/provider;
- create or change credentials, secrets, OAuth, IAM, tenant permissions, or
  authentication methods;
- deploy cloud resources;
- change GitHub workflows, protected settings, merge policy, or issue lifecycle;
- call an external service;
- authorize production activity; or
- authorize any external-system write.

## Reconsideration Triggers

Revisit this ADR only if a future approved design requires a material change to
one of these boundaries: canonical Agent OS ownership, GitHub repository-write
authority, the separation between technical credentials and Agent OS
authorization, or the provider-neutral hosted-runtime abstraction.

A vendor, runtime, tenant, authentication, or deployment choice by itself does
not invalidate this ADR.

## Version

0.1.0

## Source

Issue #897.
