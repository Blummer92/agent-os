# External Repository Governance

Version: 0.1.0
Contract issue: #580
Architecture decision: #579

## Purpose

This standard defines the canonical External Repository Governance (ERG) specification for repositories governed from Agent OS without copying Agent OS policy into consumer repositories. ERG is specification and evidence only. It does not authorize implementation, merge, deployment, production behavior, credentials, readiness changes, protected-setting changes, or external-system writes.

## Source-of-truth split

- Agent OS central registry owns admission, stable repository identity, lifecycle, profile path, admitted contract version, bounded aliases, tombstone facts, and routing metadata.
- This shared standard owns ERG policy, field meanings, result semantics, compatibility, lifecycle treatment, rollout, and rollback.
- A consumer-local profile owns only bounded repository-local governance-document declarations at the registry-declared profile path.
- Consumer code and repository behavior remain authoritative in the consumer repository on its canonical branch.
- Live runtime state remains authoritative in the runtime system; ERG makes no runtime, deployment, or production claim.
- Generated validation results are ephemeral evidence and must never be committed as registry/profile authority.

Central facts must not be repeated in a consumer profile. Consumer-local declarations must not be copied into navigation records as machine-readable authority.

## Contract identity

The initial consumer profile contract is:

    apiVersion: agent-os.external-repository-governance/v1alpha1
    kind: ExternalRepositoryProfile

The central registry contract is:

    apiVersion: agent-os.external-repository-governance-registry/v1alpha1
    kind: ExternalRepositoryRegistry

JSON Schemas are Draft 2020-12 and use stable Agent OS identifiers:

- `agent-os://external-repository-profile/v1alpha1`
- `agent-os://external-repository-registry/v1alpha1`

## Consumer profile

The v1alpha1 consumer profile deliberately exposes one local declaration surface: `governanceDocuments`, a bounded mapping from semantic document-role keys to repository-relative paths. This keeps the local contract small and prevents the profile from becoming a second policy, authorization, status, runtime, deployment, or credential store.

Consumer profiles must not contain central admission facts, repository identity, lifecycle state, contract admission state, routing owners, generated validation status, approval/readiness fields, deployment or production authorization, GitHub permissions, secrets, full Script IDs, executable commands, or arbitrary URLs.

Unknown top-level fields fail closed. Adding a new consumer-visible field or changing a field meaning requires a versioned contract change.

## Central registry

`04_Registry/external-repositories.yml` is the single central container for ERG repository admission records. Each admitted or historical record has one stable `registryId` and carries only central facts:

- canonical `repository` identity in `owner/name` form;
- `admission` state;
- `lifecycle` state;
- `profilePath`;
- admitted `contractVersion`;
- bounded routing metadata;
- optional bounded prior-name aliases;
- removal tombstone evidence when lifecycle is `removed`.

Routing metadata is non-authorizing. It identifies the owner to whom work should be routed; it never grants write, merge, deployment, production, approval, readiness, credential, or external-system authority.

The initial registry may contain zero repository records. ERG1 must not invent a consumer admission merely to populate the registry.

## Safe YAML and input bounds

ERG YAML is one UTF-8 document whose parsed value must fit the JSON data model. Implementations must fail closed on:

- duplicate mapping keys;
- aliases, anchors, merge keys, custom tags, directives, or multiple documents;
- non-string mapping keys;
- implicit timestamps, binary values, sexagesimal values, non-finite values, or floating-point values;
- unknown fields;
- unsupported `apiVersion` or `kind` values;
- input larger than 65,536 UTF-8 bytes;
- nesting deeper than 12 levels;
- more than 100 items in any collection;
- schema-specific strings beyond their declared maximum;
- unsafe repository-relative paths.

Comments may be accepted as non-semantic text. They never enter canonical identity.

## Safe repository-relative paths

A declared path must be relative to the repository root and remain inside that root after normalization and symlink resolution. Reject:

- absolute paths;
- `.` or `..` path segments;
- backslashes;
- repeated separators;
- NUL-bearing paths;
- paths that escape through symlinks.

ERG1 schemas encode lexical path constraints. ERG2 owns executable normalization, containment, symlink, duplicate-key, and strict-YAML validation.

## Result vocabulary

ERG uses the shared result vocabulary below. Results are evidence only.

- `pass`: every required control actually evaluated was satisfied.
- `warning`: a deterministic non-blocking concern exists within evaluated scope.
- `fail`: a deterministic contract or required-control violation exists.
- `manual-review`: evidence is valid but policy cannot decide safely and deterministically.
- `infrastructure-error`: trusted validation evidence could not be produced.

`infrastructure-error` must never be converted to `pass`, `warning`, or `fail`. Every report must identify evaluated and not-evaluated boundaries and must state that the result authorizes nothing.

## Compatibility

`apiVersion` changes whenever a consumer-visible field, requiredness rule, enum, path rule, field meaning, or result interpretation changes incompatibly. Because unknown fields fail closed, adding a profile field is also a compatibility event.

The current and immediately preceding admitted contracts receive at least 90 days and two Agent OS repository releases of support, whichever is longer. During overlap, validators may read both versions but must emit one explicit version-specific result and must never auto-rewrite a consumer profile.

Removal of a deprecated contract is allowed only after central registry evidence shows that no admitted consumer remains on it.

## Repository lifecycle

- Rename under the same owner requires an explicit central-registry update. A bounded old-name alias may be retained temporarily. Identity disagreement routes to warning/manual review until reconciled.
- Transfer to another owner fails closed to manual review and requires fresh admission plus human approval.
- Archive records remain in the registry with `lifecycle: archived`; validation cannot imply active support.
- Removal retains the stable registry ID as a tombstone with a reason and optional successor. Stable IDs are never reused.
- Unavailable or deleted repositories produce infrastructure/manual-review evidence; they are never auto-removed from the registry.

## Rollout and rollback

Rollout order remains `#579 -> #580 -> #581 -> #582 -> separately authorized consumer adoption -> #583`. ERG1 defines data/policy only. ERG2 owns offline validation. ERG3 owns the later pinned read-only reusable workflow. Enforcement requires a separate explicit issue after pilot evidence.

Rollback for ERG1 is an ordinary PR revert of the standard, schemas, registry container, fixtures, module-version entry, and changelog entry. ERG1 performs no consumer-repository or external-system mutation.

## Non-goals and stop conditions

ERG1 must not create a second schema-validation framework, config loader, result hierarchy, serializer, generic registry engine, repository adapter, workflow, credential path, deployment path, enforcement path, or external-system writer.

Stop and route for review if implementation would require a new generic infrastructure owner, a conflicting canonical owner, a material schema/authority decision inconsistent with #579, or any excluded surface outside the authorized #580 packet.

## Downstream handoff

#581 must consume these schemas and semantics rather than redefine them. #582 must consume #581's validator contract rather than create another validation path.
