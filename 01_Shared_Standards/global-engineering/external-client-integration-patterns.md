# External-Client Integration Patterns

## Purpose

Define provider-neutral patterns for external clients that exchange requests and
results with Agent OS without turning the client, transport, runtime, identity, or
credentials into an Agent OS authority.

This standard complements
`00_Governance/architecture-decisions/adr-0004-hosted-bridge-runtime-non-authority.md`.
It does not select a provider, runtime, tenant, protocol, authentication
mechanism, credential type, deployment model, or client product.

## Scope Boundary

An external-client integration is an ingress/egress boundary for a client that is
not itself the Agent OS source of truth. It may carry a bounded request into Agent
OS and return bounded result evidence to the client.

External-client integration is distinct from the Navigation Registry connector
framework:

- external-client integration carries a request/result exchange across an Agent
  OS boundary;
- Navigation Registry connectors discover, look up, verify, and describe
  resources for governed navigation and evidence;
- an external client does not become a Navigation Registry resource connector
  merely because it can call Agent OS; and
- a resource connector does not become an external-client ingress merely because
  it uses an API, MCP, plugin, or hosted transport.

If one implementation needs both roles, each role must satisfy its own canonical
contract independently.

## Canonical Pattern

A provider-neutral external-client integration has five logical stages:

1. **Client request** — the client supplies a bounded request plus the minimum
   identity, correlation, and context required by the selected Agent OS
   capability.
2. **Ingress normalization** — the integration validates the request shape and
   converts provider-specific transport details into a provider-neutral request
   envelope. Normalization creates no authority.
3. **Agent OS routing** — ChatGPT Orchestrator resolves the governed owner,
   standards, source-of-truth boundary, authorization requirements, and stop
   conditions. The external client does not choose or impersonate an Agent OS
   owner.
4. **Capability execution** — the selected canonical owner or capability executes
   only actions independently admitted by its existing contract. Repository
   writes remain with GitHub Service Agent; live-system writes remain with their
   existing system owner and authorization path.
5. **Result projection** — the integration returns bounded result/evidence to the
   client without promoting runtime logs, provider metadata, or client state into
   canonical Agent OS state.

These stages are logical responsibilities, not a required deployment topology.
They may run in one process or several processes when a separately governed
implementation selects a runtime.

## Request Envelope

A future implementation should preserve, when applicable:

- request identity or correlation identity;
- requested operation or capability;
- bounded user-supplied inputs;
- source references needed to reacquire canonical evidence;
- provider/client provenance;
- requested output form; and
- explicit constraints or stop conditions supplied by the caller.

The envelope must not encode credentials as authorization, assign an unregistered
Agent OS owner, override canonical source-of-truth records, or convert a client
request into approval/readiness/write authority.

Provider-specific fields may exist at the transport edge, but the governed Agent
OS handoff should depend on semantic fields rather than vendor-specific product,
tenant, token, or deployment vocabulary unless a later implementation contract
explicitly requires them.

## Result Envelope

A future implementation should return only the bounded evidence needed by the
client, such as:

- request/correlation identity;
- operation or capability identity;
- outcome or finite failure classification;
- result payload or artifact reference when authorized and available;
- provenance and canonical evidence references;
- manual-review or stop reasons; and
- retryability only when the owning capability can state it safely.

A result is evidence, not authorization. A successful response does not by itself
authorize a later write, merge, approval, readiness transition, deployment, or
other protected action.

## Authority And Identity

The following remain separate:

- **client identity** identifies the external caller;
- **transport identity** identifies the channel or integration endpoint;
- **runtime identity** identifies the execution environment;
- **provider credentials** permit technical authentication to a provider;
- **Agent OS ownership** comes from the canonical registry; and
- **authorization** comes from the governing contract for the exact action.

No identity or credential may substitute for Agent OS ownership or authorization.

GitHub repository mutations continue to route through GitHub Service Agent. An
external-client bridge must not create an independent repository-write, merge,
issue-lifecycle, review, or protected-setting authority.

## Source Of Truth And Currentness

External-client state is not a replacement source of truth. The integration
should carry references sufficient for the selected capability to reacquire the
canonical source when currentness matters.

Cached client context, provider metadata, runtime state, request history, and
bridge logs are supporting evidence only. If they conflict with the canonical
source, the canonical source controls and the operation must follow the owning
capability's existing stale/conflict behavior.

## Failure And Manual Review

The boundary must fail closed when it cannot prove the minimum facts required by
the selected capability. Provider-neutral failure classes should distinguish at
least:

- invalid or unsupported request;
- unresolved capability or owner;
- missing or stale canonical evidence;
- authorization required;
- provider/runtime unavailable;
- external operation not permitted;
- ambiguous or conflicting evidence; and
- manual review required.

A transport or provider error must not be reclassified as approval, success, or
permission to use a different write path.

## Observability And Evidence

Correlation identifiers, bounded request/result metadata, and runtime/provider
logs may support diagnosis and audit. They remain supporting evidence under ADR
0004 and must not become canonical approval, readiness, ownership, merge,
source-of-truth, or authorization records unless another governed contract
explicitly adopts them.

Implementations should avoid placing secrets or unnecessary private content in
logs or result envelopes and should preserve the destination system's own
privacy, credential, and audit requirements.

## Compatibility And Extension

A provider-specific client or transport may implement this standard without
changing the standard when it preserves the semantic request/result boundary and
all authority rules.

A future implementation may choose HTTP/OpenAPI, MCP, a plugin mechanism, a
message transport, or another protocol. That choice belongs to its own bounded
implementation decision and does not change this standard by itself.

A material change to ownership, authorization, source-of-truth behavior, or the
separation from Navigation Registry resource connectors requires governance
review rather than a provider-specific extension.

## Non-Goals

This standard does not:

- select Microsoft, Google, OpenAI, Anthropic, or another vendor/client;
- select Cloud Run, Cloud Build, a gateway, or another runtime;
- define an OpenAPI specification, MCP manifest, plugin manifest, or package;
- choose OAuth, service accounts, API keys, tokens, tenants, or credential
  storage;
- create or modify a Navigation Registry connector;
- deploy infrastructure or activate production traffic;
- create a GitHub workflow or protected-setting change;
- grant repository, tenant, production, or external-system write authority; or
- authorize a live external call.

## Version

0.1.0

## Source

Issue #898.
