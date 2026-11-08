# Governed-resume receipt store — failure detection and recovery

This procedure covers the completion-receipt store
(`$AGENT_OS_CHECKPOINT_STORE_ROOT/invocations/receipts/` and the sibling
`claims/`). It is the operator runbook for the two store failures the
repair discloses: a receipt that could not be recorded, and a store that
cannot be written at all. The procedure is tested end-to-end by
`tests/test_governed_resume_receipt_recovery.py`, which follows these
steps literally against a temporary store.

## What a failure looks like

**A receipt was not recorded.** The delivery's evidence carries reason
`completion-receipt-unrecorded` and stderr carries:

```
governed-resume: completion receipt unrecorded for executor-handoff:<hex> (store <receipts-dir>): <error>
```

The run **completed** — do not report it as failed and do not re-run it as
if it failed. The execution claim is intentionally retained. Re-delivery
without a receipt returns `blocked` with `invocation-already-claimed`
and performs no duplicate validation, even after the store is repaired.
Recovery requires reconciliation against the original completed Pilot
evidence before a receipt can be reconstructed.

**The store cannot be written at all.** Binding fails before any
execution with `completion store is not writable: <store-root>` (raised as
`ProductionHostBootstrapError` from the bootstrap, converted by the
factory to `ProductionGovernedResumeFactoryError("production
governed-resume composition failed closed")`, and surfaced by the
entrypoint's `main()` as `RuntimeError("governed-resume requires
host-supplied #1218/#1253 composition; production host composition
failed closed")`). Nothing executed; nothing was misreported. Fix the
store, then re-deliver.

## Step 1 — confirm with the probe

Run the writability probe against the store root (the same probe the
bootstrap runs at binding time):

```python
python3 -c "from agent_os_execution_service.invocation_completion_receipt import InvocationCompletionStore; InvocationCompletionStore.for_store_root('<store-root>').verify_writable(); print('store writable')"
```

- Probe passes → the store is writable now. Do **not** retry a completed
  unreceipted run; go to Step 3 for evidence reconciliation.
- Probe raises `completion store is not writable` (or `checkpoint store
  is not initialized: invocations/ is missing`) → go to Step 2.

## Step 2 — fix the cause

Common causes, in the order to check them:

1. `receipts/` or `claims/` was replaced by a regular file (the most
   common breakage in tests): remove the file and recreate the directory
   (`mkdir -m 0700 <store-root>/invocations/receipts` and the same for
   `claims/`).
2. Permissions: both directories must be writable by the host user and
   `0700`. (`chmod 0700` the directories; do not widen them.)
3. Disk full or read-only mount: free space or remount writable, then
   re-run the probe.
4. `invocations/` itself is missing: the store was never initialized by
   Gate 5. Do not hand-create receipts — re-run the admission that
   initializes the store, then re-run the probe.

Re-run the probe after each fix. It must pass before any re-delivery.

## Step 3 — reconcile evidence, then verify dedup

Do not automatically retry the handoff solely because the store is writable.
A retained claim is not proof the Pilot is still running or that it
completed. Under an operator-controlled quiescent window, check the
Scheduler lease, workspace, original Pilot result, and termination/validation
evidence for this exact handoff. If outcome is uncertain, leave the claim
intact and escalate for a governed decision. A wait timeout is never proof
that a claim is stale.

If independently verified evidence proves the Pilot completed, construct the
canonical receipt with `build_completion_receipt(...)` using the exact
admitted Pilot identity and original result; do not invent IDs or validation
results. Persist it with `InvocationCompletionStore.record_completed(...)`
and read it back with `find_completed(...)`. Only after quiescing the
original owner and verifying the receipt may an operator release that one
claim with its observed run ID. Re-delivering must return `blocked`,
`invocation-already-completed`, dispatch count zero.

If evidence conclusively proves the Pilot never started or that an explicit
non-completed result was already returned, an operator may release only
that handoff's claim under a quiescent window, and then run a fresh
admission. Do not clear claims automatically, on a timeout, or just because
the checkpoint directory is writable.

## Wrong or planted receipt

A receipt whose body does not match the admitted pilot input (repository,
issue, invocation, source SHA) makes the next delivery return
`needs-decision` with reason `completion-receipt-identity-conflict` —
fail closed, no dispatch. To recover:

1. Identify the file: `<store-root>/invocations/receipts/governed-resume-completed-<handoff-hex>.json`.
2. Read it and confirm the mismatch against the invocation descriptor.
3. Confirm with independent execution evidence whether any Pilot work
   completed for this identity. If completion is possible or uncertain,
   do **not** delete-and-retry; reconcile or escalate.
4. Only when evidence proves the receipt is invalid and no completed
   dispatch could be duplicated, remove that one file under a quiescent
   window. Never delete the entire `receipts/` directory.

## Wedged or corrupt claim

A claim file left by a crash
(`<store-root>/invocations/claims/governed-resume-claim-<handoff-hex>.json`)
is **not** automatically replaced. A timeout without a receipt is
ambiguous: the owner may still be running or its receipt write may have
stalled. A later delivery returns `blocked` /
`invocation-already-claimed` without dispatching. Follow Step 3 to
reconcile the original work before any release.

A malformed claim reports `needs-decision` /
`completion-claim-unavailable`. Do not delete it while an owner may
still be active. Investigate the underlying corruption and independently
prove that no ongoing or completed Pilot can be duplicated. Only then,
under a quiescent window, remove **that one file only** and re-admit.
Never delete the whole `claims/` directory.
