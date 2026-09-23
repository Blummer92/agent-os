# Worker Assignment And Lease Lifecycle

## Purpose

This note documents the Phase 2 worker assignment and lease behavior for #157.
It makes dry-run worker ownership explicit without introducing a real worker pool.

## Boundary

Worker leases are in-memory `ProjectJob` state inside the simulation model. This
slice does not create branches, execute issue-to-PR work, perform autonomous
coding, merge pull requests, implement distributed locking, or write to external
systems.

## Behavior

- Worker IDs must be non-empty strings.
- `claim_job()` and `claim_next()` use the ready-job path before assigning work.
- Active leases are visible through `lease_state()` and `worker_assignments()`.
- A leased job cannot be claimed by a second worker.
- Blocked and governance-blocked jobs cannot be claimed.
- `release_lease()` allows only the owning worker to release a lease.
- Released running jobs return to `READY` for deterministic dry-run reassignment.
- Project Manager release uses the same lease path.
- Workers still cannot mark jobs merged.

## Deferred

Lease expiry is intentionally deferred. Adding time-based expiry now would imply
scheduler timing and distributed-locking behavior beyond this slice.

## Smoke Tests

Smoke tests cover worker claims, duplicate-claim prevention, blocked and
governance-blocked assignment, lease release, reclaim after release, non-owner
release rejection, blank worker IDs, Project Manager assignment, and zero external
writes.

## Next Step

After #157 merges, the next issue should be #158: Validation queue and
review-readiness states.
