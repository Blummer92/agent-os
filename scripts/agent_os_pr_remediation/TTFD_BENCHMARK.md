# AOS-TTFD-1 Phase 1 benchmark

AOS-TTFD-1 measures time and diagnostic actions from mission receipt to a confirmed, correctly classified, actionable defect. It is a thin extension of the existing CRH8A blinded historical code-review benchmark in `code_review_benchmark.py`; it does not create a second corpus, scorer ontology, scheduler, or telemetry service.

## Versions

- benchmark: `1.0.0`
- scorer: `1.0.0`
- Phase 1 case schema: `1.0.0`

## Frozen Phase 1 matrix

`TTFD-A02`, `TTFD-B01`, `TTFD-B02`, `TTFD-B05`, `TTFD-C01`, `TTFD-D01`, `TTFD-D02`, `TTFD-E02`, `TTFD-F01`, and `TTFD-G04`.

Canonical behavioral owners remain the existing repository contracts named by Issue #2230: validation supersession/duplicate-run guards, developer-validation semantics, bounded diagnostic rerouting/current-head reacquisition, tool-discovery continuation, side-defect handback, semantic recovery-progress detection, and deterministic PR branch reconciliation. Fixtures should cite those owners as hidden answer-key evidence rather than restating their behavior in a parallel policy layer.

## CRH8A reuse

Each `TTFDCase` contains the existing CRH8A `ReviewerPacket` and hidden `AnswerKey`. CRH8A therefore remains responsible for subject/answer separation, neutral case identity, packet fingerprints, leakage rejection, clean-control positive evidence, detectability/manual-review vocabulary, and bounded answer truth. AOS-TTFD adds only timeline, action-trace, conformance, and native-canary fields.

## Timeline

All run durations use monotonic elapsed seconds and require this exact order:

- T0 mission received
- T1 first authoritative evidence read begins
- T2 first correct defect hypothesis
- T3 defect confirmed by evidence
- T4 correct owner/next action identified
- T5 governed terminal disposition

Derived durations are TTFE, TTFH, TTCD (primary), TTAA, and TTTD. TTCD is bound to T3, never first suspicion.

## Diagnostic action telemetry

The bounded action vocabulary records authoritative/redundant reads, surface failures and alternate routes, stale-evidence attempts, duplicate-validation attempts, incorrect hypotheses, unnecessary user prompts, no-progress transitions, parent-mission resumptions, tool/capability discovery, subordinate mutations, and execution of the next admitted operation.

No chain-of-thought, hidden reasoning, unrestricted transcript, background polling, or external telemetry database is stored.

## D01/D02 native execution-interface canaries

Repository fixtures are necessary but cannot fully pass D01/D02 by themselves. A live run must separately record native-host conformance. Missing live evidence is `integration-evidence-incomplete`, not a fabricated pass.

A live run may be behaviorally eligible without an internal ChatGPT deployment/build identifier when its bounded observable trace establishes whether the next admitted operation executed or a genuine terminal blocker existed. Missing hidden runtime identity prevents exact runtime-version attribution; it does not erase otherwise sufficient behavioral evidence.

Comparability classes are:

1. `behaviorally-eligible`
2. `profile-comparable`
3. `runtime-exact-comparable`
4. `integration-evidence-incomplete`
5. `contaminated-or-ineligible`

Never infer native runtime identity from model name, date, client version, tool availability, conversation identity, or similar proxies.

### D01 canary

For an unfinished authorized bounded mission, successful tool/schema/capability discovery is intermediate. The same interaction must execute the next admitted operation unless a genuine terminal blocker is established.

### D02 canary

For an unfinished authorized parent mission, a non-blocking side-defect write is intermediate. Canonical parent state must be reacquired and a subsequent admitted parent operation must execute without another repository-owner prompt unless a genuine terminal blocker is established.

Canary observation must be passive: instrumentation cannot inject a continuation, retry, corrective prompt, destructive mutation, workflow/protected-setting change, credential/IAM change, production action, or unrelated external write merely to make a run pass.

## Scoring and repeated runs

Preserve component results rather than a vanity score: classification correctness, exact-head/evidence discipline, TTCD, diagnostic-action efficiency, continuation/premature-stop behavior, owner/next-action correctness, and false-positive avoidance.

Deterministic fixtures should be repeated at least five times per case/configuration. Latency/cross-surface fixtures should use at least ten independent runs when practical. D01/D02 require multiple fresh isolated native-host canaries. Run identity includes run number, packet fingerprint, model/reasoning setting, tool profile, baseline SHA, and fixture SHA so unstable outcomes remain visible rather than being averaged away.

Contaminated runs are ineligible. Materially different observable host/client/tool/model profiles belong in separate cohorts. Only `runtime-exact-comparable` cohorts may support exact build-to-build regression claims.

## Non-authority

Benchmark and score objects are evidence only. They never authorize execution, merge, issue closure, external writes, production actions, or protected-setting changes.
