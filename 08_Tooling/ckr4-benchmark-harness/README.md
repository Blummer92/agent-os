# CKR4 GPT-6 measurement-only harness

Issue #1146. **Experimental Draft implementation; not an accepted A/B/C benchmark.**

## Boundaries

- Manual workflow dispatch only; maximum three frozen T1–T10 task identities per dispatch.
- Uses the OpenAI Responses API model `gpt-6-astra` with medium reasoning and `store=false`.
- Requires `CKR4_MODEL_API_KEY` and the already-governed read-only `NOTION_TOKEN` GitHub Actions secrets. Never paste keys into dispatch inputs, logs, issue comments, or files. The connector cannot create or verify secrets.
- A GitHub-only, B broad bounded Notion, C bounded filtered Notion (T2/T5 not-needed => zero Notion calls).
- Notion content is deliberately excluded from the model prompt until canonical CKR2 relevance/currentness and qualification can be preserved. Candidate IDs alone **cannot** establish usefulness.
- API input-token usage is observed directly; agent-step count here is a single model call per arm and **not** a meaningful agent-step reduction measurement.
- No correctness/safety scorer, isolation proof, counterexample patch scoring, historical contamination guard, or representative full A/B/C task run is claimed. These limitations block any adoption decision.
- Model calls incur real OpenAI API charges. Dispatch requires exact cost acknowledgment `I_AUTHORIZE_API_COST`; costs remain subject to provider billing.
- The workflow uses only read-only GitHub and Notion calls. It does not create issues, comments, or PRs, change secrets, or modify Notion. Evidence is an Actions artifact with short retention.
- #520 owns CI/build/validation timing and compute. This tool does not claim those savings.

## Reproducibility

The canonical frozen identities and observed null-vs-zero semantics remain in `08_Tooling/agent-memory-context-manager/tests/fixtures/ckr4_hypothesis_benchmark.json` and `CKR4_BENCHMARK_COUNTERS.md`. This runner records model, effort, task, arm, directly observed API usage and candidate counts. It does not replace the original benchmark evidence.

Run offline tests:

```sh
python -m unittest discover -s tests/ckr4_harness -p 'test_*.py' -v
```

## Before live acceptance

QA/Test must verify the real frozen tasks are executable with identical pre-fix repository snapshots, isolate sessions and descendant solutions, reuse CKR2 selection rather than a local invented heuristic, verify Notion source identity and revision, score correctness and safety with hidden tests, and establish meaningful agent-step equivalence. Do not dispatch or recommend adoption until these gaps are resolved.

No benchmark execution, secret configuration, merge, issue closure, or production activation is part of this Draft.
