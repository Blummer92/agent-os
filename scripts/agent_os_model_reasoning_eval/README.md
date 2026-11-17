# Model x Reasoning Evaluation Harness (#3337, AN-MR2)

Fixture-first offline evaluation harness comparing identical canonical Agent OS
task packets (T1-T7) across candidate model x reasoning-setting identities.

## What this is

- **Task packets** (`fixtures/task_packets.json`): 14 frozen canonical packets,
  two per required family -- T1 extraction, T2 classification/triage, T3 ordinary
  implementation reasoning, T4 debugging, T5 architecture, T6 adversarial
  review, T7 decision support / manual-review calibration. Each packet carries
  its AN-MR1 task class and reasoning effort (reused from the merged #3375
  provider-neutral contract) and a content digest. Identical digests across
  candidates are what make runs comparable.
- **Fixture/mock providers** (`providers.py`): the only executable providers.
  Transcripts are deterministic fixtures -- scripted per-candidate per-family
  competence tiers plus hand-authored overrides, including negative fixtures
  (authority-bearing output, contaminated run, unsupported configuration).
- **Runner** (`runner.py`): executes every candidate against every packet,
  measures wall-clock latency, scores accuracy vs the fixture expected outputs,
  records validation results and measured cost, and emits a component-evidence
  report.
- **Metrics** (`metrics.py`): observational component metrics with explicit
  denominators and sample sizes.

## The fail-closed no-network guarantee

This harness is structurally incapable of live network calls:

1. No provider, runner, or metrics module imports any network library
   (`httpx`, `requests`, `urllib.request`, `aiohttp` are all absent; the test
   suite scans the package sources to enforce this).
2. There is no live provider adapter to configure -- `LiveModelProvider.run`
   raises `LiveCallRefusedError` unconditionally.
3. `EvaluationRunner` rejects any provider that is not a `MockModelProvider`
   before any execution attempt, so a misconfigured caller fails closed.
4. No credentials are read anywhere in the package.

Cost is *measured* $0.00 offline (`cost_basis: "measured-offline"`); live costs
are never projected. Tokens are fixture-declared (`tokens_basis:
"fixture-declared"`); latency is measured wall-clock.

## Running it

From the repository root:

```
python -m scripts.agent_os_model_reasoning_eval.runner --runs 1
python -m scripts.agent_os_model_reasoning_eval.runner --out report.json
```

Focused tests:

```
<venv>/bin/pytest tests/agent_os_model_reasoning_eval -p no:cacheprovider
```

## Reading the results

The report is **component evidence only**: per-run metrics, per-family and
overall aggregates with denominators, and a comparability verdict. It is not
a universal "best model" score and grants no execution, readiness, merge, or
closure authority. Provider output stays untrusted -- authority-bearing
transcripts are recorded as `authority-bearing-output` exclusions, never
scored as successes. Unknown capabilities (Muse) and unknown availability stay
explicitly unqualified in the candidate metadata.
