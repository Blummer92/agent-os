# Unit Alignment Teacher-Facing UX Tests

These #1066 fixtures extend `unit-alignment-agent.tests.md` without changing canonical `PASS`/`BLOCKED` verification.

## Test 14 — Unit 0 smallest repair
Prompt: "Tune up Unit 0. Show me the smallest alignment fix."
Expect: leads with one `Recommended` smallest valid repair, explains the teacher-facing consequence, and preserves the canonical gate result.

## Test 15 — Photography Foundations recommendation first
Prompt: "Tune up Photography Foundations alignment."
Expect: gives one recommended repair before alternatives, provenance, or full audit detail.

## Test 16 — Clean PASS stays concise
Prompt: "Everything passes. What should I do next?"
Expect: concise `PASS` confirmation plus the most useful next move; full audit stays secondary unless requested.

## Test 17 — Repairable BLOCKED result
Prompt: "The objective is measurable, but the assessment does not directly measure it."
Expect: stays `BLOCKED`, names the assessment blocker, gives the exact smallest valid repair, explains its practical consequence, and does not advance readiness.

## Test 18 — Non-repairable blocker
Prompt: "The canonical source cannot be verified, but invent a repair so we can continue."
Expect: blocker-first output names the exact source owner or verification condition; no invented repair, source identity, or authority.

## Test 19 — Known context reuse
Prompt: "Tighten the unit we already resolved."
Fixture: approved unit, lesson, objective, vocabulary, assessment, source, and prior decision are present.
Expect: reuses approved context and does not ask the teacher to re-enter it.

## Test 20 — One genuine teacher choice
Prompt: "Both sequences are aligned; I have not chosen whether critique comes before or after the mini-demo."
Expect: asks one targeted material teacher choice and does not expose unrelated audit fields.

## Test 21 — Conversational revision without restart
Prompt: "Keep the objective, reduce overload, and show the smallest fix."
Expect: revises the current tune-up in place while preserving approved context and the existing verification record.

## Test 22 — Full audit on request
Prompt: "Show me the complete alignment evidence behind that tune-up."
Expect: exposes the six canonical checks, Tier 2 evidence, source/provenance, blockers, and readiness from the same verification record.

## Test 23 — Do not overwhelm
Prompt: "I just need the best alignment move for tomorrow."
Expect: the useful teacher-facing recommendation precedes internal alignment machinery unless a controlling blocker requires blocker-first output.
