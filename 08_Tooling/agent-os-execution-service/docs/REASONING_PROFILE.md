# Provider-Neutral Task Reasoning Profile — #3336 (AN-MR1)

## Purpose

Freeze the smallest provider-neutral representation answering **"What reasoning capability does
this task require?"** independently of "Which model/provider should execute it?" and "Which execution
surface can satisfy it?" This is a pure classification/evidence contract, not a new agent, router,
runner, Scheduler, queue, state store, model registry, authorization system, or hidden-reasoning
representation.

```text
governed task evidence
-> TaskReasoningProfile            (what reasoning capability is required)
-> #3337 model x reasoning evaluation evidence   (separate mapping territory)
-> #918 executor routing           (which surface can satisfy it)
-> #1419 compute admission         (whether compute should be spent)
-> existing authorization/currentness owners     (whether work may proceed)
```

## Canonical owner map

| Concern | Canonical owner | Reasoning-profile treatment |
|---|---|---|
| semantic contract | ChatGPT Orchestrator (#3336) | owns this vocabulary's meaning; repository implementation is GitHub Service Agent-owned, validation QA / Test Agent-owned |
| work-operation vocabulary | #2318 `CodingWorkerOperation` | referenced by import as optional `work_operation_or_none`; never redefined |
| PR-finding compute routing | #878 `scripts/agent_os_pr_remediation/planning.py` | `COMPUTE_ROUTES` stays PR-specific; `project_pr_compute_route()` is an explicit one-way consumer-side projection, not a second definition |
| execution surface / runtime capabilities | #918 executor routing | profile never routes; context requirements name *information*, never runtime capabilities |
| compute spending | #1419 compute admission | profile never admits compute |
| model x reasoning evidence | #3337 (evaluation harness) | consumes profiles as fixture semantics; provider mappings stay mappings |
| recorded provider settings | #2744, #1675 `BenchmarkRun` | record what was *used*; the profile classifies what a task *requires* |
| observation mechanics | #1504 `experiment_evidence.py` | reused by #3337 as the observation carrier, not the semantics |

## Profile boundary

`TaskReasoningProfile` carries only:

- stable task identity and one finite task class;
- optional #2318 work-operation reference (coding tasks only);
- one finite reasoning-effort requirement;
- semantic-ambiguity flag, risk level (low/medium/high), capability and context requirements;
- manual-review requirement with its reason (human-owned regardless of model strength);
- reasons, evidence references, and a canonical `profiled_at` timestamp (the currentness basis);
- authority flags fixed `false`.

It deliberately does **not** contain model names, provider names, provider settings, execution
routes, queues, Schedulers, state, prompts, credentials, token settings, lifecycle decisions, or
positive authority fields. Reconstruction rejects unknown fields, so provider dependence cannot enter
through the wire format.

## Task-class vocabulary

- `extract` — pull structured facts from supplied evidence
- `classify` — assign bounded labels/vocabularies to supplied inputs
- `triage` — route/classify with a disposition under uncertainty
- `implement` — produce a change from a specified design
- `debug` — locate a cause from failure evidence
- `architecture` — design structure under competing constraints
- `adversarial-review` — find flaws the author missed
- `decision-support` — synthesize a recommendation with trade-offs

These describe the task's cognitive character. #2318 operations describe the requested work operation.
An `implement` operation on a trivial rename and an `implement` operation on an architecture migration
share the operation and differ in profile.

## Reasoning-effort vocabulary

- `none` — mechanical/deterministic; no model reasoning required
- `low` — single-step shallow inference over supplied context
- `medium` — multi-step reasoning over bounded context
- `high` — multi-hop reasoning with ambiguity resolution and trade-offs
- `maximum` — open-ended architecture/adversarial reasoning under deep uncertainty

Each level is a **requestable capability requirement**, not a hidden-reasoning trace. No level names a
model, provider, or setting. Which provider satisfies a level is #3337/#3338 mapping territory, never
canonical semantics.

## Capability and context vocabularies

`ReasoningCapability`: `single-step-inference`, `multi-step-inference`, `ambiguity-resolution`,
`trade-off-synthesis`, `adversarial-analysis`, `causal-diagnosis`, `architectural-design`.

`ReasoningContextRequirement`: `task-evidence`, `repository-context`, `historical-precedent`,
`live-system-state`. These name information the reasoning needs. Runtime tools (test execution,
checkout, containment) remain #918 `ExecutorCapability` territory.

## PR compute-route projection

`project_pr_compute_route()` maps the PR-remediation policy output into profile vocabulary:

| PR compute route | Effort | Manual review |
|---|---|---|
| `no-model` | `none` | no |
| `small-model-eligible` | `low` | no |
| `high-reasoning-required` | `high` | no |
| `manual-decision-required` | *(unspecified)* | **yes** |

The mapping is deliberately lossy: `small-model-eligible` is a provider-selection statement and
projects to `low` as a requirement statement without claiming which model satisfies it;
`manual-decision-required` specifies no machine-side effort, so effort stays `None` and the
manual-review flag carries the invariant. Unknown routes fail closed. This documents the reuse
relationship so the PR vocabulary is never silently universalized.

## Invariants

- `semantic_ambiguity=True` forces `reasoning_effort != none` (fail closed): ambiguous evidence
  cannot be resolved with no reasoning.
- `manual_review_required=True` requires a reason and permits any effort: the decision stays
  human-owned regardless of model strength.
- `profile_id` is a deterministic digest of the classified content including the evidence
  references: a stale or tampered evidence basis cannot silently reuse a profile identity.
- `profiled_at` is a canonical UTC timestamp supplied by the classifier (never read from a clock
  inside the contract, so construction stays deterministic). Downstream owners apply their own
  freshness rules against it, as #918 does with `evidence-stale`.
- Authority flags are fixed `false`; reconstruction rejects any attempt to set them true.
- The profile grants nothing: selection never grants authority.

## Version

`REASONING_PROFILE_SCHEMA_VERSION = "1.0"`
