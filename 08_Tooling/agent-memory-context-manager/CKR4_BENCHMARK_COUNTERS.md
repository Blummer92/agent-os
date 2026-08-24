# CKR4 Repeatable Benchmark Counters

Issue: #1388
Coordinates: #1146, #1384, PR #1385

## Purpose

This is offline measurement plumbing for the frozen CKR4 Hypothesis A/B/C benchmark. It does not alter coding-knowledge retrieval, CKR2 selection, CKR6 lesson preflight, Notion behavior, or the Memory Manager packet.

The canonical fixture is `tests/fixtures/ckr4_hypothesis_benchmark.json`. The corresponding test is `tests/test_ckr4_benchmark_counters.py`.

## Frozen tasks

The fixture preserves T1 through T10 from #1146 exactly once. Benchmark observations may reference one or more frozen task IDs but may not redefine their meaning.

## Counter semantics

A benchmark observation may record only directly observed values:

- retrieval path/escalation;
- Notion retrieval count;
- candidate count;
- selected count;
- irrelevant candidate count;
- full-page read count;
- workspace-search count;
- agent/retrieval step count;
- context token count;
- correctness and safety disposition;
- source-authority result.

`0` means the operation was observed and did not occur. `null` means unavailable/not directly observed. These values are not interchangeable.

## Reduction rule

A fractional reduction is calculated only when both compared values are measured and the baseline is non-zero:

`(before - after) / before`

If either value is unavailable or the baseline is zero, the reduction is unavailable. Do not estimate or substitute another metric.

Candidate-count reduction is not token reduction. Candidate-count reduction is not compute reduction. A 1 -> 1 retrieval-call comparison is 0% call reduction even when precision improves.

## Recorded CKR6A observation

The repository fixture records the observed positive C-path comparison from #1146:

- pre-tuning: filtered retrieval, 1 retrieval, 2 candidates, 1 selected, 1 irrelevant;
- post-tuning: known-reference retrieval, 1 retrieval, 1 candidate, 1 selected, 0 irrelevant.

Therefore the reproducible observed changes are:

- candidate load: 50% reduction;
- irrelevant candidates: 100% reduction;
- retrieval calls: 0% reduction;
- token/context reduction: unavailable;
- agent-step reduction: unavailable.

No broader efficiency or compute claim follows from these counters.

## Ownership boundary

#520 remains canonical for CI/build/validation compute measurement. CKR4 counters do not record CI queue time, workflow duration, install time, cache behavior, test execution duration, or build compute.

GitHub remains canonical for benchmark fixtures, executable tests, and acceptance evidence. Notion Lessons Learned remains advisory working knowledge.

## Architecture freeze

This benchmark surface introduces no new database, persistent telemetry store, connector, selector, retrieval engine, embeddings/vector system, agent, scheduler, workflow, packet schema, Notion mutation, or production behavior.
