# Curriculum Vocabulary Planner Response Standard

## Purpose

Use this standard when a curriculum-facing agent reviews lesson vocabulary, flags vocabulary overload, or helps decide which words students should learn now versus later.

The output must be concise, table-based, and decision-oriented. Prefer comparison tables over long explanations.

## Required Response Shape

Agents must respond with these sections in this order unless the user asks for a different format:

1. `Vocabulary Snapshot`
2. `Vocabulary Planner Table`
3. `Difficulty by Student Group`
4. `Issue and Fix`
5. `Assessment Vocabulary`
6. `Recommendation`
7. `Next Action`

## Vocabulary Snapshot

Summarize the lesson vocabulary load in a small table:

| Check | Status | Direction |
|---|---|---|
| Candidate word count | number | keep / reduce / expand |
| Active words today | number | safe / too many |
| Abstract words | number | model / delay |
| Assessment words | number | assess / reduce |

## Vocabulary Planner Table

Start from a candidate pool of about 15-20 vocabulary words. Classify each word as one of:

- `Teach & Use Today`
- `Introduce, Don’t Assess Yet`
- `Future Unit Vocabulary`

For each word include:

| Word | Student-Friendly Definition | Category | Lowest-Performing Difficulty | On-Grade-Level Difficulty | Advanced Difficulty | Concrete/Abstract | Observable? | Assessable Today? | Prior Vocabulary Connection |
|---|---|---|---|---|---|---|---|---|---|

Use `Low`, `Medium`, or `High` for difficulty.

## Prior Unit Vocabulary Context

Difficulty judgments must consider vocabulary students have already learned in earlier units, not only the current lesson or unit.

- If a word is already familiar from an earlier unit, rate it easier and name the prior connection.
- If a word is new but built from known words, rate it as partially supported.
- If a word is new, abstract, and not observable, rate it harder and delay assessment.
- If prior vocabulary context is unavailable, say `Prior context not provided` instead of guessing.

## Difficulty by Student Group

Show what each student group is likely to need:

| Student Group | Likely Barrier | Support Needed | Safe Expectation |
|---|---|---|---|
| Lowest-performing students | | | |
| On-grade-level students | | | |
| Advanced students | | | |

## Issue and Fix

When vocabulary overload, ambiguity, or assessment misalignment appears, use this table:

| Issue | Why It Matters | Fix |
|---|---|---|

Name only the most important issues. Do not list every possible concern.

## Assessment Vocabulary

Separate words students must master today from words they only hear or see:

| Use Today and Assess | Introduce Only | Save for Later |
|---|---|---|

Assessment words must be observable in student work or student explanation.

## Recommendation and Next Action

End with:

- `Recommendation`: one clear direction.
- `Next Action`: one concrete action the teacher or agent should take next.

Do not end with multiple optional next steps unless the user requests options.