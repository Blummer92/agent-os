# Assessment Cross-Unit Validation and Regression Standard

## Purpose
Define the synthetic, noncanonical cross-unit portability contract for #846. This standard verifies that the canonical assessment architecture generalizes across representative Digital Media domains without hard-coding subject assumptions, creating subject-specific agents, redefining upstream contracts, producing classroom assessments, or authorizing external writes.

## Upstream Boundary
This contract consumes #837 assessment-design semantics, #838 blueprint structure, #1192 lifecycle/change-impact/stale-validation behavior, #839 sequencing/student-experience semantics, #841 QA/evidence-review semantics, #842 accepted synthetic Unit 0 integration evidence, and #843 dashboard/workspace behavior by reference.

It does not redefine those contracts. #840 and #844 remain retired/not planned and are not active dependencies. Teacher Decision Studio and Artifact-First Response remain reference behavior where teacher-facing presentation is relevant.

## Content-Domain Rule
Photography, Typography, Graphic Design, Branding, Video Production, and AI Media are content domains, not agents.

A domain label is descriptive fixture context only. Domain names must never directly select an assessment method, evidence requirement, warning, AI-policy rule, scoring rule, dashboard status, repair, or authority state.

Differences between fixtures must arise from supplied synthetic target, claim, observable evidence, task context, scoring/observation need, assignment-specific policy, accessibility/context constraints, and authentic disciplinary practice.

## Synthetic Fixture Rule
Every fixture is explicitly `synthetic_noncanonical: true`. Synthetic target IDs, domain names, task patterns, criteria, and policy examples are regression identities only. They are not approved curriculum targets, canonical unit content, production assessments, classroom materials, or source-of-truth records.

The bounded fixture projection records only portability evidence:
- domain name and synthetic target identity/classification;
- claim and observable evidence;
- selected method plus evidence-based rationale;
- task pattern and scoring/observation need;
- survey/mastery classification;
- supplied assignment-specific policy condition when applicable;
- accessibility/context note;
- expected #1192 preservation/revalidation behavior;
- expected #839 sequencing/student-experience result;
- expected #841 QA disposition;
- expected #843 dashboard/workspace behavior; and
- regression tags.

Fixtures reference upstream behavior instead of recreating upstream schemas.

## Portable Architecture Invariants
Across every synthetic domain preserve:
- #837 target -> claim -> evidence -> method alignment;
- survey/mastery separation;
- authentic direct performance/process evidence when the supplied claim requires it;
- #838 blueprint structure by reference rather than a second blueprint model;
- #1192 stale/change-impact/bounded-preservation semantics;
- #839 dependency, language, cognitive-flow, accessibility, engagement, time, and workload semantics;
- #841 independent QA categories, deterministic disposition semantics, and report-only non-authority;
- #843 dashboard-first workflow, canonical planning-only statuses, nonlinear section editing, warning-to-repair, progressive disclosure, and unrelated-work preservation;
- #842 lesson that Unit 0 fixture content is local synthetic evidence rather than a universal subject rule; and
- fixed false authority for execution, classroom use, grading, readiness, production, publication, external writes, and source-of-truth writes.

## Method and Evidence Selection
Method and evidence follow the supplied target and claim, never the domain name.

Representative synthetic examples:
- Photography may use critique plus performance observation when a supplied claim requires composition choices and explainable camera decisions.
- Typography may require hierarchy/readability evidence when the supplied target concerns information structure; it does not inherit camera handling, equipment inspection, or file-naming checks without target support.
- Graphic Design may use a design artifact plus rationale when the claim concerns visual communication and revision decisions.
- Branding may require audience reasoning and identity-system consistency without inheriting equipment-inspection behavior.
- Video Production may require timeline/performance evidence, continuity, pacing, or editing rationale when supplied by the claim; Photography criteria are not copied merely because both domains use visual media.
- AI Media uses disclosure, prompt/source documentation, or allowed-use checks only when the supplied assignment-specific AI condition makes them relevant.

Two different domains may legitimately share a method when their supplied claims require equivalent evidence. One domain may legitimately use different methods across different targets.

## Cross-Unit Comparison Rules
Compare architecture and evidence validity, not content uniformity.

Valid comparison dimensions include:
- contract completeness;
- target/claim/evidence/method alignment;
- evidence appropriateness and authenticity;
- survey/mastery separation;
- sequencing and student-experience validity;
- workflow/status consistency;
- teacher workload findings;
- warning/repair quality;
- accessibility review;
- lifecycle revalidation/preservation correctness; and
- QA non-authority.

Do not require identical section counts, evidence mixes, time estimates, methods, question formats, terminology, or disciplinary criteria.

## Positive Regression Coverage
The synthetic suite must prove:
- the same dashboard/workspace architecture supports all six required domains;
- method/evidence differences follow supplied target/claim context rather than domain labels;
- Photography and Video may use different evidence criteria when their supplied claims differ;
- Typography can require hierarchy/readability evidence without camera-workflow assumptions;
- Branding can require audience/identity-system judgment without equipment-inspection behavior;
- AI Media applies disclosure/policy checks only from supplied assignment-specific policy;
- bounded local changes preserve unrelated valid sections/units through #1192 semantics;
- canonical #839/#841/#843 outcomes remain portable; and
- at least one valid fixture requires no unit-specific repair.

## Negative Regression Coverage
Fail closed when supplied evidence shows:
- file-naming behavior injected into Typography without target support;
- equipment-inspection behavior injected into Branding without target support;
- Photography criteria copied into Video despite incompatible supplied evidence needs;
- camera-handling assumptions applied to non-camera domains;
- AI-policy requirements copied into a fixture with no supplied assignment-specific AI condition;
- Unit 0 readiness-survey behavior treated as universal mastery evidence;
- domain name directly determining method or evidence;
- dashboard status/workflow semantics changing by domain;
- synthetic fixture identities presented as canonical targets;
- a local regression globally invalidating unrelated units without #1192 evidence; or
- QA/portability status elevating authority.

## Local Change and Preservation
A bounded fixture-local or section-local regression invalidates only the affected object and dependent evidence proven by #1192. Unrelated valid units and sections remain preserved unless supplied lifecycle evidence identifies a shared semantic-root change.

Portability validation does not recompute #1192 impact. It verifies that the supplied preservation/revalidation expectation follows the canonical lifecycle contract.

## Deterministic Portability Result
A fixture is `portable` only when it is explicitly synthetic/noncanonical, target/claim/evidence/method alignment is valid, survey/mastery separation holds, no unsupported domain rule or domain-name selector is present, assignment-specific policy is respected, lifecycle preservation is valid, sequencing and QA expectations remain canonical, dashboard/workspace semantics remain consistent, and fixed authority remains intact.

Any violated hard boundary returns `invalid`. This result verifies composition only and does not replace upstream dispositions.

## Defect Routing
Route a failed portability regression back to the canonical owner rather than redefining behavior here:
- assessment design -> #837;
- blueprint structure -> #838;
- lifecycle/change impact/preservation -> #1192;
- sequencing/student experience -> #839;
- QA -> #841;
- Unit 0 integration-baseline assumptions -> #842;
- dashboard/workspace -> #843.

## Additional-Domain Admission
A future synthetic domain may be added only when it:
1. is explicitly synthetic/noncanonical;
2. supplies target/claim/evidence context rather than subject-name defaults;
3. runs the same portable architecture invariants;
4. separates universal behavior from fixture-local disciplinary content;
5. routes failures to existing owners; and
6. does not create a new agent unless governance separately authorizes a repeatable role.

## Authority and Non-Goals
Cross-unit portability evidence is validation evidence only. QA, portability, dashboard, or fixture status never creates authority.

`execution_authorized`, `classroom_use_authorized`, `grading_authorized`, `readiness_authorized`, `production_authorized`, `publication_authorized`, `external_write_authorized`, and `source_of_truth_write_authorized` remain false.

No production assessment, classroom artifact, real student data, curriculum target mutation, production UI, persistence layer, recommendation engine, Notion/Drive write, workflow/protected-setting change, credential/IAM change, source-of-truth mutation, or standalone Assessment Agent is authorized.

## Version
0.1.0
