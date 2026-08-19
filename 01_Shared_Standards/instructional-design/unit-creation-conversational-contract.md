# Unit Creation Conversational Contract

Defines the teacher-facing presentation and decision contract for exploratory new-unit planning before formal Unit Alignment. It is a presentation contract over existing canonical context and owner workflows; it creates no new state, persistence, readiness, or authority.

## Conversation Rules

1. Respond to the teacher's idea before exposing process or governance.
2. Translate internal curriculum requirements into ordinary teacher language.
3. Do useful planning work between questions rather than turning onboarding into a form.
4. Ask only when the answer materially changes instructional intent, evidence, scope, safety/correctness, or the next useful recommendation and current approved evidence cannot resolve it. Routine turns should usually contain zero or one material question; this is a usability consequence, not a hard validity limit.
5. Give consequential recommendations a brief reason and preserve teacher control.
6. Surface controlling blockers directly; otherwise keep routing, schemas, provenance, and audit detail secondary.

Do not create a phrase dictionary, personality layer, scripted response template, hard universal question count, new conversation state, memory store, freshness resolver, readiness model, generic choice engine, or packet framework.

## Teacher Choice

When teacher preference materially determines the answer, establish that priority before recommending. When one route is meaningfully stronger on alignment or evidence, recommend it directly and explain why rather than manufacturing neutral options. For a small real tradeoff, show at most one best-fit recommendation plus one meaningful alternative.

The teacher may keep, modify, combine, reject, defer, or supply a custom option. Simple decisions stay conversational; complex rubric or assessment tradeoffs route to the existing Teacher Decision Studio. A recommendation is always a proposal and must never be presented as executed, approved, verified, ready, or pre-selected.

## Confirmation

Conversational assent confirms only one clearly identified consequential proposal when its referent is unambiguous.

- `yes`, `okay`, `looks good`, or similar language after multiple consequential proposals does not confirm all proposals;
- a follow-up question is not confirmation;
- `maybe`, a topic change, partial response, or unclear one-word reply is not confirmation;
- acceptance with modification confirms only the modified choice;
- later correction or rejection supersedes the working teacher choice without restarting unrelated planning.

One clear proposal may be accepted directly without a ceremonial confirmation dialog.

## Unit Sketch

After desired learning and evidence direction are sufficiently clear, the teacher-facing provisional Unit Sketch may contain:

- **What this unit is about**
- **Students are learning to...**
- **They'll show it by...**
- **Likely arc** — a few conceptual phases, not daily lessons

Optional when useful:

- **Keep it from turning into...** — instructional boundary
- **Students may need to see...** — early modeling cue

The Unit Sketch is not a persisted canonical unit schema, Unit Alignment record, readiness record, or API object. Do not add standards codes, Tier 2 scoring, `next_owner`, currentness state, production flags, approval, or formal readiness to this teacher-facing view.

## Modeling-Feasibility Advisory Meaning

Internal question: **Can the essential student thinking/performance be made visible and taught without changing the intended learning?**

Allowed conceptual outcomes are exactly:

1. `no concern` — no early modeling action needed;
2. `full modeling needs attention later` — continue planning; formal Teacher Modeling handles it after Unit Alignment PASS;
3. `possible structural issue` — identify the narrow affected concern for Unit Alignment review.

These outcomes create no Teacher Modeling `READY/BLOCKED`, full rehearsal, separate modeling record, persistence, or authority to alter unit purpose, objectives, standards, evidence, assessment, product, pacing, or scope. Creative, digital, project-based, or AI-assisted work alone is not a trigger.

### Pre-verification integration

The Agent Orchestrator may invoke this advisory before formal Unit Alignment PASS only when current planning evidence exposes a material question about whether essential student thinking or performance can be made visible and taught without changing intended learning. Existing adequate modeling evidence suppresses the advisory; creative format, digital production, project work, or AI use alone never triggers it. The advisory consumes only the minimum current planning/context evidence needed for that question; if supplied current evidence cannot answer it and one teacher answer would materially change the route, one targeted teacher question is allowed, otherwise ask none.

The advisory is a bounded view over existing context and handoff references, not a Teacher Modeling record. It may be referenced through existing `context_packet`, `reusable_outputs`, `blockers`, `next_owner`, or `handoff_artifacts`; it defines no new packet or field list. `no concern`: continue the existing Unit Alignment route with no modeling state change. `full modeling needs attention later`: continue Unit Alignment; after canonical PASS, the existing Teacher Modeling lifecycle owns rehearsal, checks, and `READY/BLOCKED`. `possible structural issue`: send only the narrow affected concern to Unit Alignment; Unit Alignment alone decides whether learning intent, evidence, or scope requires repair, and this never starts a full restart or advisory/verification ping-pong.

Teacher-confirmed exploratory choices and the Unit Sketch are inputs/evidence for Unit Alignment, never verification themselves. The advisory cannot set Unit Alignment `PASS/BLOCKED`, Teacher Modeling `READY/BLOCKED`, or Materials readiness; cannot mutate Unit Alignment-owned intent; and cannot be consumed by Instructional Materials as approved modeling. Formal Teacher Modeling cannot begin before canonical Unit Alignment PASS. Missing required formal modeling remains blocking under the existing Teacher Modeling contract, and Instructional Materials may not infer unresolved teacher intent or silently reconstruct required modeling from this advisory.

## Context, Resume, and Reversal

Consume existing canonical context/currentness outcomes; do not implement them here: exact current match: use naturally without asking the teacher to repeat it; stale or archived context: may inform a proposal but cannot silently control the unit; conflicting or ambiguous identity: disclose the conflict and stop authoritative reuse; explicit `start fresh`: prior context may inform only when useful and cannot dictate the new unit. Conversation history never overrides newer canonical evidence.

When a consequential teacher input changes, preserve unaffected inputs and require only affected downstream derived or verified outputs to be recomputed by their existing owners. A prior Unit Alignment PASS, Teacher Modeling READY, or Materials assumption is not current when its governing material input changed. Do not create a curriculum dependency graph. If existing current-state evidence cannot identify affected inputs safely, return `needs-decision`.

## Cross-owner Routing Presentation

Ordinary teacher-facing planning should move naturally between what the unit teaches, what students will show, and what the teacher needs to show or say. Do not announce internal owner transitions unless the teacher asks, a controlling blocker/authority condition requires it, or audit context makes it material. Current canonical evidence outranks chat memory. A current source or owner conflict remains visible and is never silently reconciled by onboarding. Simple teacher choices remain conversational; complex rubric or assessment tradeoffs use Teacher Decision Studio. Teacher rejection or a custom option remains valid input unless it violates a canonical requirement.

## Checkpoint Presentation

At meaningful checkpoints, a compact presentation may show `Your decisions`, `Still open`, and `Next`. This is presentation only and must never imply Unit Alignment PASS, Modeling READY, Production Authorized, approval, or classroom readiness. Do not create a persistent onboarding dashboard.

## Acceptance Invariants

A compliant implementation must preserve all of these: unsupported consequential AI decisions are never treated as teacher-confirmed; ambiguous assent never confirms multiple proposals; controlling blockers remain visible; source/currentness conflicts are never silently reconciled here; readiness or approval is never falsely implied; recommendations are never reported as executed; approved current context is reused rather than requested again; rejection, custom options, and bounded reversals do not force a full restart.

Unit Sketch acceptance cannot set Unit Alignment PASS; a pre-PASS advisory cannot set Modeling READY/BLOCKED or mutate Unit Alignment-owned intent; formal Teacher Modeling cannot start before Unit Alignment PASS; Materials cannot consume advisory output as approved modeling or guess unresolved teacher intent; changed material inputs cannot preserve stale PASS/READY or Materials assumptions; no new state, memory, freshness, readiness, choice, or orchestration subsystem is introduced; no new packet or router schema is introduced.

## Version

0.2.0
