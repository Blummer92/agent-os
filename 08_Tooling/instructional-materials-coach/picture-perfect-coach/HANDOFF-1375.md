# #1375 PPUX-VRL2 Capable-Runtime Handoff

Status: `needs-capable-runtime`

Issue: #1375 — PPUX-VRL2 — Wire current visual-reference retrieval into Tutorial 0 prompt generation

Branch: `agent/1375-ppux-tutorial0-visual-reference`

Head before this handoff commit: `d7451c40970262af186e7e69c62119d5741dda46`

Do not open the Draft PR until the issue-required developer loop has actually executed on a capable runtime.

## Implemented path

The bounded implementation now projects Tutorial 0 through:

```text
reviewed instructional step
-> historical F1/F2 Recorder/capture binding
-> exact current application context/state selection
-> current-vs-recorded reconciliation
-> VisualSpecification current-reference binding
-> buildPortablePrompt()
```

`VisualSpecification` carries selected current reference identity, application variant, exact context/state, stable asset identity, provenance, and blocker reasons. Ready screen-fidelity prompts preserve both historical capture evidence and the selected current visual reference while using the current reference as the presentation base.

The canonical app now renders `tutorial0CurrentReferencePromptCards`, not the older capture-only Tutorial 0 projection.

## Tutorial 0 behavior

- Your Stuff / Files selects only `navigation/your-stuff/files`.
- Historical `Create new` conflicts with current `Create` -> `Create file` and is blocked with `visual-reference-current-recorded-ui-conflict`.
- A separate explicitly reconciled fixture proves `Create` -> `Create file` can become Ready without rewriting historical Recorder evidence.
- Landscape requires one `creation/get-started` reference supporting both `Landscape` and `16:9`.
- Cross-reference claim unioning remains forbidden.
- Missing current references fail closed.
- Final filename/arrangement uncertainty remains blocked.
- Provider-adapter validation preserves current-reference identity and the non-reconstruction directive.

## Files changed so far

- `src/promptIntent.ts`
- `src/visualReference.ts`
- `src/fixtures/tutorial0-prompts.ts`
- `src/tutorial0VisualReference.test.ts`
- `src/App.tsx`
- `HANDOFF-1375.md`

## Required capable-runtime validation

From `08_Tooling/instructional-materials-coach/picture-perfect-coach`:

```bash
npm ci
npm run typecheck
npm run lint
npm test
npm run build
npm run guard
npm run test:e2e
```

Repository validation:

```bash
bash 07_Agent_Tests/validate-repo-structure.sh
./scripts/validate-all.sh
```

If the known Cloud Shell `/usr/local/bin/agent-os-capabilities` environment-only failure recurs, record it separately and do not modify unrelated reusable-capability-registry code.

## Current runtime blocker

The active chat container cannot resolve `github.com`, so it cannot acquire this branch or install/run the repository dependency graph. This is an execution-surface limitation, not validation evidence.

## PR / authorization state

No Draft PR has been opened because #1375 explicitly requires the developer loop before Draft PR creation under the Safe Implementation Lane. Merge, auto-merge, issue closure, protected settings/workflows, credentials/IAM, production, live Adobe/provider execution, Notion/Drive/classroom writes, and other external writes remain excluded.

## Rollback

Revert the #1375 commits on `agent/1375-ppux-tutorial0-visual-reference`; no protected branch or external system has been changed.
