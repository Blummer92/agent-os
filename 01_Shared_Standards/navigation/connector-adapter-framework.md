# Connector Adapter Framework

## Purpose

Define the platform-independent contract every connector must satisfy to
participate in the Navigation Registry, Workspace Discovery Service, and future
read-only lookup tooling.

## Connector Lifecycle

```text
Registered -> Configured -> Validated -> Active -> Suspended
Active -> Deprecated -> Retired
Suspended -> Configured
Deprecated -> Active only with owner approval
```

Registered means the connector is known. Configured means required metadata and
auth model are declared. Validated means read, verification, and health behavior
pass checks. Active means it may support registry lookup. Suspended blocks use
until resolved. Deprecated allows migration only. Retired blocks future use.

## Connector Interface

Every connector must declare connector_id, connector_name, connector_version,
supported_resource_types, authentication_model, authorization_requirements,
verification_strategy, discovery_capabilities, lookup_capabilities,
relationship_capabilities, cache_capabilities, write_capabilities,
failure_modes, adapter_metadata, owner, source_of_truth mapping, and health
model.

## Discovery Interface

Conceptual methods are Discover Resources, Lookup Resource, Verify Resource,
List Relationships, Report Drift, Report Health, and Validate Permissions. The
framework defines required inputs and outputs only; it does not define code,
transport, API calls, Apps Script, Python, or implementation details.

## Resource Contract

Every discovered resource must provide stable identifier, display name, resource
type, parent, owner, permissions metadata, modification timestamp, verification
timestamp, source of truth, relationship metadata, cache metadata, connector id,
and evidence reference. Missing required fields produce lookup warnings, not
authority to write.

## Authentication Model

Supported models include read-only, read/write, service account, OAuth, API key,
and future approved models. Read/write capability does not grant write
authorization. Credentials are owned by the connected system owner or approved
service owner, not by the registry.

## Health Model

States are Healthy, Degraded, Unavailable, Authentication Failed, Permission
Limited, Maintenance, and Retired.

```text
Healthy -> Degraded -> Unavailable
Healthy -> Permission Limited
Healthy -> Authentication Failed
Any active state -> Maintenance
Maintenance -> Healthy or Degraded
Deprecated connector -> Retired
```

Unhealthy connectors may report evidence, but write-impacting actions remain
blocked until health and permission state are verified.

## Capability Matrix

Each connector must declare support level for Discovery, Lookup, Relationships,
Verification, Caching, Write Support, Drift Detection, and Health Reporting.
Support levels are none, read-only, partial, full, or future. Write Support must
name the owning approval path and may be none even when the platform supports
writes.

## Connector Validation

Before Active state, a connector must validate stable identifiers, metadata
normalization, permission reporting, health reporting, rate-limit behavior,
source-of-truth mapping, freshness window, drift reporting, and failure outputs.
Validation must prove the connector cannot convert lookup or discovery evidence
into write authorization.

## Error Contract

Standard errors are AuthenticationFailed, PermissionDenied, ResourceMissing,
ResourceMoved, RateLimited, SystemUnavailable, UnknownError,
ConnectorDeprecated, MetadataIncomplete, SourceOfTruthConflict,
DuplicateIdentifier, and VerificationFailed. Errors must include connector id,
resource id when available, severity, retryability, evidence, and recommended
owner.

## Security Model

Connectors are evidence providers, not authorities. Trust boundaries exist
between connector credentials, registry cache, live systems, and approval paths.
Audit records must include connector id, run id, timestamp, operation type,
resource id, permission scope, evidence reference, and disposition. Permission
inheritance must be reported, not inferred. Write authorization remains governed
by the system owner and existing Agent OS policy.

## Versioning

Connector versions describe platform-specific behavior. Adapter versions describe
compatibility with this framework and the Navigation Registry Data Model.
Backward-compatible changes may add optional metadata or capabilities. Breaking
changes require migration notes, owner approval, QA review, and a compatibility
matrix.

## Extension Model

Future connectors plug in by declaring the same lifecycle, interface, resource
contract, health model, error contract, security model, and versioning fields.
They may add adapter metadata, but must not change the Navigation Registry
Standard, Architecture, Data Model, or Workspace Discovery Service to become
compatible.

## Supported Connector Families

The framework supports Notion, Google Drive, GitHub, Gmail, Google Calendar,
Canvas LMS, Adobe, Figma, and future connectors through the same contract. Each
connector maps its native resources into the shared Resource Contract and
reports system-specific limits through adapter_metadata.

## Validation Against Navigation Registry

This framework is compatible with the Navigation Registry Standard because it
keeps connectors as lookup and evidence providers. It is compatible with the
Architecture because connector output supports discovery, relationship traversal,
live verification, drift reporting, and health checks. It is compatible with the
Data Model because all resource output normalizes to canonical entities and
fields. It is compatible with Workspace Discovery because the connector contract
supplies discovery, validation, health, permissions, and drift evidence.

## Version

0.1.0
