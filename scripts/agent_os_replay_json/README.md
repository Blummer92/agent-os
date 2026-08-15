# Browser Replay JSON Semantic Analyzer

This module turns browser-recorder JSON into a traceable semantic timeline before UX analysis or replay rewriting.

## Contract

1. Load and validate `steps[]`.
2. Preserve original zero-based source indexes.
3. Normalize recorder events into semantic actions.
4. Collapse contiguous text edits and keyboard correction noise when the target is unchanged.
5. Retain click versus double-click as interaction evidence.
6. Extract object identity from stable selector evidence such as `data-testid`.
7. Mark loading/upload recovery actions as non-instructional.
8. Flag generated/account-specific anchors such as URNs, loading placeholders, search-history IDs, and timestamped untitled names as fragile.
9. Build the semantic timeline before making UX recommendations.
10. Never invent selectors or actions that are absent from the replay evidence.

## Supported events

`setViewport`, `navigate`, `click`, `doubleClick`, `change`, `keyDown`, and `keyUp` are normalized directly. Unknown event types are preserved as `unsupported` evidence rather than guessed.

## Evidence preservation

Each semantic action contains `source_indexes` and raw selector/value/URL evidence. Normalization may summarize recorder noise, but it must not discard the link back to the original events.

## Intended sequence

`semantic timeline -> UX analysis -> optional JSON rewrite`

Application-specific UX rules belong outside this parser. The analyzer reports evidence and fragility; it does not decide classroom content or execute browser actions.

## RJ2 rewrite capability

RJ2 consumes the RJ1 semantic timeline and produces a bounded proposed rewrite.

Supported rewrite vocabulary:

- `keep`
- `remove-noise`
- `replace-sequence`
- `move-before`
- `move-after`
- `change-selector`
- `insert-assertion`

Safety rules:

- preserve source-index provenance;
- never invent selectors;
- preserve unknown/unsupported steps;
- preserve click versus double-click;
- do not remove recovery behavior as noise;
- reject instructional-action removal;
- treat reorder requests as unproven without explicit dependency evidence;
- return `proven`, `unproven`, or `rejected` rather than guessing.

RJ2 does not prove Recorder-format conformance or browser replay equivalence.

Canonical sequence:

`RJ1 semantic analysis -> RJ2 rewrite -> RJ3 conformance -> RJ4 replay equivalence`
