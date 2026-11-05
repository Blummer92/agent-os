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
if it failed. What is missing is only the durable record: the next
delivery of the same handoff will dispatch again (duplicate validation
work) until the store is fixed and a receipt is recorded.

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

- Probe passes → the failure was transient (a single record error, a
  momentary disk stall). No repair is needed; go to Step 3.
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

## Step 3 — re-deliver, then verify dedup

Re-deliver the same handoff. It will dispatch once and record its
receipt. Then deliver it once more: the second delivery must return
`blocked` with reason `invocation-already-completed` and
`scheduler_dispatch_count` 0. If the re-delivery reports
`completion-receipt-unrecorded` again, the store is still broken — go
back to Step 1.

Deliveries that ran while the store was broken may have duplicated
validation work. Check the evidence logs for repeated `completed` runs
for the same handoff with no intervening receipt; that is the expected
consequence of the outage, not a defect in the repair.

## Wrong or planted receipt

A receipt whose body does not match the admitted pilot input (repository,
issue, invocation, source SHA) makes the next delivery return
`needs-decision` with reason `completion-receipt-identity-conflict` —
fail closed, no dispatch. To recover:

1. Identify the file: `<store-root>/invocations/receipts/governed-resume-completed-<handoff-hex>.json`.
2. Read it and confirm the mismatch against the invocation descriptor.
3. Delete **that one file only**. Never delete the whole `receipts/`
   directory — that would erase other handoffs' completion records.
4. Re-deliver the handoff; it dispatches once and records a correct
   receipt.

## Wedged or corrupt claim

A claim file left by a crashed delivery
(`<store-root>/invocations/claims/governed-resume-claim-<handoff-hex>.json`)
is replaced automatically: the next delivery waits up to
`claim_wait_seconds` (default 5s) for the receipt, then replaces the
stale claim and dispatches. No manual action is needed.

If the claim file itself is corrupt (malformed JSON), the next delivery
returns `needs-decision` with reason `completion-claim-unavailable`.
Delete **that one claim file only** and re-deliver; the delivery
re-claims and proceeds. Never delete the whole `claims/` directory.
