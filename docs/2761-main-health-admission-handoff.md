# #2761 — Main-health admission handoff to the host (#2340's domain)

## Decided semantics (owner decision, 2026-10-12)

When reusable exact-head candidate evidence says **admissible** but a newer
required current-main-health dependency is **pending or failing**, the admission
result is **`blocked`** (fail-closed). There is no repo merge path here;
`blocked` is terminal.

## What the repository provides

- `scripts/agent_os_remote_validation/validation_gate_currentness.py`
  - `classify_validation_gate_currentness(...)` — pure freshness classifier for
    a validation-gate run snapshot (wrapper vs. canonical check runs).
  - `compose_admission_with_main_health_currentness(*, candidate_admissible,
    main_health_currentness, main_health_failed)` — the decided mapping:
    - currentness not `CURRENT` → `BLOCKED` (pending, stale, or diverged
      health evidence is never treated as green);
    - `CURRENT` but health failed → `BLOCKED`;
    - `CURRENT` and health green → `CANDIDATE_VERDICT_STANDS` (the candidate
      verdict is preserved, never upgraded).
  - The composition verifies the currentness result's integrity and grants no
    merge, closure, workflow, protected-setting, production, or execution
    authority.
- Behavioral contract tests:
  `tests/agent_os_remote_validation/test_2761_main_health_admission_composition.py`
  (8 tests: pending → blocked, failing → blocked, green → stands, stale →
  blocked, diverged → blocked, never-upgrades, tamper-refused, strict types).
- The older `evaluate_final_validation_admission` seam
  (`scripts/agent_os_remote_validation/main_health_admission.py`) already
  blocks on projected main health; this handoff covers the *freshness*
  composition it does not perform.

## Host call-site (fresh binding before mutation — host-side)

The audit's "fresh binding before mutation" is enforced by the host, not the
repository. Before any mutation, the host (#2340's domain, currently
BLOCKED-EXTERNAL) must, at the decision boundary:

1. Reacquire the exact-head candidate evidence → `candidate_admissible`
   (True when the candidate would otherwise be admitted).
2. Reacquire the main-health gate snapshots **fresh** — the connector wrapper
   run observation **and** the canonical check-runs for exact-current main.
   Never inherit these from an earlier plan or cached read.
3. `classify_validation_gate_currentness(repository=..., pull_request=<gate
   run id>, reacquired_head_sha=<exact-current main SHA>,
   wrapper_run=<fresh wrapper snapshot>,
   canonical_check_runs=<fresh canonical check runs>)`.
4. Derive `main_health_failed` from the **same** evidence: True when any
   canonical check run (or the wrapper's terminal conclusion) carries a
   failure conclusion.
5. `compose_admission_with_main_health_currentness(
   candidate_admissible=..., main_health_currentness=<result from 3>,
   main_health_failed=<from 4>)`.
6. On `BLOCKED`: stop. Do not mutate, do not retry the same evidence, do not
   fall back to a cached health read. Reacquire and reclassify.
7. On `CANDIDATE_VERDICT_STANDS`: the candidate verdict governs — still
   subject to every other gate (the #2589 server-side required check, now
   live on ruleset 19123362; approvals; branch protection).

## Explicit non-goals

- No auto-merge path is defined or implied. `blocked` is terminal behavior.
- The repository never performs the fresh binding; it only classifies and
  composes caller-supplied evidence. A host that skips step 2 and reuses
  stale health evidence violates this contract even if it calls the
  composition function.
- Registration, packaging, or unit-test passage of these modules is not
  evidence of host enforcement (cf. the ChatGPT facade's live-consumption
  rule).

## Enforcement

- #2589: server-side required check `agent-os/authoritative-aggregate`
  (live on the `Protect main` ruleset) — the host-independent control.
- #3460: the consumer-side admission mapping.
- #2340: the host connector — BLOCKED-EXTERNAL; terminal gate for
  production-safe auto merging. Until the connector consumes admission,
  merging stays human-supervised per-PR.
