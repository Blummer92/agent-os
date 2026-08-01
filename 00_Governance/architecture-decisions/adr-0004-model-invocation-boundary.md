# ADR 0004: Model Invocation Boundary

## Status

Accepted for planning. Documentation only.

## Context

Instructional material generation in `08_Tooling/instructional-materials-coach/` is
deterministic today: an approved Slides or Docs template is duplicated, then placeholder tokens
are replaced through batchUpdate payloads. No model is invoked anywhere in Agent OS.

Introducing a generative model to draft lesson content crosses a boundary this repository has
tracked explicitly. `CHANGELOG.md` repeatedly records that a change added "no AI invocation,"
alongside network, credential, persistence, and external-write behavior. Model invocation is
therefore a governed capability, not an implementation detail, and it needs an authority
decision before any dependency, adapter, or schema exists.

This ADR decides that boundary. It adds no dependency, client, adapter, schema, prompt, or
credential, and authorizes no external call.

## Decision

Model invocation is an authorized Agent OS capability, bounded as follows.

- Model-generated content is **always draft content**. It is a proposal for human review, never
  a finished or approved artifact.
- Model generation **cannot modify** readiness values, approvals, governance records, registry
  files, ownership records, or source-of-truth records.
- Model generation **cannot be used as validation evidence**. Validation evidence remains
  deterministic, reproducible, and bound to an exact SHA.
- Model invocation **grants no additional write authority**. It does not widen any existing
  write surface and creates no new one.
- Credentials are **external only**. No API key, token, or credential enters this repository;
  only variable names and non-secret references may be committed.

Instructional generation is owned by the Instructional Materials Coach, already recorded in
`04_Registry/ownership-matrix.md`. This ADR adds no ownership-matrix row and no canonical agent.

## Non-Authority Statements

Model invocation is not:

- an Agent OS agent;
- a write owner for GitHub, Notion, or Google Workspace;
- an approval, readiness, or acceptance authority;
- a source of validation evidence;
- a justification for widening an existing write surface.

## Authority Boundary

A model proposes; a human disposes; existing gates execute. Generation produces a draft
artifact, review remains human, and every downstream write continues to pass through the write
surface that already governs it. Repository changes continue to route through the GitHub Change
Request handoff in `03_Templates/prompts/github-change-request.md`, and the GitHub Service Agent
remains the sole GitHub repository write owner, exactly as before. Drive, Slides, and Docs
writes remain behind the existing `ALLOW_WRITE` gate. Notion access remains read-only.

Consistent with `00_Governance/architecture-decisions/adr-0003-cloud-execution-substrate.md`:
a request does not create authority, and execution does not create ownership.

## Tool Boundary

When a model is given callable tools, the runtime may execute those tools automatically. Every
tool exposed to a model must therefore be read-only. A writable tool would hand the model an
indirect write path that no approval gate reviewed, which this ADR prohibits. Implementations
must prove the read-only property by test, not by convention.

## Determinism

Generation is nondeterministic. Deterministic rendering, offline validation, and exact-SHA
evidence remain the basis for every acceptance decision. A nondeterministic step may produce
draft artifacts; it may not produce evidence that a gate consumes.

## Rejected Alternatives

- Treating generated content as finished material: rejected because it would place unreviewed
  output in front of students and bypass existing quality gates.
- Allowing writable tools for convenience: rejected because automatic tool execution converts a
  writable tool into an unreviewed write path.
- Adding a new canonical agent for generation: rejected because Instructional Materials Coach
  already owns instructional generation, and `00_Governance/agent-creation-policy.md` forbids
  redundant agents.

## Validation Expectations

- This ADR remains under the Markdown line limit.
- No runtime behavior, dependency, credential, or external call is introduced.
- `07_Agent_Tests/validate_registry_consistency.py` passes unmodified, with
  `04_Registry/ownership-matrix.md` unchanged.

## Version

0.1.0

## Changelog

- 0.1.0 accepted the model invocation boundary: draft-only output, no added write authority,
  no validation evidence, read-only tools, external credentials.
