# LP4 Implementation Handoff
This document is the separate implementation handoff that LP4 / #649 requires before any branch, code, test, or pull request exists.
`04_Registry/lp4-implementation-handoff.yaml` owns the machine-readable gates, contract sources, reuse map, file allowlist, validation commands, and conformance requirements; this file owns normative meaning.
The handoff is `prepared-not-authorized`. Preparing it grants nothing: LP4 stays `status:blocked` until every gate below is satisfied and the owning human authorizes the work.
Roadmap LP13 / #709 step 5 governs the sequence; CW1 / #654 owns the shared-mechanics boundary.
### gate-lp-contracts-merged
The LP3 and LP15 contract files must exist on `main` before LP4 begins. They currently live only on an unmerged branch, so the required `main` SHA is recorded as pending rather than guessed; naming a SHA that lacks the contracts would make the handoff false.
### gate-issue-text-corrected
The #649 body must be reconciled with the ratified contracts before authorization, because three of its stated requirements contradict them. An implementation built to the current text would be non-conforming on delivery.
### gate-cw5a-reason-namespace
CW5A must be able to accept LP-namespaced reason codes before LP4 can both reuse CW5A reason mechanics and emit LP15 reasons. Until this is resolved the two requirements are mutually unsatisfiable.
### gate-owner-authorization
The implementation owner must authorize this handoff explicitly. Issue text, roadmap position, and a prepared handoff are each insufficient on their own.
### source-lp3-handoff-contract
LP3 supplies the packet shape, fail-closed defaults, owner-state independence, the six diagnosis dimensions, and the adaptation hierarchy, at the exact contract version and record revision named in the registry.
### source-lp15-reason-catalog
LP15 supplies the finite `lp-*` semantic reasons LP4 may emit, with their triggers, required evidence, allowed result families, and prohibited implications.
### source-lp12-authority-registry
LP12 supplies advisory, routing, lifecycle, gate, compatibility, and non-authority vocabulary. LP4 selects values from it and never coins its own.
### source-issue-ratified-standards
LP1, LP2, LP5, LP10, LP11, and LP14 are ratified in their issue bodies with no repository file. LP4 consumes them by reference; the handoff records the issue and ratification date so a reviewer can locate the exact text.
### reuse-cw5a-public-surface
LP4 imports the named CW5A public symbols for JSON-compatible validation, recursive bounds, deterministic normalization, canonical serialization, fingerprints, stable identifiers and versions, shared result and reference models, immutable authority evidence, sanitized bounded details, and forbidden-import policy.
### reuse-no-second-core
LP4 must not copy, fork, vendor, or reimplement any mechanic CW5A already owns. A private helper that duplicates a public CW5A behaviour is a contract violation regardless of naming.
### reuse-interface-gap-handoff
Where CW5A cannot support an LP requirement, LP4 stops and produces a bounded interface-gap handoff naming the exact symbol, the exact requirement, and the smallest sufficient change. It never resolves the gap by building a competing core.
### scope-file-allowlist
LP4 touches only the files in the registry allowlist. Anything outside it, including registry admission and roadmap edits, is a separate authorization.
### scope-supplied-evidence-only
LP4 evaluates only supplied, bounded evidence admitted through the LP3 intake paths. It opens no artifact, invokes no extraction engine or model, and treats extraction confidence as evidence only.
### scope-pure-local-offline
LP4 is pure local, deterministic, offline, side-effect free, and report-only, and fails closed on malformed, contradictory, incomplete, unsupported, privacy-risk, or low-quality evidence.
### conformance-six-dimensions
LP4 reports the six LP3 diagnosis dimensions separately, under the exact registry field names. They are never summed, averaged, ranked, or collapsed into one task, class, or learner score.
### conformance-non-authority-fields
Every LP4 result carries the complete LP3 non-authority set with `report_only` true and every `*_authorized` flag false. The set is immutable evidence; no caller may raise a flag and no code path may omit one.
### conformance-fail-closed-defaults
An unpopulated or rejected evaluation returns the LP3 fail-closed defaults rather than an optimistic value or a silent omission.
### conformance-lp12-vocabulary
Advisory outcomes, routing recommendations, and gate states come from the LP12 registry. A missing owner decision resolves only to `NOT_EVALUATED`, and pacing feasibility never advances a gate.
### conformance-lp15-reasons-only
LP4 emits LP-specific reasons only from the LP15 catalog and surfaces generic mechanics reasons by reference. It defines no new reason identifier.
### validation-focused
The focused suite proves LP4's own domain behaviour and its adversarial fixture matrix at the exact final head.
### validation-reuse-and-import-isolation
A reuse and import-isolation check proves LP4 imports the CW5A public surface, imports nothing forbidden, and causes no import-time filesystem, environment, network, subprocess, registration, or logging side effect.
### validation-structural-and-aggregate
The repository structural check and the aggregate runner both pass, so LP4 cannot land while breaking line limits, registry consistency, or another suite.
### validation-exact-head-evidence
The final report distinguishes the branch head SHA tested locally, the pull-request synthetic-merge SHA tested by CI, workflow run identifiers and conclusions, and whether tests were rerun after the final change. `GITHUB_SHA` is never labelled as the branch head in a pull-request workflow.
### delivery-branch-and-draft-pr
LP4 delivers one focused Draft pull request from one branch, using only the allowlist, with the final report attached before review is requested.
### delivery-no-external-system
LP4 involves no external system, no network access, no credential, no model, and no real student data. Every fixture is synthetic.
