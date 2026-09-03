# #1372 Governed Pre-PR Runtime Handoff

Status: `needs-capable-runtime`

Issue: #1372 — PPUX-VRL1 — Governed current-application visual-reference library and screenshot ingestion

Authorized branch: `agent/1372-ppux-visual-reference-library`

Base / current branch head at handoff: `c9ae691d4f1cfccb3fc94c262f4af7dabda4b391`

Do not create another branch or Draft PR before the declared developer loop passes.

## Resume objective

Implement the bounded visual-reference library and ingestion/retrieval contract from #1372, reusing the existing PPUX capture-evidence, ArtifactManifest, and visual-asset compatibility seams. Preserve state-local/co-visible evidence authority and fail closed on privacy, staleness, mismatch, or current-vs-recorded UI conflicts.

## First implementation seam inspected

`src/captureEvidence.ts` already provides:

- `CaptureStatus = valid | invalid | blocked | stale | manual-review-required`;
- ArtifactManifest and visual-asset compatibility evidence types;
- privacy, rights, readiness, medium/representation, and staleness eligibility checks;
- exact screenshot/claim state locality;
- no cross-state claim unioning;
- deterministic fail-closed status mapping.

#1372 should reuse these concepts and must not introduce a second asset registry.

## Proposed bounded implementation

Prefer one additive TypeScript module such as `src/visualReference.ts` plus focused tests and minimal integration into `promptIntent.ts` only where needed.

The module should own:

1. application/context-state reference metadata;
2. teacher-supplied screenshot ingestion eligibility where raw upload alone never grants reuse;
3. sanitized-derivative + provenance requirements;
4. retrieval by exact application + context/state + required co-visible claims;
5. current/stale/privacy/manual-review classification using existing vocabulary;
6. explicit current-vs-recorded label conflict detection (minimum regression: `Create new` vs current `Create` -> `Create file`);
7. an evidence-backed presentation directive that uses the selected approved reference and forbids reconstruction or cross-state mixing.

Use privacy-safe metadata/synthetic fixtures only. Do not add the real screenshots from the chat to Git.

## Required acceptance coverage

Cover all 12 scenarios in #1372, especially:

- Your Stuff state isolation;
- Create/Create file conflict;
- Landscape 16:9 state;
- Media vs Elements/Text separation;
- Text Edit/Effects/Animation separation;
- Image Edit/Effects/Animation separation;
- Background filter state;
- Shapes / Rectangle / fill / border separation;
- cross-screenshot co-visibility rejection;
- stale/privacy-unresolved fail closed;
- raw screenshot upload is not reusable by itself;
- explicit manual-review/blocking on historical/current UI conflict.

## Required pre-PR developer loop

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

Repository checks:

```bash
bash 07_Agent_Tests/validate-repo-structure.sh
./scripts/validate-all.sh
```

If Python contract surfaces change, also run their focused tests.

Draft PR creation is blocked until all issue-required developer-loop checks above have actually executed on a capable route. A Draft PR must not be used as the first runtime.

## Current execution-surface evidence

The prior ChatGPT runtime has Node 22.16.0 and global TypeScript 5.8.3 but cannot resolve `github.com`, has no repository checkout, no cached npm dependencies, and does not have package Vitest/Vite available. Therefore it is not a capable #1372 pre-PR runtime under #1278/#1077 even though generic Node/TypeScript execution exists.

## Authorization / exclusions

Authorized: one existing non-protected branch, bounded #1372 implementation, corresponding offline tests/docs, one Draft PR after developer-loop success, then exact-head validation and Ready-for-Review if green.

Not authorized: merge, auto-merge, issue closure, protected settings/workflows, credentials/IAM, production, live Adobe/provider execution, Notion/Drive/classroom writes, raw private screenshot commits, or other external writes.

## Required final report

Return actual branch and final head, files changed, tests/checks run, docs updated, visual-reference record/binding architecture, privacy/sanitization behavior, staleness/currentness behavior, taxonomy, retrieval and conflict behavior, each acceptance scenario, Draft PR state, exact-head validation, blockers, handoffs, rollback, remaining risks, and excluded-surface confirmation.
