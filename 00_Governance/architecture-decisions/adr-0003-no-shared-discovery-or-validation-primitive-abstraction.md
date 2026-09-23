# ADR 0003: No Shared Discovery Core or Validation-Primitive Abstraction

## Status

Rejected.

This ADR records a decision **not** to build a set of proposed abstractions, so
future Agent OS work does not repeatedly rediscover the same surface similarity
and re-propose them. It is documentation-only: it adds no code, changes no
runtime behavior, and authorizes no repository, cloud, merge, or external write.

## Context

Three reviews were run against Agent OS (evidence verified against `main` at
`ae721f03d3b7a6255e400bb50b35c789f6037eee`):

1. a Discovery Abstraction Review of seven systems that share the vocabulary
   *discover / candidate / duplicate / provenance / collision*;
2. an Adversarial Validation Primitive Review of a proposed shared scalar-
   validation package (`require_exact_str` / `require_positive_int` /
   `require_sha40` / `require_sha256`);
3. a Naming and Structural Readability investigation.

The recurring pressure is to unify code that *looks* similar into a shared core.
The reviews measured whether unification reduces total complexity. It does not.

## Decision

Agent OS will **not** build any of the following. Each is rejected on measured
evidence, not taste.

### 1. A shared Discovery Core / `agent_os_discovery_primitives`

The word "duplicate" resolves **seven different ways** across the systems, at
seven call sites: abort the scan (`scripts/agent_os_issue_acceptance/issue_scanner.py`),
block adoption without collapsing (`scripts/agent_os_issue_acceptance/issueplan_scanner.py`),
withhold identity for manual review (`08_Tooling/visual-asset-intake/.../duplicates.py`),
classify as `DUPLICATE_ID` (`src/visual_asset_sync/reconcile.py`), two distinct
hard errors (`src/instructional_workflow_contracts/visual_asset_compatibility.py`,
`.../artifact_manifest.py`), and a legitimate multi-result set
(`08_Tooling/reusable-capability-registry/.../discovery.py`). A single package
must pick one meaning and be wrong at six. The total genuinely-shareable surface
was ~24 lines of 1–10-line expressions across four packages; replacing them costs
+130 to +230 lines net.

### 2. A generic `IdentityCollision` abstraction

The generic shape means *one identity, many items*. The visual-asset conflict
case is the **inverse** — one content hash, many identities
(`08_Tooling/visual-asset-intake/.../duplicates.py`) — which the generic object
cannot represent. Separately, `04_Registry/reusable-capabilities.yml` registers
`issue-batch-identity-collision-check` with the invariant *"never select a
canonical winner,"* which a `by_identity: Mapping[str, T]` would violate.

### 3. A universal `DiscoveryResult`

The registry's existing `DiscoveryResult`
(`08_Tooling/reusable-capability-registry/.../models.py`) is concrete, not
generic, and is a byte-stable serialized CLI contract guarded by an import-time
field-classification check in `provenance.py`. It shares only a *name* with the
proposed universal type; every field shape differs. Generalizing it is a breaking
schema change for two consumers.

### 4. A new shared validation-primitives package

The four proposed scalars are byte-identical across the two named consumers
(`scripts/agent_os_remote_validation/models.py`,
`08_Tooling/agent-os-execution-service/.../models.py`) but total ~24 duplicated
lines; extraction nets ≈ −3 production lines and +85 to +115 total
(tests + packaging). Both consumers already share one distribution boundary
(`08_Tooling/workflow-scheduler` already distributes `scripts.agent_os_remote_validation`;
execution-service already depends on `workflow-scheduler`), so no reachability
problem exists to solve. The one real finding underneath the proposal — a
tab/LF/CR divergence in the two `_validate_path` validators — is a convergence
bug handled as ordinary implementation, not an extraction.

## Consequences

- The seven systems stay separate. Each keeps its own collision, identity,
  bounds, provenance, and normalization semantics where the governing policy
  lives.
- No new package, abstraction, registry, dependency direction, or public concept
  is introduced (`new public concepts = 0`).
- Future agents encountering the shared vocabulary should read this ADR before
  proposing a discovery/validation core again.

## Reconsideration Triggers

Reopen only when **all** hold, with evidence:

1. a second real consumer exists with a concrete matching API — not a document,
   roadmap entry, or naming coincidence;
2. two systems agree on one collision meaning (both group, or both abort);
3. the shared implementation would delete more domain lines than it adds;
4. no governed invariant (e.g. "never select a canonical winner") is weakened.

Absent all four, this decision stands.
