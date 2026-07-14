# Navigation Registry Data Model

## Purpose

Define the canonical, platform-independent data contract for every Navigation
Registry implementation, connector, cache, adapter, and discovery service.

## Core Entities

| Entity | Primary id | Required fields | Unique constraint | Owner | Lifecycle |
|---|---|---|---|---|---|
| Registry Entry | registry_id | entity_type, system, canonical_id, display_name, owner, source_of_truth | registry_id | Integration Manager | entry_state |
| System | system_id | system_name, owner, auth_model, verification_method | system_id, system_name | Integration Manager | system_state |
| Database | registry_id | system, canonical_id, display_name, owner, parent_system | system+canonical_id | System owner | entry_state |
| Page | registry_id | system, canonical_id, display_name, parent, owner | system+canonical_id | System owner | entry_state |
| File | registry_id | system, canonical_id, display_name, mime_type, owner | system+canonical_id | System owner | entry_state |
| Folder | registry_id | system, canonical_id, display_name, owner, sharing_boundary | system+canonical_id | System owner | entry_state |
| Workflow | workflow_id | workflow_name, trigger, owner, steps, stop_conditions | workflow_id, workflow_name | Integration Manager | entry_state |
| Relationship | relationship_id | source_id, target_id, relationship_type, cardinality, owner | source+target+type | Integration Manager | relationship_state |
| Alias | alias_id | alias, canonical_target, scope, owner, human_review_required | scope+alias | Integration Manager | entry_state |
| Template | registry_id | system, canonical_id, display_name, template_type, owner, version | system+canonical_id | Template owner | entry_state |

Optional fields include description, tags, course, unit, audience,
freshness_window, duplicate_risk, deprecation_note, related_standards, and
notes.

## Field Catalog

| Field | Type | Required | Default | Validation | Update authority | Source of truth |
|---|---|---:|---|---|---|---|
| registry_id | string | yes | none | globally unique | Registry owner | Registry |
| entity_type | enum | yes | none | known entity | Registry owner | Registry |
| system | string | yes | none | known system_id | Integration Manager | Registry |
| canonical_id | string | yes | none | stable per system | System owner | Live system |
| display_name | string | yes | none | non-empty | System owner | Live system |
| aliases | list | no | empty | no duplicate in scope | Integration Manager | Registry |
| owner | string | yes | none | canonical owner | Registry owner | GitHub registry |
| source_of_truth | string | yes | none | approved system | Registry owner | GitHub governance |
| entry_state | enum | yes | Draft | valid transition | Registry owner | Registry |
| verification_state | enum | yes | Unverified | known state | System owner | Live verification |
| relationship_type | enum | relationship only | linked_to | known type | Integration Manager | Registry |
| cardinality | enum | relationship only | many-to-many | 1:1, 1:N, N:N | Integration Manager | Registry |
| cache_status | enum | yes | Unknown | known status | Cache owner | Cache |
| human_review_required | boolean | yes | false | true/false | Registry owner | Registry |
| write_allowed | boolean | yes | false | never grants auth alone | System owner | Live system |

## Relationship Types

Standard relationship types are contains, belongs_to, depends_on,
generated_from, references, linked_to, parent, child, template_for, and
derived_from. Relationships support one-to-one, one-to-many, and many-to-many.
Circular references are allowed only when the relationship type explicitly
permits mutual links; dependency cycles require human review.

## Lifecycle State Model

Valid entry states are Draft, Verified, Cached, Stale, Deprecated, Archived,
and Deleted.

```text
Draft -> Verified -> Cached -> Stale -> Verified
Draft -> Archived
Verified -> Deprecated -> Archived
Cached -> Deprecated -> Archived
Stale -> Archived
Archived -> Deleted
```

Deleted entries are retained only as tombstones when needed for audit, drift
recovery, or alias deprecation.

## Cache Metadata

Cache-only fields include last_refresh, freshness_window, drift_detected,
verification_timestamp, refresh_source, cache_version, cache_status, and
verification_state. These fields are never authoritative for live content,
approvals, readiness, ownership, sharing, permissions, grades, or source of
truth.

## Identifier Strategy

Notion pages and databases use Notion stable IDs. Google Drive files and folders
use Drive item IDs. GitHub repositories use owner/name plus repository ID when
available. GitHub files use repository, branch or ref, and path; governed files
should also track blob SHA when exact content matters. Templates and workflows
use registry-managed stable IDs.

Renames update display_name only. Moves update parent or path metadata but keep
canonical_id when the platform preserves identity. If a platform path is the only
identifier, the registry must retain previous paths as aliases or tombstones.

## Validation Matrix

| Condition | Required response |
|---|---|
| Duplicate alias in same scope | block automatic resolution; require review |
| Orphan relationship | mark invalid; route to owner |
| Missing owner | stop before action |
| Invalid source_of_truth | stop and request governance review |
| Invalid lifecycle transition | reject transition |
| Stale cache | verify live state before action |
| Circular dependency | require human review |
| Missing canonical_id | lookup warning only; no write action |
| Permission mismatch | stop and route to system owner |

## Extension Rules

Future systems extend the model through adapters, not new core entities. Each
adapter must define resource types, stable identifier format, verification
method, freshness window, write boundary, drift behavior, and owner mapping.
Adapter-specific fields live in an extension metadata object and must not change
core field meaning.

## Versioning

Schema versions use semantic versioning. Entity versions increment when required
fields, validation, or lifecycle behavior change. Registry entry versions change
on meaningful metadata updates. Relationship versions change when type,
cardinality, source, target, or confidence changes.

Backward-compatible additions may add optional fields. Breaking changes require
a new schema version, migration plan, QA review, and owner approval.

## Version

0.1.0
