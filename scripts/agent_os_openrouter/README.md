# OpenRouter Bug-Investigation Pilot (#3637)

Opt-in, disabled-by-default provider adapter for independent two-model bug
investigations. It reuses the `scripts/agent_os_pr_remediation/` evidence
kernel's `ProposalAdapter` seam and strict verifier without modifying any
kernel file.

## Purpose

Evaluate whether OpenRouter-mediated, independent two-model bug
investigations reduce time to verified root cause without weakening
governance. This package is the pilot's Phase 2 (provider extension) and
Phase 3 (offline validation) implementation. It ends at decision input: the
offline benchmark and the prepared-but-unexecuted live plan below.

## Enabling (opt-in)

The pilot is **off** unless every condition holds:

| Variable | Meaning |
|---|---|
| `OPENROUTER_PILOT_ENABLED` | Must be exactly `"true"`. Anything else (unset, `"1"`, `"yes"`) leaves the pilot disabled, regardless of other variables. |
| `OPENROUTER_API_KEY` | The API key. Read from the environment at call time only. |
| `OPENROUTER_MODEL_A` / `OPENROUTER_MODEL_B` | The two independent investigation models, in OpenRouter `vendor/model` form. Defaults are examples (`anthropic/claude-sonnet-4.5`, `openai/gpt-5`); availability is verified at enablement time, not assumed here. |
| `OPENROUTER_MAX_TOKENS_PER_REQUEST` | Per-request token cap (default 4096). |
| `OPENROUTER_MAX_REQUESTS_PER_INVESTIGATION` | Per-adapter request cap (default 8). |
| `OPENROUTER_MAX_TOTAL_TOKENS` | Shared pair budget for one dual investigation (default 120000). |
| `OPENROUTER_TIMEOUT_SECONDS` | HTTP timeout (default 60). |
| `OPENROUTER_MAX_RETRIES` | Retries on transient failures (default 3). |
| `OPENROUTER_RETRY_BACKOFF_SECONDS` | Base backoff (default 2.0, exponential). |
| `OPENROUTER_ENDPOINT` | Chat-completions endpoint (default `https://openrouter.ai/api/v1/chat/completions`). |
| `OPENROUTER_API_KEY_ENV_VAR` | Override the key's env-var *name* (default `OPENROUTER_API_KEY`). |
| `OPENROUTER_MODELS_ENDPOINT` | `/models` catalog feeding the pricing gate (default `https://openrouter.ai/api/v1/models`). |
| `OPENROUTER_GENERATION_ENDPOINT` | Per-call cost verification (default `https://openrouter.ai/api/v1/generation`). |
| `OPENROUTER_SPEND_CEILING_USD` | Cumulative spend backstop, default `0.0` (these models are free). |

Only variable **names** appear above and in code. No key material is stored,
logged, or embedded in errors, stats, or evidence payloads.

## Free-model pricing gate

The live benchmark runs **free models only**, enforced in the invocation
path -- not as an advisory side check. `FreeModelPricingGate`
(`pricing.py`) is checked inside `OpenRouterProposalAdapter.propose()` before
every transport call:

- The exact model identity sent to the API must end with `:free`. The gate
  never strips `:free` and never substitutes a paid model; anything else is
  rejected, even with zero pricing.
- Zero-cost pricing is verified from a fresh `/models` catalog snapshot:
  `pricing.prompt` and `pricing.completion` must both be zero (accepts `"0"`,
  `0`, `0.0`). Unknown model ids, missing pricing, or nonzero values fail
  closed with `OpenRouterPricingGateError`.
- The catalog is fetched at runner start and **re-fetched before every
  invocation**. A mid-run re-fetch failure fails closed: no invocation on
  stale or unknown pricing.
- After each response, the generation id is looked up at
  `/api/v1/generation` and its cost must verify zero. Nonzero or unknown
  cost is a fail-closed defect (the kernel maps it to NEEDS_DECISION /
  `provider.failure` -- never a synthesized plan).

A pricing-gate defect stops the whole live run: the free-model assumption is
violated and further invocations would risk spend. The spend ceiling
(`OPENROUTER_SPEND_CEILING_USD`, default `0.0`) is a defense-in-depth
backstop checked after each bug.

## Budgets

- Per-request: `max_tokens` is bounded by `max_tokens_per_request`.
- Per-adapter: at most `max_requests_per_investigation` provider calls.
- Shared pair: `OpenRouterBudgetTracker` aborts the second model's call with
  `provider.unavailable` (fail closed) when the budget is exhausted, rather
  than overspending. One response may overrun by at most its own reported
  usage; the per-request cap keeps that bounded.
- Retry: exponential backoff on `URLError`, timeouts, HTTP 5xx, 408/425/429.
  Other 4xx responses are terminal and fail closed without retry.

## Security invariants

- Disabled-by-default; `is_configured()` requires enabled **and** a present,
  non-empty key.
- The key is read from `os.environ` at call time, never stored on the config
  or adapter, never logged, never in `repr` or exceptions.
- The request payload carries structured investigation metadata (paths, SHAs,
  schema keys) only -- never file contents. A defense-in-depth bound
  (mirroring the kernel's 4 KiB text bound) rejects oversized payload strings
  before any network call.
- Model output is untrusted: non-JSON raises `OpenRouterMalformedResponse`
  (kernel maps to NEEDS_DECISION / `provider.failure`); oversized responses
  are refused at the boundary; `provider_identity`, `model_identity`, and
  `request_fingerprint` are overwritten deterministically so the model cannot
  forge bindings. All kernel verification (exact schema, fingerprint binding,
  authority fields false, scope checks) still applies unchanged.

## How the benchmark works

`benchmark_corpus.json` holds 10 closed, verified Agent OS bugs. Each entry
carries the verified root cause (grounded in the issue), detection criteria,
a **synthetic** canned model transcript per model role (not a recorded live
run), and an illustrative per-model price table.

`benchmark.py`:

- `load_corpus(path)` validates the corpus.
- `run_benchmark(corpus, runner=None)` replays the offline runner per bug and
  computes per-bug plus aggregate metrics: simulated time to verified root
  cause, detection accuracy (predicted vs verified root-cause key), false
  positives, token usage, estimated cost, and the kernel verifier ACCEPTED
  rate.
- `run_benchmark(corpus, live=True, config=...)` -- or `run_live_benchmark`
  directly -- runs the real comparison: 10 bugs x 2 models = 20 investigations
  through `run_dual_investigation` with the pricing gate wired into every
  adapter. Per investigation it records the model id, the pricing evidence
  verified pre-call, wall-clock time to verifier outcome, verifier
  ACCEPTED/REJECTED + reason codes, token usage, and per-call cost
  verification. The corpus's verified root cause and detection criteria are
  never sent to the model; live detection accuracy is not manufactured (the
  aggregate reports verifier outcomes with adjudication deferred to owner
  review).
- `python -m scripts.agent_os_openrouter.benchmark --corpus <path>
  [--output report.json]` runs the offline mode. Add `--live` for the gated
  live comparison (refused without the approvals below). No network call is
  ever made in offline mode or in tests.

## What remains gated on owner approval

- **Live benchmark execution**: the `--live` path refuses to run unless
  `OPENROUTER_BENCHMARK_LIVE_APPROVED` is exactly `"true"` **and** the pilot
  config is enabled and keyed. The pricing gate additionally restricts live
  calls to `:free` models with verified zero pricing -- paid-model calls are
  prohibited by construction, not by policy text.
- **Production activation** of the adapter and **sending private code to
  external providers** are not authorized by this pilot.

## Layout

- `config.py` -- frozen `OpenRouterConfig`, `from_env()`, `validate()`.
- `adapter.py` -- `OpenRouterProposalAdapter`, budget tracker, retry policy,
  pricing-gate wiring in `propose()`.
- `pricing.py` -- `FreeModelPricingGate`, `/models` catalog fetch,
  `/generation` cost verification, `OpenRouterPricingGateError`.
- `investigation.py` -- `run_dual_investigation()` and frozen result records.
- `benchmark.py` -- offline harness plus the gated live free-model benchmark.
- `benchmark_corpus.json` -- the 10-bug corpus.
