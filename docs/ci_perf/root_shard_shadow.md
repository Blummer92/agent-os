# Root shard shadow
This trial only runs on the dedicated owner-authored same-repository
`ci/root-shard-shadow-20261127` PR branch. It checks current pytest collection
before assigning whole tracked test files. Historical timings influence only
balance. The 2026-11-27 #4143 receipt supplied the eight historical weights.
Untimed/new modules receive a deterministic per-case weight.

Compare one full-root serial control and four isolated root jobs for the
same exact head, run and attempt. The serial job still checks independent
root completeness. Missing, unsuccessful or mismatched lanes do not produce
a passing parity result. Review provider setup, queue, collection, and join
times separately from the emitted pytest timings.

This trial does not run or validate package coverage, does not replace the
existing workflow, and is not a merge verdict. Before proposing any change
to required validation, benchmark the complete package and root workload on
the same revision, compare exact identities, skips and subtests, and require
independent completeness and coverage receipt parity. Keep five minutes as
the ceiling; three minutes is the stretch goal. No branch-setting changes
are part of this pilot.
