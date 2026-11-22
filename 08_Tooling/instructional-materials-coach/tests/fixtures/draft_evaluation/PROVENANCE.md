# Provenance of the model-produced draft fixtures (#4072)

These three files are real, unedited outputs of one model, produced for this test suite. They are fixtures for the deterministic evaluator only. They are not classroom material and no claim is made that any of them is good, accurate or suitable writing.

| field | value |
|---|---|
| model | `claude-sonnet-5-5` (the model id reported by the Claude Code `init` event and by each assistant message) |
| host | Claude Code 2.1.330 non-interactive mode: `claude -p ... --tools "" --no-session-persistence --setting-sources project --strict-mcp-config --output-format stream-json --verbose --model claude-sonnet-5-5` run from an empty neutral working directory |
| date | 2026-11-21 |
| context | a fresh single-turn context per draft: no tools, no MCP servers, no repository instruction files, no user settings or hooks, no prior conversation |
| sampling | one response per prompt; all three runs are recorded here and none was discarded or regenerated |
| extraction | each draft file is the model's `result` text byte for byte (the three responses contained no code fences) |

| draft | prompt (sha256) | draft (sha256) | session id | raw stream (sha256, held with the pull-request evidence) |
|---|---|---|---|---|
| `model_draft_a_plain.yaml` | `prompts/A_plain.txt` (`857c5e60c018c53e8298e0698e11a0fa5fc2c3cfdca9b33a4c43a9159475de2b`) | `743d0fbcc92c7eac10e8ab7116e8ef4227e5cccc85881e18259b9ee8d453f02c` | `5a2e624a-b1a0-4738-9b0e-48518db73a9c` | `265b9aaf3391d939a27583fe9692d6d730a23dc88b5112ca37c3b7c770cabb6b` |
| `model_draft_b_statistic.yaml` | `prompts/B_statistic.txt` (`0ea1523df23358b886d0db12b65a67eab4c7ffb255c3735bd545db3d8448f48c`) | `3fd2e6b8f6a3eddd3b4e90b150c0ccbf6ce3ce6798259891a47c70af4ecc0314` | `8755d634-5ddb-43c2-9040-e1b9f445a40f` | `3e4bce5bf2087c0ef26a9d4ae3b3f5b3f87f4b9a0206c2a02739866d2ff8b6d8` |
| `model_draft_c_detailed.yaml` | `prompts/C_detailed.txt` (`85fe0344396e5afb43cb049956033dc4f3becd110f9ddc02d82f93322f5126eb`) | `8c6a8d4b9ca67776066de28282d60452848523fa84dcbf8ff5a9e7f419824fd6` | `d282bbfb-8090-464c-9913-60f41afa2926` | `61dd98f4e6c0ef4cfe9c10ec5dcefc2907c097e5ca047dd535e19fb5bedfc234` |

The machine-readable values are in `goldens.json` (the test asserts them). The three prompts differ on purpose so the fixtures exercise different findings: a plain request (A), a request that asks for one real-world statistic (B), and a request for rich multi-part questions (C). Each prompt supplies the verified Day 1 learning target and focus from the pinned lesson-content record and asks for four questions, which is why every golden run declares `--min-questions 4`.

## Goldens and their review status

`golden_review: unreviewed-by-human` for all three. The expected findings in `goldens.json` are the evaluator's own output on these recorded drafts, captured on 2026-11-21 with the pinned fixture `lesson_content_run_38462963519.json`. **No human has reviewed them.** The issue's acceptance criterion that goldens be human-reviewed is therefore still open: a reviewer must read each draft and its expected findings, then change `golden_review` to `human-reviewed` and add `reviewer` and `reviewed_on` in `goldens.json` (the test enforces those fields when the value is `human-reviewed`). Goldens must never be regenerated blindly.

What the goldens show, stated as observed rather than endorsed: draft A returns no deterministic finding; draft B's first slide bullet attributes a percentage range to a named institute that the verified lesson text does not contain (`draft-ungrounded-claim-pattern`, manual review; whether the claim is true was not checked); draft C's fourth question is longer than 35 words (`draft-instruction-line-over-35-words`, manual review).
