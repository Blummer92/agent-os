# CKR5 Failure-to-Lesson Contract

Issue: #1352

## Purpose

`coding_failure_learning.py` is the repository-local Phase 1 seam for turning supplied bounded coding-failure evidence into a deterministic Lesson Learned decision. It performs no live retrieval and no external writes.

The contract composes with the existing CKR2 selector rather than replacing it:

```text
bounded supplied failure evidence
-> reusable-lesson qualification
-> deterministic SHA-256 lesson identity
-> new | recurrence | non-reusable | insufficient | manual-review
-> authority-false Lesson Learned publication proposal
-> optional CodingKnowledgeCandidate projection
-> existing CKR2 selector / Memory Manager handoff
```

## Input boundary

`FailureObservation` accepts explicit normalized evidence only. It carries a source reference, finite failure kind, bounded signature and guidance text, language/ecosystem/capability hints, canonical GitHub references, evidence references, currentness, and explicit reusable-rule / authority-conflict flags.

Raw mappings, unknown executable-payload fields, multiline raw-log-like detail, oversized collections, stale or unverifiable evidence, and conflicting authority fail closed or are rejected before a publication proposal can be produced.

The caller owns evidence gathering. This module does not inspect GitHub, Notion, the filesystem, CI logs, Scheduler state, providers, credentials, or production systems.

## Qualification dispositions

The finite result vocabulary is:

- `reusable-new`
- `reusable-recurrence`
- `non-reusable`
- `manual-review`
- `insufficient-evidence`

Trivial, one-off, transient-environment, flaky-infrastructure, and already-canonical failures are non-reusable by default. A reusable lesson also requires a concrete next-time instruction, guardrail, canonical GitHub reference, and evidence reference.

## Identity and recurrence

Lesson identity is deterministic and provider-neutral. A core SHA-256 identity binds normalized failure kind, signature, ecosystem, capability, and optional library. A full lesson identity also binds the reusable next-time instruction and guardrail.

This permits exact recurrence without fuzzy matching:

- exact full identity -> propose `increment-recurrence`;
- same core with one materially different guidance variant -> new distinct lesson;
- multiple related variants -> `manual-review`;
- stored identity inconsistent with its own bounded semantic fields -> `manual-review`.

Embeddings, vector similarity, model scoring, and unrestricted semantic matching are not used.

## Publication proposal

`LessonPublicationProposal` maps to the existing #1145 Lessons Learned concepts without mutating Notion. It preserves lesson identity, summary, what happened, next-time guidance, learning type, severity, guardrail, owner, source/evidence refs, proposed recurrence count, currentness, canonical GitHub refs, and a conservative `surface_before_work` recommendation.

Every proposal and result has fixed non-authority evidence:

```text
authority_created=false
side_effects_performed=false
notion_write_performed=false
github_write_performed=false
publication_authorized=false
```

These flags cannot be supplied by callers.

## Pre-work projection

Only a current reusable result with a positive `surface_before_work` recommendation may project to the existing CKR2 `CodingKnowledgeCandidate` type. The projection retains canonical GitHub and evidence references and remains non-authoritative working knowledge.

Stale, unverifiable, conflicting, non-reusable, insufficient, or manual-review results do not project to CKR2. CKR2 remains the sole coding-knowledge selection/sufficiency owner and continues to perform no writes.

## External-write boundary

Phase 1 performs zero Notion row writes, schema/view/property changes, GitHub writes, synchronization, Scheduler/background work, provider calls, credential access, or production operations. A later writer remains separately authorization-gated by `00_Governance/write-authorization-policy.md`.

## Validation

Focused tests in `tests/test_coding_failure_learning.py` cover reusable and non-reusable failures, environment/flaky exclusions, human correction, recurrence, distinct guidance, identity conflicts, ambiguity, insufficient evidence, stale/currentness behavior, GitHub authority conflicts, deterministic serialization, bounds, raw-payload rejection, fixed non-authority flags, and CKR2 projection safety.
