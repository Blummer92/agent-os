# Production Gates and Compute Rules
These rules prevent unnecessary generation, repeated review, and wasted model calls while protecting classroom-material quality.
## Request Classification
Classify the requested material change before applying the full production gate:
1. **Teacher-directed routine revision** — the teacher explicitly requests a bounded edit to an existing canonical classroom working artifact.
2. **Structural instructional revision** — the change alters or invents curriculum, pacing, learning targets, evidence, assessment criteria, unit structure, or another owner-controlled instructional decision.
3. **New production / release** — the request creates a new student-facing artifact, publishes or releases material, or otherwise depends on unresolved production, source, modeling, evidence, or readiness decisions.
When classification is ambiguous, use the stricter applicable path and route the uncertainty to the owning dashboard or human decision-maker.
## Teacher-Directed Revision Lane
An explicit teacher instruction may authorize a bounded revision of an existing canonical classroom working artifact without requiring `Production Authorized: Yes` or re-running the full new-production gate when all of these conditions are true:
- the target artifact already exists and is the current classroom working file;
- the teacher explicitly requested the specific revision;
- the target is not a protected template or master;
- the revision stays within existing approved instructional intent and does not invent curriculum, pacing, learning targets, assessment criteria, student evidence, unit structure, or another owner-controlled instructional decision;
- no unapproved asset, source, vocabulary, or unsafe content is introduced;
- no governed readiness, approval, source-of-truth, ownership, or audit field is changed;
- no sharing, permissions, publication, ownership, or destination change occurs; and
- the edit is bounded and reversible.
Teacher-directed revision authority is artifact-edit authority only. It does not set or imply `Production Authorized`, `Unit Generation Approval`, packet readiness, source authority, modeling readiness, evidence readiness, classroom-ready status, publication approval, or any other governed state.
If any lane condition fails, or the requested change becomes structural or new production/release, leave the routine revision lane and apply the relevant full production gates.
## Hard Stop Gates
For structural instructional revisions and new production/release, generation is allowed only when all applicable conditions are true:
1. `Source Confidence` is approved.
2. `Unit Readiness` is ready.
3. `Modeling Readiness` is ready for slides or ready for materials.
4. `Evidence Target` is populated for worksheets or assessments.
5. `Blockers` is none.
6. `Production Authorized` is `Yes`.
If any applicable condition fails, the agent must stop, name the blocker, and route to the owning dashboard. It must not create a partial slide deck, worksheet, rubric, packet, or placeholder product under the production path. This hard stop does not convert a qualifying teacher-directed routine revision into new production.
## Blocker Taxonomy
Use one of these blocker labels:
- Missing target
- Missing modeling
- Missing evidence
- Missing pacing
- Missing unit structure
- Low source confidence
- Active blocker
- Ownership conflict
- Human review needed
## Anti-Duplication Rule
Do not re-check a condition already verified by the owning gate unless the source field changed after the last verification timestamp.
## Smallest Context Rule
Agents should read only the approved fields needed for the current lesson and material type. Do not load full unit history, unrelated lessons, or archived notes unless the gate explicitly requires them.
## Reuse Rule
Use approved modeling language, task frames, directions, visuals, templates, and rubric language before generating new equivalents.
## Pipeline Rule
Use the fixed sequence:
1. Classify the request.
2. For a qualifying teacher-directed routine revision, verify the bounded lane, revise the existing artifact, then run material QA.
3. For structural revisions or new production/release, run the applicable gate check, proceed only if ready, then run material QA.
4. Revise only the flagged rubric rows unless the teacher explicitly requests a broader bounded revision.
Agents must not self-orchestrate extra reviewers or repeat checks that belong to another owner.
## Agent Compute Profiles
Pipeline: Unit Alignment → Teacher Modeling → Instructional Materials.
### Unit Alignment Agent
- Read only: standards, learning objectives, assessments, instructional strategies, horizontal alignment, vertical alignment, 12 essential questions.
- Reuse: prior standards maps, approved unit structure, previously verified alignment if source fields did not change.
- Skip: Teacher Modeling, Instructional Materials, student-facing artifact generation.
- Cache/memoize: standards lookup, standards-to-objective map, six-check result, 12-question score.
- Never re-check: a gate already verified by another trusted agent with unchanged source fields.
### Teacher Modeling Coach
- Read only: approved Unit Alignment handoff, learning objective, think-aloud method, component breakdown, visual anchors, error analysis, student-language standard.
- Reuse: approved think-aloud patterns, visual anchor patterns, common-error examples, student sentence frames.
- Skip: Unit Alignment re-verification, materials generation, full unit history.
- Cache/memoize: modeling pattern, common error library, sentence-frame set, visual-anchor pattern.
- Never re-check: Unit Alignment's six checks or 12 essential questions.
### Instructional Materials Coach
- Read only: approved Teacher Modeling handoff, student-language artifacts, content spec, evidence target, approved template, target folder, material-quality rubric.
- Reuse: approved templates, approved assets, modeling outputs, sentence frames, rubric language.
- Skip: Unit Alignment re-verification, Teacher Modeling re-verification, unrelated lessons, archived notes.
- Cache/memoize: template map, asset library, approved language snippets, failed rubric rows.
- Never re-check: Unit Alignment or Teacher Modeling gates once approved and handed off.
## Version
0.3.0
## Changelog
- 0.3.0 adds the bounded Teacher-Directed Revision Lane for existing canonical classroom working artifacts while preserving full gates for structural revisions and new production/release (#1013).
- 0.2.0 added Agent Compute Profiles (read only, reuse, skip, cache/memoize, never re-check) per pipeline agent.
- 0.1.0 initial gates and compute rules.
