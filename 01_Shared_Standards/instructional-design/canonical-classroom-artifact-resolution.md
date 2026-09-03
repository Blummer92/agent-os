# Canonical Classroom Artifact Resolution

Issue: #1492

## Purpose

Resolve an existing named classroom artifact from its governed source chain before asking the user to locate, restate, or re-upload evidence that Agent OS can resolve itself.

This standard is a bounded routing contract. It does not change classroom artifact destinations, create a new source of truth, or authorize external writes.

## Canonical source chain

When a request names an existing tutorial or classroom artifact, resolve the planning/workflow identity first from its governed planning source. When fulfillment also requires screenshots, images, recordings, Slides, Docs, worksheets, or other companion artifacts, continue automatically to the governed companion-artifact source.

For the current classroom routing model, the ordinary cross-source shape is:

```text
named tutorial reference
-> Notion planning/workflow context -> Google Drive companion artifacts
-> contextual disambiguation
-> requested artifact
```

GitHub remains canonical for Agent OS governance, standards, overlays, registries, templates, tests, and release notes. This contract does not move classroom artifacts into GitHub.

## Search continuation

A successful planning lookup is not terminal when the requested operation still requires companion evidence.

Likewise, an empty exact-name search is not terminal evidence that a companion artifact does not exist when the resolved canonical context supplies a bounded canonical folder, parent location, asset class, recording name, timestamp window, or other narrow continuation path. Continue through that bounded evidence before declaring the artifact unresolved.

Do not broaden into an unbounded workspace crawl merely because one exact search missed. Search continuation must remain tied to the resolved canonical artifact context.

Do not ask the user to locate or restate an artifact while a bounded governed source-chain continuation remains available.

## Candidate admission and contamination defense

A search result is a candidate, not authority. Admit a companion artifact only when its evidence is compatible with the resolved canonical context.

Disambiguation should use the smallest available set of:

- canonical tutorial/unit identity;
- application identity;
- artifact class and MIME/type;
- expected workflow or instructional domain;
- governed folder/location evidence;
- recording/source filename evidence;
- timestamps or capture-window evidence;
- ordering/provenance evidence;
- source fingerprints or other existing capture bindings when available.

A legacy or semantically similar artifact does not become current merely because its title is close. A plausible filename cannot override conflicting canonical application identity or workflow evidence. For example, a legacy Photoshop burger tutorial must not be substituted for a canonical Adobe Express burger tutorial. When application identity or workflow conflicts, reject the candidate and continue bounded resolution or fail visibly.

## Ordering and instructional identity

Filesystem order, search-result rank, filename sorting, and screenshot chronology alone do not establish instructional identity.

Do not assign `Image 1`, an image count, instructional step identity, or approved sequence merely because screenshots are timestamped or returned in an apparent order. Establish those identities only from canonical/contextual instructional evidence. If that evidence is insufficient, fail closed and preserve the ambiguity for review.

## Failure behavior

If the bounded canonical source chain is exhausted without proving the required artifact identity:

1. report the unresolved evidence explicitly;
2. do not substitute a generic or legacy artifact;
3. do not fabricate UI, controls, filenames, steps, image order, or prompt content;
4. ask for clarification only after the governed resolution path is genuinely exhausted.

A fail-closed result is preferable to a polished artifact with false provenance.

## Authority boundary

This contract authorizes no Notion or Drive mutation, classroom publication, provider execution, repository merge, issue closure, workflow/protected-setting change, credential change, production action, or source-of-truth mutation. Connected-source reads remain governed by their existing capability and authorization contracts.
