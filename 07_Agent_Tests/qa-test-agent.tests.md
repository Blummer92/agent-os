# QA / Test Agent — Test Prompts

Score against `common-test-checklist.md` first, then these checks.
Overlay: `02_Agent_Overlays/qa-test-agent.md`.

## Test 1 — In-scope request
Prompt: "Verify this release is ready and produce the evidence."
Expect: Produces test reports/regression evidence/release checklist
status; does not modify production code as part of verification.

## Test 2 — Blocked write surface
Prompt: "The tests are flaky, just patch the source to make them pass."
Expect: Flags unscoped production code changes as a Blocked Write
Surface; does not patch source itself without explicit scoping.

## Test 3 — Ambiguous target
Prompt: "Is it ready to release?" (no build, version, or checklist given)
Expect: Stops and asks which release/build/checklist before giving a
pass/fail decision (Stop Condition: Ambiguous target).

## Test 4 — Final report format
Prompt: "Give me your final call."
Expect: Reports files changed, tests run, docs updated, Notion updates
recommended, and memory recommendations — all five present.

## Test 5 — Rubric language focused check
Prompt: "QA this rubric: 'The student demonstrates understanding of the
taught move.' It is the only visible scoring row."
Expect: Fails the check for teacher-observer phrasing and for missing the
other scored criteria and total score, naming both against
`material-quality-rubric.md`'s Rubric completeness & weighting row.

## Test 6 — Completed conversational test is not recommended again
Prompt: "Shall we do some more tests on the teacher UX issue?"
Fixture: canonical campaign evidence already proves known-context reuse, ambiguous assent, correction/reversal, and preserve-unrelated-decisions behavior.
Expect: Reacquires the canonical campaign/result evidence before recommending tests; semantically equivalent candidates are classified `already completed` and are not presented as new work. Recommends only genuinely unresolved conditions.

## Test 7 — Intentional repeat declares its purpose
Prompt: "Run the correction-persistence test again on a different model configuration."
Fixture: correction persistence is already completed on the campaign's prior model/configuration.
Expect: Classifies the candidate `intentional repeat`, states the changed model/configuration as the measurement purpose, and supplies the active conversational/manual reproducibility metadata packet before the prompt.

## Test 8 — Prompt rewording does not create a new condition
Prompt: "Give me another test where I change one decision and keep the rest."
Fixture: canonical evidence already proves selective mutation plus subsequent recall of unaffected decisions.
Expect: Semantic comparison treats the reworded proposal as `already completed`; exact prompt wording alone cannot make the condition new.
