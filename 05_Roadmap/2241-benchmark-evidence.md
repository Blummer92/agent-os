# #2241 Benchmark Evidence

Status: evidence collection in progress.

## Purpose

This record binds the remaining acceptance evidence for #2241 to a visible current pull-request lineage without duplicating the already-landed workflow implementation from PR #2229.

Canonical implementation:
- PR #2229
- implementation head `a6ba8b6907e7afdefacb5cf51b4d7559506ecfc3`
- merged commit `fa90c85d370f969a1525cbf72985199c23aa1891`

## Preserved contract

The current implementation removes the scheduling-only `needs: plan` edge while preserving focused validation, draft deferral, final-candidate admission, exact-head identity verification, and the single authoritative aggregate gate. The structural workflow regression remains the executable contract for the absence of the edge.

## Exact-head validation evidence

Implementation-head workflow run `34394646079` completed successfully. Both `Run validation plan` and `Run aggregate validation` succeeded for exact head `a6ba8b6907e7afdefacb5cf51b4d7559506ecfc3`.

The validation-plan log reports canonical profile `aggregate` for that exact head.

## Focused-profile reference

Run `34349243603` is the canonical focused-profile reference already named by #2241/#520. Its focused validation plan and authoritative aggregate both completed successfully. It remains baseline/reference evidence; it is not silently reclassified as a post-change sample.

## Post-change sample admission

Only Ready runs that are exact-head, non-draft, non-cancelled/non-superseded, and comparable under #520's benchmark fields may enter the post-change sample. Draft-deferred or skipped aggregate runs are excluded. Failed unrelated aggregate runs are not counted as successful samples.

## Remaining benchmark acceptance

Acceptance criterion 7 still requires a complete comparable sample of at least:
- 5 aggregate-profile Ready runs; and
- 2 focused-profile Ready runs.

For the completed sample, report baseline/post-change median and p90 where supported, observed run count, wall-clock savings, compute impact, preserved validation lanes, and coverage-neutral classification. Coordinate focused-profile finalization with #2200 as required by #2241.

This evidence-only PR does not change workflow topology, validation coverage, required-check identity, branch protection, or production behavior.
