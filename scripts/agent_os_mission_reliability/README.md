# Mission-Level Reliability Measurement (#2766)

Read-only measurement evidence that separates Agent OS throughput (issue/PR/commit
volume) from mission-level reliability. Owned by `owner:qa-test-agent` for issue
#2766. Read-only measurement/evidence only: no analytics platform, no event
warehouse, no new persistence, no repository or GitHub writes.

## What this is

`scripts/agent_os_mission_reliability/` computes the minimal measurement set from
already-durable evidence:

1. **Acquire** (read-only): `github_source.acquire_mission_records()` freezes a
   bounded issue population and normalizes it into mission records, or the
   caller supplies records directly from another durable source (mission
   completion admission records, handoff records, batch reports).
2. **Derive** (pure): `derive.derive_mission_reliability(records, window=...)`
   projects every metric below, each with exact `n`, numerator/denominator,
   median/p90 for elapsed times, evidence source, and confidence.

Run it: `python -m scripts.agent_os_mission_reliability --owner Blummer92
--repo agent-os --issues 2775,2776` (add `--admitted 2775:<ISO>` for admission
evidence; only HTTP GET is issued; `GITHUB_TOKEN` is optional).

## Module map

```text
__main__ -> cli -> args -> inputs -> errors
               |-> http_client -> errors
               |-> report -> errors
               +-> service -> github_source -> inputs/http_client/errors
                             |                 + canonical issue linkage parser
                             +-> derive -> inputs/errors
                                        +-> progress/delivery/lifecycle/outcome_metrics -> metrics
```

| File | One job |
|---|---|
| `__main__.py`, `cli.py` | Module entrypoint and CLI orchestration, respectively. Only the CLI reads the token environment value, after parsing. |
| `args.py`, `inputs.py` | Parse argument text and freeze validated issue/admission data, respectively. |
| `http_client.py` | One GitHub API JSON GET, with timeouts, origin policy, pagination indicator, and safe errors. |
| `github_source.py` | Freeze and acquire exact issue/PR records; continues numeric pages only when the response indicates next-page coverage. |
| `service.py` | Check all acquired identities, then compose acquisition and derivation. |
| `derive.py` | Validate normalized rows and concatenate pure metric projections without changing the callers' data. |
| `progress_metrics.py`, `delivery_metrics.py`, `lifecycle_metrics.py`, `outcome_metrics.py` | Group pure formulas by completion/interaction, PR delivery, elapsed time, and finite/learning outcomes. |
| `metrics.py` | Assemble metric rows and calculate time distributions, with no I/O or transport. |
| `errors.py`, `report.py` | Define structured errors and serialize complete output, respectively. |
| `__init__.py` | Preserve the package-level acquisition and derivation exports. |

The grouped metric projections are pure and keep related prefilters, evidence
labels, and formulas together. Their literal row definitions explain why those
functions exceed 35 lines; no other production function does.

### Usage and compatibility

Run both CLI and tests from a checkout root. No path edits, installed console
entrypoint, or extra setup is provided by this repository's `pyproject.toml`:

```sh
python -m scripts.agent_os_mission_reliability --owner Blummer92 --repo agent-os --issues 2775,2776
python -m pytest tests/agent_os_mission_reliability
```

- `--issues` accepts up to 100 decimal entries (positive signed-32-bit range),
  deduplicated in first-seen order. Empty entries are errors.
- `--admitted` requires unique entries from the frozen set, with offset-aware
  ISO timestamps. Omitted issues are not admitted.
- Only HTTPS GETs to the GitHub API are used. Cross-origin redirects are
  refused, so the optional trimmed token is never forwarded. No retries.
- The CLI scans up to 30 PR pages of 100; the injected-reader API retains its
  10-page default and may explicitly select a limit up to 30. More pages,
  duplicate page identities, incomplete acquisition, or wrong issue / PR
  readback cause an error rather than a partial report. Large repositories
  above this scan limit cannot produce a complete report by this route.
- Success prints `{"records":...,"report":...}`, preserving the existing
  records envelope and its nested `records` list. CLI-only `report.window`
  is now `{repository, issue_numbers, label}` rather than a bare label.
  Programmatic `derive_mission_reliability(..., window="label")` still returns
  the string label unchanged. Unknown metrics are valid evidence, not failures.
- Exit codes: **0** verified report (or standard `--help`), **1** failed
  acquisition or report processing, **2** invalid arguments or token.
  Failure outputs one `{"error":{"code":...,"message":...,"field":...}}`
  object, with optional sanitized HTTP status, body excerpt, and rate limits.

## Metric definitions and derivation sources

| Metric | Definition | Derivation source |
|---|---|---|
| `admitted_missions` | Admitted missions in the frozen window | Caller-frozen population + admission evidence |
| `truthful_terminal_completion` | Admitted missions reaching a truthful terminal state / admitted missions with known terminal state | Durable terminal evidence only (e.g. mission completion admission records); unknowns excluded, not estimated |
| `intermediate_stops` | Admitted missions stopped at a non-terminal state / admitted | Durable terminal-state evidence |
| `blocker_split` | Systemic vs item-local blocker counts (disjoint counts, no ratio) | Durable terminal-state evidence |
| `user_interventions_per_completed_mission` | User interventions / completed-truthful missions with durable intervention evidence | Durable host records only; **unknown** otherwise |
| `continuation_prompts` | Re-prompt / explicit-continuation counts over admitted missions with durable evidence | Durable continuation records only; **unknown** otherwise (#2753 owns host lifecycle telemetry) |
| `issue_to_pr_conversion` | Admitted issues with >=1 linked implementation PR; elapsed admitted_at -> first PR | Canonical closing-keyword linkage (`scripts/agent_os_issue_acceptance/parse_pr.parse_linked_issue`) + `agent/<issue>-<slug>` branches |
| `pr_merge_conversion` | Linked implementation PRs merged; elapsed PR create -> merge | GitHub PR `merged` flag + `merged_at` |
| `repair_attempts_per_delivered_implementation` | Repair/follow-up PRs / delivered implementations (first PR merged) | Repair flag on PRs ordered by creation time (heuristic; authoritative source is #2220/#2607 admission records where present) |
| `failed_repair_reentries` | Delivered implementations with >=1 repair re-entry | Same as above |
| `pr_to_first_terminal_validation` | PR create -> first exact-head terminal validation | Durable `first_terminal_validation_at` timestamps only; CI/build/validation timing itself is owned by #520 and is **not** recomputed here |
| `merge_to_issue_convergence` | Merged first PRs whose linked issue closed after merge; elapsed merge -> close | GitHub `merged_at` + issue `closed_at` |
| `requested_vs_delivered` | Delivered / requested items over finite missions with persisted counts | Persisted counts only (e.g. #2220/#2607 completion proof); **unknown** otherwise |
| `bug_family_recurrence` | Missions in a bug family with an explicit prior completed fix in the same family | Explicit bug-family lineage on the record |
| `finding_to_implementation_to_retest` | Findings reaching a linked implementation PR and then retest evidence | Explicit finding->issue->implementation->retest lineage |

## Confidence rules

- `measured`: every contributing record carries primary evidence for every field used.
- `strongly_evidenced`: durable evidence with one documented linkage assumption
  (issue<->PR closing-keyword linkage).
- `weakly_evidenced`: durable evidence with a heuristic linkage (repair PRs by
  creation order).
- `unknown`: no durable evidence; the metric is reported as unknown, never
  estimated. In particular: user interventions, cross-chat continuations, retry
  ceilings, and requested/delivered counts stay unknown until a durable source
  exists. Do not infer them from memory or narrative.

## What is deliberately out of scope

- No composite health score (forbidden by the #2766 handoff).
- No recomputation of CI/build/validation timing: reference #520.
- No host lifecycle telemetry duplication: #2753.
- No conversational-test metadata: #2744.
- No cross-domain experiment evidence contracts: #1502/#1505.
- No database, event pipeline, conversation logger, or background monitor: the
  derivation stays read-only until a bounded baseline proves one exact missing
  field is materially blocking a high-value question.

## Record schema

See the docstring in `derive.py` for the normalized mission record schema.
Timestamps are ISO-8601 UTC. `terminal_state` is one of
`completed_truthful | blocked_systemic | blocked_item_local | intermediate_stop | unknown`.
Anything without durable evidence stays `None`/`unknown`.
