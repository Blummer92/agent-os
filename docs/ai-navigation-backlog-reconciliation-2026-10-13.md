# AI Navigation Backlog Reconciliation — 2026-10-13

Read-only backlog-maintenance record. It grants no implementation, Ready, merge,
closure, workflow, label, or external-write authority. GitHub stays canonical:
reacquire every mutable fact below before acting on it.

## Evidence baseline

- `main` = `811bf12c7b356d5142ab5977140b9b61449795d3` (fetched 2026-10-13).
- Issues enumerated with `state=OPEN` pagination (219 open, 3 pages), then
  title, label and semantic searches on shadow selection, cohort admission,
  candidate evidence, lifecycle, PR lineage, model recommendation, Navigation
  Index and scanner integration. Every issue body and the decisive comments were
  read in full.
- Code checked on `main`: `scripts/agent-os-shadow-run.py`,
  `shadow_issue_selection.py`, `cohort_admission.py`,
  `live_candidate_evidence_reader.py`, `lifecycle_stage_acquisition.py`,
  `reasoning_profile.py`, `notion_navigation_client/index.py`,
  `.github/workflows/agent-os-shadow-navigation.yml` and its composite action.
- Focused tests run on `main`: 147 passed (shadow selection and provenance,
  cohort admission, reasoning profile, live candidate evidence reader,
  lifecycle-stage acquisition and its integration, shadow-run CLI and ledger,
  shadow navigation action); 33 passed (`notion-navigation-client`). These are
  fixture tests. **None of them is live behavior evidence.**

## Population and dispositions

17 issues are in scope: 8 closed and 9 open. The supporting dependencies read
were #3360, #3361 and #3426, plus PRs #3321, #3323, #3330, #3340, #3357,
#3366, #3370, #3375 and #3440.

| Disposition | Count | Issues |
| --- | ---: | --- |
| COMPLETE (closed, historical) | 8 | #2832, #3082, #3086, #3328, #3329, #3367, #3433, #3336 |
| READY | 4 | #3441, #3306, #3307, #3308 |
| BLOCKED | 3 | #3338, #3339, #3494 |
| DECISION REQUIRED | 2 | #3337, #3429 |
| PARTIAL / SPLIT / DUPLICATE / OBSOLETE | 0 | — |

Closed issues are immutable under the lifecycle contract. Their dispositions
are evidence only, and none is proposed for reopening.

### Closed (historical evidence)

| Issue | Code merged | Tests | Live behavior | Note |
| --- | --- | --- | --- | --- |
| #2832 shadow seam | yes | pass | CLI canary | `select_shadow_issue` has one production caller: the shadow-run CLI. |
| #3328 cohort admission | PRs #3357, #3366 | pass | CLI canary on `49ba7d3e` (#3082 comment 6041392888) | **Gap:** the GitHub Actions route (`agent-os-shadow-navigation.yml` and its action) exposes only manual `candidates`/`narrowing_criterion`. It has no `--request-interpretation`, so canonical cohort admission is reachable from the CLI only. |
| #3329 candidate evidence | PRs #3330, #3340 | pass | fail-closed canary | Production reader wired. `lifecycle_stage`, `primary_claims` and `approval_applicability` are still `None` (`agent-os-shadow-run.py:687-689`). |
| #3367 B3 owner decision | n/a | n/a | n/a | Option (a): accept fail-closed. Superseded for lifecycle-stage development by the owner's 2026-10-08 approval, which produced #3433 and #3441. No owner exists for claims or approval. |
| #3433 lifecycle evaluator | PR #3440 | pass | **unconsumed** | `acquire_lifecycle_stage` has no non-test caller. The successor is #3441. |
| #3082 SELECTED → issue-start | none | n/a | n/a | Closed as satisfied under the #3367 rescope. No `ShadowIssueSelectionResult` consumer exists, which is correct while SELECTED is unreachable. |
| #3086 legacy-wrapper retirement | PR #3370 | — | — | Lineage only. |
| #3336 AN-MR1 reasoning profile | PR #3375 | pass | n/a | Contract only. Exported from `__init__.py`, with no production consumer yet. Its consumers are #3337 and #3338. |

### Open issues

**#3441 AI-NAV-LINEAGE1 — READY.** Verified gap: no complete, read-only
PR-lineage reader exists, nothing outside tests calls `acquire_lifecycle_stage`,
and the shadow CLI passes `lifecycle_stage=None`. #3433 and PR #3440 are merged,
and the body's operative dependency section already says
`Prerequisite satisfied`. The 2026-10-11 appendix marked "NOT APPLIED" is
therefore stale. No competing PR exists. Remaining obligations: the acceptance
list in the body, unchanged. Advisory dependencies only: none. It does not
supply claims or approval (see Decision D1).

**#3306 NAV-USE1 — READY.** `NavigationIndex` has dashboard, database, field,
source-of-truth, workflow, prompt and duplicate-risk lookups, but no Refresh
Log reader. No PR. It is independent, small and fixture-testable.

**#3307 NAV-USE2 — READY.** `check_duplicate_risk` exists, but no pre-create
composition consumes it. No PR. Sequencing after #3306 is advisory; #3306 is
not a hard blocker, because missing chronology must yield
`stale-or-unverified`.

**#3308 NAV-USE3 — READY, scope risk.** It consumes #3306 and #3307 (advisory
ordering). The "continuation architecture lock" duplicates acceptance owned by
#3485 (native continuation) and #2826/#3139. Recommendation: keep those
bullets as references to their owners, not as #3308 acceptance. The
2026-10-11 proposed simplification clause is already present in the body
under `## Canonical navigation reconciliation contract`.

**#3337 AN-MR2 — DECISION REQUIRED.** No PR. The open owner decision, recorded
in comment 6080707496, is fixture and scoring placement plus a qualified
model/configuration matrix. Fixture work needs no provider.

**#3338 AN-MR3 — BLOCKED.** True blocker: its input is a canonically
selected/current task, and production cannot produce one. For arbitrary
backlog, SELECTED is unreachable until lifecycle (#3441) and claims/approval
(D1) exist. Advisory: #3337 measured evidence is needed only for an
evidence-backed preference. #3333 is needed only for live dispatch.

**#3339 AN-MR4 — BLOCKED.** It depends on #3338 semantics. A live Coding
Dashboard schema read can proceed independently, but only through an approved
bounded Notion read. No mutation is authorized.

**#3429 CI-NAV — DECISION REQUIRED.** CodeQL is enabled (#3360 closed). Vulture
is an advisory doc plus a dev dependency (`docs/vulture-advisory.md`, #3361),
with no CI producer of machine-readable findings; scheduling is open as #3426.
No shadow input contract accepts advisory findings. Decision needed: which
existing input (request-interpretation constraint vs. candidate-evidence
annotation) may carry findings, and whether the Vulture producer (#3426) is a
hard prerequisite.

**#3494 UX-NAV — BLOCKED.** Upstream consumers #3308 and #3441 are
unimplemented. Host acceptance (a fresh iOS replay of render → tap → turn →
receipt) is NOT RUN. Pure local action-composition spec work is unblocked.

## Dependency roadmap

| Boundary | Canonical issue(s) | Implementation → consumer | State |
| --- | --- | --- | --- |
| Mission | #3328 (closed) | `request_interpretation.py` → shadow CLI `--request-interpretation` | **Works (CLI)**; disconnected from the Actions route |
| Candidate discovery | #2832, #3328 (closed); #3306→#3307→#3308 | population scan + `cohort_admission.py` | Works for backlog cohort; Navigation Index discovery not built |
| Evidence acquisition | #3329 (closed), **#3441**, D1 | `LiveCandidateEvidenceReader` | **Partial**: lifecycle, claims and approval are `None` → fail-closed |
| Selection | #2832, #3082 (closed); #3494 | `ExecutableLaneSelection` inside `select_shadow_issue` | **Blocked**: SELECTED unreachable for real backlog, by design |
| Authorization | Safe Implementation Lane; #3338 advisory | no shadow → admission consumer (rescoped out by #3082) | Disconnected by decision |
| Execution | #918 (PR #3323); #3333 | `select_executor_route`; Codespaces ingress (PR #3493 canary only) | Partial, outside this family |
| Receipt | #3497 | shadow-run evidence ledger (selection decision only) | Partial |
| Continuation | #3485, #3308 | `continuation_driver.py` (not native host dispatch) | Disconnected at the host |
| Acceptance | #3490, #3494 | Issue Acceptance workflow; host replay | Unproven |

## Ranked implementation queue (not implemented)

1. **#3441.** This is the only change that moves Evidence acquisition forward,
   and it is a prerequisite for #3494, #3338 and any SELECTED canary.
2. **Owner decision D1** (no code): designate an owner for `primary_claims` and
   `approval_applicability`, or record that they stay permanently fail-closed.
   Without this, #3441 alone still cannot yield SELECTED.
3. **#3306**, then **#3307**: small, ready and independent. Together they feed
   #3308 and #3339.
4. **#3308**, with the continuation acceptance narrowed to owner references.
5. **D2** (excluded surface): expose `request_interpretation` on the
   shadow-navigation workflow and action. This needs separate workflow
   authorization.
6. **D3/D4** decisions for #3337 and #3429, then #3337 fixtures.
7. **#3494 host replay** (QA/operator, not code), after items 1 and 4.

## Owner decisions and smallest unblock

| ID | Decision | Smallest unblock |
| --- | --- | --- |
| D1 | Claims and approval owner for shadow candidates | One owner comment: "fail-closed permanently" or "owner = X". The SELECTED goal depends on it. |
| D2 | Workflow route lacks cohort admission | Authorize one bounded edit of `.github/workflows/agent-os-shadow-navigation.yml` and `.github/actions/agent-os-shadow-navigation/` |
| D3 | #3337 placement and model matrix | Pick the package (the `code_review_benchmark.py` owner vs. `experiment_evidence.py`) and the qualified candidate list |
| D4 | #3429 finding input contract | Choose the carrying input and whether #3426 is a prerequisite |
| D5 | Apply the reconciliation packets below | Authorize a GitHub Service Agent write for the open-issue appendices |

## CKR6

**Not run. Blocker:** the governed CKR6 route is the `/agent-os ckr6`
issue-comment trigger (`.github/workflows/agent-os-ckr6.yml`, `issue_comment`,
allowed actor `Blummer92`). Invoking it requires a GitHub comment write. On
this surface, the governed-route preflight returned `status=needs-decision`
(`descriptor-store-not-configured`). No `not-needed` outcome was invented,
and no other mission's result was reused. Smallest unblock: the owner posts
the following on #3441, or authorizes the Service Agent to post it:

```text
/agent-os ckr6 {"operation":"issue-start","repository":"Blummer92/agent-os","issue_number":3441,"task_reference":"AI Navigation backlog reconciliation 2026-10-13","ecosystem_hints":["python"],"language_hints":["python"],"capability_keywords":["shadow navigation","pr lineage","lifecycle stage","backlog reconciliation"],"target_path_hints":["scripts/agent-os-shadow-run.py","scripts/agent_os_issue_acceptance"],"canonical_rule_refs":["issue:#3441","AGENTS.md"],"specialized_knowledge_required":false}
```

## Proposed issue updates (NOT APPLIED — readback pending)

Each packet is appended as a new section and does not replace existing
content. After writing, read back the issue and confirm that the heading
`## 2026-10-13 — AI Navigation backlog reconciliation` appears exactly once.

- **#3441**: "Main `811bf12`: no PR-lineage reader exists. The only
  `acquire_lifecycle_stage` callers are tests, and `agent-os-shadow-run.py:687`
  passes `lifecycle_stage=None`. The 2026-10-11 dependency-correction proposal
  is now present in the body, so that appendix is historical. Disposition:
  READY. Advisory dependencies: none. Claims and approval stay out of scope
  (owner decision D1). No competing PR."
- **#3306**: "No Refresh Log reader in `notion_navigation_client/index.py`.
  Navigation client tests: 33 pass. Disposition: READY; no blocker; no PR."
- **#3307**: "`check_duplicate_risk` exists with no pre-create consumer.
  Disposition: READY. #3306 ordering is advisory: missing chronology maps to
  `stale-or-unverified`."
- **#3308**: "Disposition: READY. Recommend referencing #3485 and #2826/#3139
  for continuation acceptance instead of owning it. The simplification clause
  is already in the body."
- **#3337**: "Disposition: DECISION REQUIRED (D3). #3336 is merged (PR #3375)
  with no consumer yet."
- **#3338**: "Disposition: BLOCKED. Production cannot yield a selected/current
  task until #3441 and D1 are resolved. #3337 is advisory for preference
  claims only."
- **#3339**: "Disposition: BLOCKED on #3338 semantics. The bounded live schema
  read may proceed independently under an approved read route."
- **#3429**: "Disposition: DECISION REQUIRED (D4). CodeQL is enabled (#3360).
  Vulture has no CI findings producer (#3426 open). No shadow input accepts
  findings."
- **#3494**: "Disposition: BLOCKED. #3441 and #3308 are unimplemented, and the
  fresh iOS replay is NOT RUN. Pure local spec work is unblocked."

No closures, duplicates, splits or new issues are proposed. No obligation
lacks a surviving open owner, except claims and approval, which are captured
as decision D1 rather than a new issue (#3367 option (a) deliberately left
them fail-closed).

## Report

- **Files changed:** this document only.
- **Tests run:** 147 + 33 focused fixture tests passed on `811bf12`.
  `validate-repo-structure.sh` was run on this branch.
- **Docs updated:** this reconciliation record.
- **Code merged vs. tests passed vs. live verified:** see the closed-issue
  table. Live evidence exists only for the CLI fail-closed canary (#3082
  comment 6041392888). There is no live SELECTED, no live lineage reader and
  no live host acceptance.
- **Unresolved blockers:** D1–D5; CKR6 not run; issue writes not applied.
- **Handoffs:** GitHub Service Agent (packets D5, then #3441); QA/Test (#3494
  replay; #3337); owner (D1–D4).
- **Remaining risks:** issue state drifts after 2026-10-13; the semantic
  search may miss issues that never use navigation vocabulary; a merged
  evaluator (#3433) can be mistaken for live capability.
- **Excluded surfaces:** none touched. PR #3292 was not modified.
