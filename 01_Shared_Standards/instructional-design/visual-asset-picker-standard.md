# Visual Asset Picker Standard

## Purpose
Define the governed reuse-selection contract used before Instructional Materials Coach consumes classroom visual references.

## Source-of-Truth Boundary
GitHub owns interpretation and selection policy. Notion owns instructional context and Visual Asset Library working records. This standard does not create a parallel phrase taxonomy in Notion and does not authorize connected reads or writes.

## Semantic Input Boundary
The Asset Picker consumes already-interpreted semantic intent. Natural-language interpretation happens upstream and must preserve meaning rather than exact wording. Equivalent paraphrases must produce equivalent semantic inputs and governed behavior. Do not implement a phrase dictionary or general NLP framework in this layer.

The smallest semantic input must preserve only the dimensions required by the request, including source preference, generation permission, selection authority, visual role/context, and explicit existing-asset references when supplied.

## Reuse-First Default
An underspecified visual request defaults to reusable-asset discovery. It does not imply permission to generate a new image.

`reuse-only` is a hard constraint and prohibits generation handoff. Later explicit teacher instructions override earlier compatible preferences. Hard constraints survive downstream handoff.

## Candidate Eligibility And Ranking
Only reusable candidates supplied by the governed library boundary may be considered. Never infer eligibility, approval, canonical identity, or compatibility from filenames, prompts, notes, comments, or arbitrary prose.

Rank eligible approved candidates in this order:
1. reuse eligibility / approval;
2. unit match;
3. concept match;
4. instructional-role match;
5. explicit teacher context;
6. known same-unit use;
7. coursewide reusable scope;
8. recency only as a weak tiebreaker.

A `Needs Review` candidate may be shown as such but cannot silently enter selected classroom-material references.

## Candidate-First Clarification
When ambiguity can be resolved safely by presenting actual eligible candidates, return candidate references for teacher choice instead of an abstract clarification question. Do not require the teacher to remember Asset IDs, filenames, database records, or internal Agent OS terminology.

## Failure Behavior
- Library discovery failure never becomes permission to generate. Preserve the teacher's active constraints and report that reusable assets could not be checked.
- No eligible candidate returns an explicit visual gap. Generation is a separate downstream handoff only when semantic intent permits it.
- If a previously selected asset becomes unavailable, ineligible, or review-blocked, return control to Asset Picker resolution. Instructional Materials Coach must not silently substitute another asset.

## Downstream Handoff
Preserve stable selected asset identity, source/reference, review/eligibility evidence, associated visual requirement/role, active hard constraints, and relevant search/source context. Instructional Materials Coach consumes these selected references and must not independently reinterpret the original teacher request to choose different assets.

## Ownership Boundaries
This standard does not change #952-#959 responsibilities. It owns reusable-asset discovery/selection policy only. It does not own ingestion, duplicate reconciliation, generation, provider execution, external storage, schema changes, or classroom-artifact generation.

## Authority Boundary
Asset selection is advisory. It grants no production, publication, approval, classroom-use, source-authority, or external-write authority. `Create new` is only a possible downstream handoff when allowed; this standard never performs generation.

## Validation
Use fixture-first offline tests. Prove semantic equivalence across paraphrases, correction/late-override precedence, candidate-first ambiguity, multiple/no/review candidates, library failure, selected-asset invalidation, ranking precedence, and downstream identity/constraint preservation. Tests should prove behavior, not a phrase dictionary.

## Version
0.1.0
