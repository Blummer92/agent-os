# Reusable Capability Registry Standard

## Purpose and boundary

The registry identifies reusable repository-local capabilities before new modules
are created. It is a discovery and governance aid, not write authorization,
runtime dependency injection, an exhaustive code catalog, or an executable-agent
registry.

## Canonical location and ownership

- Registry: `04_Registry/reusable-capabilities.yml`
- Contract/routing owner: ChatGPT Orchestrator, consuming this shared standard
- Validation support: QA / Test Agent
- Repository reader/tool implementation: GitHub Service Agent
- GitHub writes: GitHub Service Agent only, under approved handoff or Safe Implementation Lane scope

Legacy capability records may still contain retired agent names during migration
only when those names resolve through `04_Registry/legacy-agent-alias-registry.md`.
Such values are compatibility labels, not executable owners. New or materially
updated records must use current canonical agent names.

Existing source-of-truth and write rules remain governed by
`00_Governance/ownership-and-source-of-truth.md` and
`00_Governance/write-authorization-policy.md`.

## Record schema

Required fields: `capability_id`, `name`, `summary`, `status`, `canonical_paths`,
`public_interfaces`, `owner_agent`, `known_consumers`, `tests`, `keywords`,
`reuse_guidance`, `side_effects`.

Conditionally required: `deprecated_by` when status is `deprecated` or `replaced`.
Optional fields include `supporting_agents`, `inputs`, `outputs`,
`extension_points`, `invariants`, `failure_modes`, `compatibility`,
`documentation_handoff`, and `known_consumer_exemption`.

Allowed statuses: `active`, `experimental`, `deprecated`, `replaced`, `internal-only`.

## Identifier and interface rules

- `capability_id` is stable, lowercase kebab-case, unique, and never reused after retirement.
- `canonical_paths`, `tests`, and consumer evidence use repository-relative paths or explicit repository references.
- Each registered Python interface has one explicit canonical import path in `module.path:Symbol` form.
- Package re-export is preferred only where the package already treats that surface as public.
- Private helpers and speculative interfaces are not registered.

## Consumer tracking

`known_consumers` is a curated evidence list, not an automatically generated
dependency graph. At least one verified consumer is required unless
`known_consumer_exemption` records an approved reason.

## Admission and updates

A record may be admitted only when canonical paths, public interfaces, canonical
owner or active legacy alias, consumer evidence or exemption, tests, reuse
guidance, and side effects are verified. Updates require routing/owner review when
interfaces, lifecycle, compatibility, or ownership change.

## Deprecation and replacement

Deprecated and replaced records remain discoverable. They must explain migration
guidance and name `deprecated_by` when a successor exists. Capability IDs are
never silently reassigned.

## Validation severity

- Missing required fields, duplicate IDs, invalid status, missing canonical paths,
  or unresolved required owners are errors.
- A retired name that lacks an active legacy alias is an unresolved owner error.
- Missing or ambiguous interface, consumer, or test evidence requires manual review until deterministic static validation exists.
- Validation is report-only through the RC0 pilot and must not mutate registry or readiness state.
- Validators must not import arbitrary registered modules; targeted safe import tests are allowed only for intentionally exposed and already tested packages.

## Documentation and placement

Material implementation guidance belongs in the owning package or an approved
documentation handoff and must reference this standard. The registry remains one
YAML file until size, ownership boundaries, merge contention, or validation
complexity provides evidence that partitioning is safer.

## Versioning and change control

`registry_version` versions the registry format, not individual records. Contract
or schema changes follow `00_Governance/standards-change-control.md`, update
Global Engineering module references when required, and add a repository
changelog entry when required by policy.

## Prohibitions

No automatic registry mutation, network dependency, embeddings, external catalog,
issue mutation, readiness mutation, label mutation, production-system write, or
new executable technical agent is authorized by this standard.
