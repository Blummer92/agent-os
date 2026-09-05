# Authorized Validation Lifecycle Runbook (WSC-AUTO1F / #762)

Operator guide for `agent_os_execution_service.authorized_validation_entrypoint
.run_authorized_validation_lifecycle`. This is the single end-to-end entrypoint
for one authorized-validation run: #757 admission, #758 host-local lease,
#759 delegated cgroup v2 containment, #760 workspace-state evidence, and the
#761 unified lifecycle bundle/terminal result, composed exactly once.

This document explains what each terminal status means and what an operator
should (and should not) do about it. It does not re-document the lower-level
contracts -- see `08_Tooling/workflow-scheduler/docs/ARCHITECTURE.md` and the
module docstrings for #757-#761 themselves.

## Request schema compatibility

`AuthorizedValidationLifecycleRequest` keeps schema `1.0` as the default and
legacy read contract. A `1.0` request has the original exact field set and
retains the original request-identity calculation; it does not contain enough
immutable pre-runtime evidence for the later #1929 source-capture caller.

Schema `1.1` is opt-in. It adds only the canonical pre-PR
`ValidationEvidenceBundle` and a bounded, sorted, unique tuple of
`invalidation_events`. Both are non-authorizing evidence, both are covered by
the request identity, and the bundle must round-trip through its existing
canonical serializer/reconstructor. The carried bundle must also match the
already-bound runtime validation-bundle and validation-plan identities before
it can be exposed for later pilot reconstruction.

Deserializing either version never creates authority. Unknown versions,
version-specific field drift, malformed/tampered bundle evidence, or
noncanonical invalidation events fail closed. A malformed `1.1` payload cannot
fall back to `1.0` because each version has a separate exact field set.
`SingleIssuePilotInput` is never serialized or persisted by this request; the
later #1929 caller must reacquire current issue/repository/authorization truth
and rebuild that object in memory before invoking #1830.

## What runs, in order

1. **#757 admission** (`verify_authorized_validation_admission`) -- pure,
   no I/O. Re-verifies every identity and freshness check on the caller's
   `AuthorizedValidationLifecycleRequest`. Nothing below this line runs
   unless admission is `ACCEPTED`.
2. **#759 containment preflight** -- only if the runtime configuration
   names a `delegated_parent_cgroup`. Probes the cgroup v2 mount, `clone3()`
   support, and `cgroup.events`/`cgroup.kill` access, and creates/removes one
   disposable probe cgroup. Fails closed before any lease or worktree exists.
3. **#758 lease acquisition** -- only if the runtime configuration names a
   `lease_directory`; otherwise an in-process lease is used (single-process
   callers only, e.g. tests). Exactly one atomic acquire attempt.
4. **Worktree creation**, **#760 initial observation**, the **one authorized
   validation run** (inside the #759 invocation cgroup when configured),
   **#760 final observation**, **worktree cleanup**, **lease release** --
   all inside the one call to `run_concrete_runtime_entrypoint_with_validation_evidence`,
   in that fixed order, via the unmodified Workflow Scheduler lifecycle.
5. **#761 bundle + terminal result** -- assembled from exactly the evidence
   steps 1-4 produced. No status is invented above #761's own precedence
   table.

Every step above happens for **at most one** validation command set, on
**at most one** attempt each for lease/worktree/validation/cleanup/release.
There is no retry anywhere in this path.

## Terminal statuses and operator response

| Status | Meaning | Operator action |
|---|---|---|
| `succeeded` | Full conjunction proven: admission accepted, lease/workspace/cleanup/release all clean, validation passed, no unexpected changed paths. | None. Safe to proceed to whatever consumes this result. |
| `blocked` | Admission not (yet) authorized -- not approved, not GO, needs a human decision, or authorization not yet active. Zero side effects. | Resolve the blocking condition upstream (approval, execution-packet readiness). Do not retry this entrypoint until the input changes. |
| `stale` | Admission input drifted or the authorization window expired. Zero side effects. | Re-derive a fresh candidate packet / authorization and re-run. Never treat a stale admission as authorization to proceed. |
| `evidence_incomplete` | Either the admission input itself was invalid (identity/content check failed), or the accepted run produced incomplete/missing evidence (e.g. #759 preflight failed, or a runtime exception was caught inside composition). | Read `reason_codes` for the specific cause. A `#759 containment preflight failed` reason means the delegated cgroup is unusable on this host -- fix host cgroup delegation before retrying; do not fall back to an uncontained run for an invocation that was configured to require containment. |
| `validation_failed` | Everything else completed cleanly; the validation command(s) did not pass. | Inspect the retained `FrozenTestValidationResult` on the composition evidence. This is a real validation failure, not an infrastructure problem -- do not quarantine or force-cleanup. |
| `quarantined` | The pilot itself hit an unexpected/unclassified error. A `QuarantineEvidencePacket` is attached. | Manual review required. This is Workflow Scheduler's existing quarantine posture, unchanged by #762 -- see `quarantine_review.py`. |
| `termination_uncertain` | The executor or validation process's termination could not be directly confirmed (proc reaped, but not through the full observed-exit + drain path). | Manual review of the host for an orphaned process before reusing this workspace or lease. Never assume clean termination. Since #1202 the lease is also **withheld** on this path (`lease.release-withheld-unproven-termination`): it stays actively owned rather than becoming available while a process tree may still be alive. Clearing it requires the governed recovery below. |
| `cleanup_failed` | Worktree cleanup did not confirm both filesystem and metadata removal. | Manual worktree cleanup. Do not `git worktree remove --force` or `git clean` as a substitute -- that is exactly the destructive shortcut #758/#759/#760 are designed to avoid. |
| `release_failed` | Lease release did not confirm or was withheld (host-local: metadata mismatch, ambiguous state, or unproven termination). | Manual lease review under the configured `lease_directory`. Never delete the lease's `.active.json` file by hand to "unstick" it. Use `HostLocalLeaseAdapter.recover_orphaned_lease` (#1202), which requires the exact lease/holder/generation, the originating invocation, proven #759 containment termination, a resolved workspace disposition, and review evidence -- and performs zero mutation on any mismatch. |
| `timed_out` | The bounded validation run exceeded its timeout. | Distinct from `cancelled` -- if unexpected, check whether the configured timeout is realistic for this command set, not a retry loop. |
| `cancelled` | The caller's `CancellationProbe` fired before or during the run. | Expected under caller-initiated cancellation. No cleanup ambiguity implied by cancellation alone -- check the other evidence fields if in doubt. |

Precedence when more than one condition applies is fixed and owned entirely
by #761 (`POST_ADMISSION_TERMINAL_STATUS_PRECEDENCE`); #762 does not
re-order or override it.

## What this entrypoint deliberately never does

- Never retries a lease acquisition, a worktree operation, or a validation
  run. `automatic_retry` is fixed `False` throughout the #757-#761 chain.
- Never takes over, force-releases, or expires a lease. An ambiguous
  host-local lease state is always left for manual recovery.
- Never releases a lease on unproven termination. Once the executor or the
  validation adapter has been dispatched, teardown releases only when that lane
  proved terminal; otherwise exact ownership is retained (#1202). Recovery is an
  operator-invoked, evidence-bound call -- there is no age, TTL, heartbeat, or
  PID-absence path that frees a lease, and nothing recovers one automatically.
- Never force-removes a worktree, runs `git reset`/`git clean`/`git stash`,
  or otherwise mutates repository state outside the one authorized
  validation command set.
- Never falls back to an uncontained process run when `delegated_parent_cgroup`
  was configured. A #759 preflight failure fails the whole invocation closed.
- Never raises Scheduler concurrency above 1 or reaches any provider/queue
  API -- this entrypoint has no execution authority of its own; it only
  assembles evidence from adapters the caller supplied.

## Recovery checklist (any non-`succeeded` accepted-admission status)

1. Read `result.reason_codes` first -- every reason is namespaced
   (`admission.*`, `pilot.*`, `workspace.*`, `lease.*`, `runtime-*`) back to
   the layer that produced it.
2. If a `quarantine_packet` is present on the composition evidence, start
   there -- it already carries the redacted, bounded evidence for manual
   review.
3. Do not re-run the same `admission_request`/`pilot_input` pair expecting a
   different outcome -- every identity in this chain is content-addressed,
   so an unchanged input reproduces the same evidence deterministically
   (modulo host state like an already-held lease).
4. Fix the underlying condition (approval, host cgroup delegation, lease
   state, worktree state) out-of-band, then construct a fresh admission
   request/invocation for the retry -- never mutate and replay evidence
   objects in place.
