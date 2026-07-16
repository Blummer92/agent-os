# Navigation Registry Improvement Plan (Issue #97)

**Status:** Finalized planning + gap analysis. Planning only — no implementation
code, no live-system writes, no new agent, no new duplicate standards.
**Owner:** Integration Manager. **Validation owner:** QA / Test Agent.
**Repository writes:** routed through a GitHub Service Agent Change Request handoff.

## Context

Agents struggle to navigate reliably across Notion, Google Drive, and GitHub. This
plan decides how the Navigation Registry fits into Agent OS *before* implementation,
and guards against the real risk: re-inventing standards, tooling, or agents that
Agent OS already has. The finding below is that the design layer is largely built,
so the remaining work is operational, small, and reuse-first.

## Final Decisions

- **Owner:** Integration Manager (already canonical) — no new agent.
- **Disposition:** reuse-first — extend the data model slightly; create no new
  standard; duplicate no policy text.
- **Phase 1:** GitHub-only, read-only — register the module, apply small schema
  extensions, stand up benchmark fixtures + an offline metric harness.
- **Repository writes:** a GitHub Service Agent Change Request handoff, not direct
  git execution; that agent owns the branch / commit / push / PR-or-no-PR / report.
- **Follow-up issues + the Phase-1 CR:** recommended as text only here; nothing is
  created on GitHub by this planning work.

## 1. Executive Summary

Agent OS already contains a near-complete Navigation Registry **design stack**: the
governing standard, architecture, data model, connector-adapter framework, and
workspace-discovery-service standard (v0.1.0–0.1.1), plus an accepted "Navigation
Registry Read Contract" ADR, a Notion navigation-index standard, a read-only Notion
connector skeleton (`src/navigation_registry/`) with offline tests + CI, a
`notion-navigation-client` read tool, a navigation alias registry, and DMSC
external-repo registry entries. **Integration Manager** already owns navigation
governance and cross-system routing.

Conclusion: **do not create a new agent, a new standard, or a new registry model.**
The gaps are operational: (a) benchmark fixtures + an offline harness to measure the
three required success metrics; (b) small backward-compatible data-model extensions
(a few relationship types and naming fields); (c) Drive and GitHub read-only
connector **skeletons** mirroring the Notion one; (d) an operational cache
destination decision; (e) a read-only discovery runner; (f) a consume-only interface
for the DMSC image/icon sync; and (g) a growing agent-workflow + compute-efficiency
test library. The smallest safe first phase is entirely **GitHub-only and
read-only** — because the three acceptance metrics cannot be measured without
fixtures.

## 2. Current Agent OS Evidence Reviewed

Standards — `01_Shared_Standards/navigation/`: `README.md` (doc order + canonical
authority map), `navigation-registry-standard.md`, `navigation-registry-architecture.md`,
`navigation-registry-data-model.md`, `connector-adapter-framework.md`,
`workspace-discovery-service.md`, `connector-contract-adr.md` (ADR naming the
canonical read-only contract), plus four Notion pilot plans.
Notion: `01_Shared_Standards/notion/notion-navigation-index-standard.md`.
Governance: `AGENTS.md`, `00_Governance/ownership-and-source-of-truth.md`,
`write-authorization-policy.md`, `documentation-dependency-map/navigation-guide.md`.
Registry — `04_Registry/`: `agent-inheritance-registry.md`, `responsibility-matrix.md`,
`navigation-alias-registry.md`, `navigation/` (DMSC external-repo entries),
`module-version-map.md` (**Navigation Registry not listed — gap**).
Overlay: `02_Agent_Overlays/integration-manager.md`.
Tooling / code / CI: `08_Tooling/notion-navigation-client/`,
`src/navigation_registry/connectors/`, `tests/navigation_registry/`,
`.github/workflows/navigation-registry-offline-tests.yml`.
Issue thread: #97 body + three owner comments (Notion Content Completeness Risk;
DMSC image/icon sync dependency; Scalable Phase Testing + compute efficiency).

## 3. Existing Reusable Components (Reuse / Extend / Create / Archive)

| File / asset | Purpose | Disposition | Reason | Duplicate-risk | Next action |
|---|---|---|---|---|---|
| `navigation-registry-standard.md` | Boundaries, two-step lookup, non-authoritative rule | **Reuse as-is** | Complete; owns SoT + write boundary | High if restated | Reference only |
| `navigation-registry-architecture.md` | Schemas, workflow, cache lifecycle, drift, expansion | **Reuse as-is** | Owns component + workflow authority | High | Reference only |
| `navigation-registry-data-model.md` | Entities, field catalog, relationship types, lifecycle, validation | **Extend (small)** | Add a few relationship types + naming fields (§8) | Medium | Backward-compatible additions |
| `connector-adapter-framework.md` | Connector interface, health, error contract | **Reuse as-is** | Platform-independent; covers all systems | High | Reference from adapter specs |
| `workspace-discovery-service.md` | Discovery lifecycle, drift classification, repairs | **Reuse as-is** | Complete design; implement later | High | Feed Phase-4 runner |
| `connector-contract-adr.md` | Names the canonical read-only contract | **Reuse as-is** | Anchors all read paths | High | Cite in adapter specs |
| `notion-navigation-index-standard.md` | Notion Sheet cache standard + overlay mapping | **Reuse as-is** | Notion-specific cache authority | High | Reference only |
| `notion-navigation-client/` | Read-only Notion cache client + tests | **Reuse / extend later** | Working read adapter; route via read contract | Medium | Reference for Drive/GitHub |
| `src/navigation_registry/connectors/*` | Offline read-only connector skeleton | **Extend** | Add Drive + GitHub skeletons | Medium | Phase-2 |
| `tests/navigation_registry/*` + CI | Offline connector contract tests | **Extend** | Add fixtures + metric harness (§10) | Low | Phase-1/2 |
| `navigation-alias-registry.md` | Human alias → reading paths | **Reuse / extend** | Not the operational alias store | Medium | Keep distinct from Alias entity |
| `04_Registry/navigation/` (+ DMSC) | Governed external-repo/system entries | **Reuse / extend** | Home for seeded + DMSC asset entries | Medium | Phase-3 |
| `module-version-map.md` | Module version table | **Extend** | Register Navigation Registry module | Low | Phase-1 |
| Four Notion pilot plans | Live Notion connector pilot design | **Reuse** | Feed the live-connector pilot phase | Medium | Phase-5 |

Concepts **already covered** (do not re-create): source-of-truth boundaries,
read-only default, live verification (two-step lookup), "lookup aid only" rule,
relationship registry, alias registry, duplicate detection, drift detection +
classification, connector adapter framework, workspace discovery service, Notion
navigation index, Notion read-only lookup client, cross-system expansion model.

Duplicate-risk summary: the biggest risk is **restating** boundary/SoT/write rules
that already live in the standard — new docs must reference, not repeat. Second risk
is conflating the human `navigation-alias-registry.md` (reading paths) with the
data-model **Alias entity** (operational resolution) — keep them distinct.

## 4. Ownership Recommendation

**Owner: Integration Manager** — already canonical in `agent-inheritance-registry.md`
and `responsibility-matrix.md`. No new agent is justified (issue constraint +
`agent-creation-policy.md`). Supporting agents stay as the matrix defines: ChatGPT
Orchestrator (triage/routing), GitHub Service Agent (all repo writes), Google
Workspace Automation Engineer (Drive/Sheets tooling), QA / Test Agent (benchmark
ownership + metric validation). System owners retain live-system approval authority.

## 5. Source-of-Truth Boundaries

Unchanged from existing governance — restated as boundaries, owned elsewhere:

- **GitHub** = source of truth for Agent OS governance, standards, overlays, registry
  files, templates, tests, release notes (and this plan).
- **Notion** = teacher planning, readiness status, working knowledge, and the Visual
  Asset / Icon / Prompt libraries (live working-knowledge, **not** GitHub records).
- **Google Drive** = student-facing artifacts (Slides, Docs, worksheets, images).
- **Navigation Registry** = a **cache/lookup aid only**; a lookup result is never
  write authorization, and never overrides which live system owns a record.
- **Live systems** remain authoritative for their own records; cached data is never
  authoritative for content, approvals, readiness, ownership, sharing, permissions,
  grades, or source of truth.

## 6. Navigation Registry Scope (what it owns)

- Cached identifiers, canonical IDs/paths, display names, aliases per system.
- Typed cross-system relationships (edges) for discovery/traversal.
- Owner/routing hints, source-of-truth pointers, freshness metadata.
- Human-review + drift flags and duplicate-risk notes.
- Consume-only interpretation of external sync metadata (e.g. DMSC image/icon).
- The two-step lookup workflow (cache first → live verify before action).

## 7. Out-of-Scope Items (what it explicitly does NOT own)

- Any **write** to Notion, Drive, GitHub, or governed fields (readiness, approval,
  audit, ownership, sharing, source-of-truth). Lookup ≠ authorization.
- Being a source of truth for live content, grades, permissions, or approvals.
- Owning the **DMSC scripts** implementation (consume outputs only; no edits there).
- Owning **instructional judgment** (grade-level language, cognitive load,
  misconceptions, task analysis) — those belong to the instructional overlays (Unit
  Alignment, Teacher Modeling, Instructional Materials Coach) and are *referenced*,
  not absorbed, by nav tests.
- Creating a new agent, a duplicate standard, or a parallel `09_Tests/` tree when
  `tests/navigation_registry/` + `07_Agent_Tests/` already fit.
- Operational cache **writes** without approved ownership + SoT confirmation.

## 8. Proposed Data Model (high level — extensions only)

Reuse the existing canonical entities: Registry Entry, System, Database, Page, File,
Folder, Workflow, Relationship, Alias, Template — with `registry_id`, `canonical_id`,
`display_name`, `owner`, `source_of_truth`, lifecycle states
(Draft→Verified→Cached→Stale→Deprecated→Archived→Deleted), and the validation matrix.
**Extend, backward-compatibly (optional fields / enum additions):**

- **Relationship types** — add the issue's missing types to the existing enum:
  `governed_by`, `stored_in`, `supersedes`, `duplicates`, `handoff_to`,
  `requires_verification_in` (existing: contains, belongs_to, depends_on,
  generated_from, references, linked_to, parent, child, template_for, derived_from).
- **Naming fields** — add `slug`, an `audience` split for student-facing vs
  teacher-facing display names, explicit `provider_id` vs `provider_path`, and
  `previous_paths`/tombstones; distinguish `deprecated` names from `legacy_alias`
  scope in the Alias entity.
- **Asset (image/icon) metadata** — represent as **extension metadata on File
  entries** (or an optional `Asset` entity), using the DMSC minimal schema:
  `stable_identifier`, `source_system`, `status`, `freshness`, `category`,
  `sync_state`. Do **not** add a new core entity (extension-rules compliant).

Naming/alias recommendation: **extend `navigation-registry-data-model.md`**, do not
create a new naming-convention standard. Relationship handling stays in the data
model; traversal examples go to fixtures/examples.

Cross-system navigation model + concrete traversal (reuses the architecture workflow):

```text
lookup starts: classify intent + likely owner
  -> query Navigation Registry (cache) for canonical id/alias/relationships
  -> resolve aliases + typed relationship edges
  -> select canonical target by source_of_truth pointer
  -> check human-review + drift flags
  -> LIVE-VERIFY the target before any write/governed decision
  -> enforce read-only default; produce handoff if a write is needed
```

Example (issue §7.3): Drive Slides deck `derived_from` Notion Lesson page
`belongs_to` Notion Unit page `governed_by` GitHub Instructional Design Standard
`generated_from` GitHub Template. The reverse and the other directional routes
(Drive↔Notion, Notion↔GitHub, Drive↔GitHub) traverse the same edges. Scalability:
Gmail, Calendar, Canvas, Adobe, Figma, LMS connect through the **same** connector
contract + data model via adapters — no core-entity change (the extension model
already specifies this).

## 9. Live Verification Rules (safe cache vs. verify-before-use)

**Safe to cache** (non-authoritative): canonical IDs/paths, display names, aliases,
typed relationships + confidence, owner/routing hints, source-of-truth pointers,
freshness/last-verified timestamps, drift/human-review/duplicate-risk flags,
consumed DMSC asset metadata.

**Requires live verification before use** (any write or governed decision):
readiness/status, approval, ownership, sharing/permissions, source-of-truth changes,
grades, curriculum decisions, any irreversible artifact change, and any resource
whose entry is Stale, flagged `human_review_required`, drift-detected, or missing
`canonical_id`. Duplicate alias/name → block auto-resolution, require review.
Permission/SoT mismatch → stop and escalate to system owner.

**Write actions that remain blocked** regardless of cache: writes to Notion/Drive/
GitHub content, governed fields, sharing settings, source-of-truth records; DMSC repo
edits; operational cache writes without approved ownership; treating any lookup as
authorization.

## 10. Risk Analysis, Success Metrics, and Testing

**Too broad** (over-implementation): duplicating boundary/SoT text across new files;
building live connectors or a discovery runner before fixtures + a cache destination
exist; spawning a new agent or `09_Tests/` tree; treating cached data as
authoritative; over-specifying the DMSC dependency and coupling Agent OS to an
unfinished external format; scope-creeping instructional judgment into the registry.

**Too narrow** (under-implementation): staying Notion-only so cross-system routes
(the actual pain) never work; shipping standards with no measurable fixtures so the
three metrics can't be validated; ignoring drift/duplicate/permission cases; ignoring
incomplete-library readiness and DMSC sync states; no compute-efficiency signal, so
poorly structured navigation keeps wasting tool calls.

**Success metrics** (from #97 §3 — names/thresholds preserved verbatim; owner QA /
Test Agent; reported each validation run + summarized in the plan):

| Priority | Metric | Threshold |
|---|---|---|
| Primary | Navigation accuracy (correct first-attempt canonical resolutions / total) | ≥ 95% |
| Primary | Cross-system resolution success rate (valid multi-hop routes / total) | ≥ 90% |
| Primary | Drift detection effectiveness (precision; recall) | ≥ 90% and ≥ 90% |
| Secondary | Drift detection latency | ≤ 24h |
| Secondary | Measurement consistency | no metric defined inconsistently/duplicated |
| Secondary | Benchmark completeness | 100% of metrics documented with all required fields |

Measurement rules preserved: first-attempt-only success; multi-hop needs every
intermediate relationship valid; drift counts only labeled TP/FP/FN; expected changes
are not drift; false positives reported separately.

**Testing plan** (reuse existing structure — no new tree): unit/contract + fixtures
stay under `tests/navigation_registry/` and offline CI; agent-workflow + compute
tests grow under `07_Agent_Tests/` (matches the existing `.tests.md` pattern).
Coverage to add as **fixtures** (offline JSON, no live data): duplicate aliases,
duplicate display-names, stale cache, renamed/moved resources, missing canonical IDs,
broken/orphan relationships, source-of-truth conflicts, permission drift, invalid
lifecycle transitions, cross-system routes (Drive→Notion→GitHub, Notion→Drive,
GitHub→Notion, GitHub→Drive), unavailable connector, partial discovery run,
incomplete/partial libraries, DMSC sync states (synced/partial/stale/pending/failed/
unknown). Existing tests to keep: the four `tests/navigation_registry/` offline files
+ the `notion-navigation-client` suite. Scalable testing is a **growing capability**,
not a one-time deliverable; each test records a compute profile (tool calls,
retrieval hops, re-searches, handoffs, systems traversed) and recommends **safe,
reversible** GitHub/Drive/Notion structure changes that lower future compute — never
destructive edits, permission changes, or new uncontrolled sources of truth. (Compute
baselines/thresholds are an open blocker — §15.)

**Notion Content Completeness Risk** (issue comment 1): the registry marks Visual
Asset / Icon / Prompt libraries as partial/incomplete, lists missing categories, and
treats missing assets as **readiness risks, not drift** unless the registry *expected*
the asset to exist — distinguishing missing vs incomplete vs stale vs
intentionally-empty vs true drift, and recommending a Notion content-completion
handoff. These become explicit benchmark fixtures.

**DMSC image/icon sync dependency** (issue comment 2): consume-only. Synced metadata
is authoritative for its six fields at its own boundary and lives in Notion (assets)
with the sync pipeline as origin-of-record for sync state; represented in the registry
as File extension metadata / optional Asset entries; incomplete/missing/duplicate/
stale/renamed reported via existing drift + readiness rules. **No DMSC repo changes**
from this issue; only a documented consume interface + fixtures.

## 11. External Pattern Review

No external code copied; conceptual patterns only, each mapped back to existing Agent
OS standards. (Named projects are permissively licensed — Apache-2.0 / MIT — but this
plan adopts **ideas, not dependencies**; verify license + runtime weight before any
actual dependency adoption.)

| Project | Problem it solves | Borrow | Avoid | Maps to | Already have? | Action |
|---|---|---|---|---|---|---|
| LlamaIndex | Connectors, ingestion, indices, retrievers, tool abstractions | Reader/connector abstraction; node vs metadata separation | Vector-store / LLM-in-loop retrieval coupling | Connector Adapter Framework; Data Model | Yes | Adapt idea |
| DataHub | Metadata graph: entities+aspects, URNs, lineage, ownership, freshness | URN-style stable IDs; lineage as typed edges; ownership + freshness first-class | Kafka/GMS infra weight | Data Model ids + Relationship; discovery freshness | Mostly | Adapt idea |
| OpenMetadata | Metadata standard, entity relationships, glossary, data contracts, connectors, MCP for AI | Glossary = alias/naming; data-contract framing; ingestion-framework shape | Full server deployment | Alias entity; Connector Framework; Read Contract | Mostly | Adapt idea |
| Microsoft GraphRAG | Graph construction + relationship traversal for retrieval | Typed relationship traversal; entity resolution for duplicates | LLM-driven graph extraction (overkill) | Relationship model + traversal | Yes | Reuse idea |
| Apache Atlas *(opt)* | Lineage + governance, GUID identifiers | Governance/classification + stable GUIDs | Heavy platform | Data Model + governance | Partial | Investigate later |
| OpenLineage / Marquez *(opt)* | Run/job/dataset lineage events | Run-id + evidence-bundle discovery model | Streaming infra | Workspace Discovery run model | Yes | Reuse idea |
| LangGraph / LangChain *(opt)* | Stateful agent workflows/tools | Tool + handoff abstraction | Framework lock-in | Workflow entity; handoffs | Partial | Investigate later |
| Sourcegraph *(opt)* | Code navigation/indexing | Search-before-build anchors | Indexing infra | `04_Registry/navigation` code-zones | Yes | Reuse idea |
| Obsidian Dataview / Logseq *(opt)* | Local link graph + aliases | Lightweight alias + backlink model | Local-only assumptions | Alias entity | Yes | Ignore |

External risk/dependency note: adopt **patterns**, not runtimes; keep the registry
small and governance-first; nothing above should trigger a new dependency in Phase 1.

## 12. Smallest Safe First Implementation Phase (Phase 1)

Entirely **GitHub-only, read-only, offline** — the highest-leverage minimum, because
the three acceptance metrics cannot be measured without fixtures:

1. **Governance registration** — add "Navigation Registry" (and connector/discovery
   sub-modules) to `04_Registry/module-version-map.md`; `CHANGELOG.md` entry.
2. **Data-model extension (small, backward-compatible)** — add the six missing
   relationship types and the naming fields (§8) to `navigation-registry-data-model.md`
   as optional additions.
3. **Benchmark fixture foundation** — define the fixture schema and seed offline JSON
   fixtures covering the three primary metrics + drift/duplicate/permission +
   cross-system-route + incomplete-library + DMSC-sync-state cases, under
   `tests/navigation_registry/fixtures/`.
4. **Offline metric harness** — a read-only scorer computing Navigation accuracy,
   Cross-system resolution success rate, and Drift detection precision/recall from
   fixtures; wired into the existing offline CI workflow. Owner: QA / Test Agent.
5. **DMSC asset consume-schema** — document the six-field extension-metadata schema +
   fixtures (consume interface only; no DMSC repo work).

Defer to later phases (see §13): Drive + GitHub connector skeletons (Phase 2), seeded
cross-system relationship/alias registry entries + traversal tests (Phase 3),
operational cache-destination decision + read-only discovery runner (Phase 4), live
connector pilots starting with Notion per the existing pilot plans (Phase 5), and the
agent-workflow + compute-efficiency test library growth (Phase 6).

## 13. Recommended Follow-up Issues (text only — none created here)

1. Register Navigation Registry module + version (map + CHANGELOG). *(Phase 1)*
2. Data-model extension: relationship types + naming fields — small extension, **not**
   a new standard. *(Phase 1)*
3. Benchmark fixtures + offline metric harness for the three primary metrics. *(Phase 1)*
4. DMSC image/icon sync **consume interface** schema + fixtures (dependency, not DMSC
   implementation). *(Phase 1)*
5. Google Drive read-only connector skeleton + adapter spec (reuse framework). *(Phase 2)*
6. GitHub read-only connector skeleton + adapter spec (reuse framework). *(Phase 2)*
7. Seed cross-system Relationship + Alias registry entries + traversal tests. *(Phase 3)*
8. Operational cache **destination** decision (governance). *(Phase 4 blocker)*
9. Read-only workspace discovery runner design→build. *(Phase 4)*
10. Notion content-completeness readiness validation cases (Visual Asset / Icon /
    Prompt libraries). *(Phase 3/6)*
11. Agent-workflow + compute-efficiency scalable test library under `07_Agent_Tests/`.
    *(Phase 6, ongoing)*
12. Refine #97 to point at this finalized plan as the accepted baseline.

## 14. GitHub Change Request Scope for Phase 1

Prepared via `03_Templates/prompts/github-change-request.md` as a handoff. The
**GitHub Service Agent** executes the repository write and owns the branch, commit,
push, PR-or-no-PR path, validation, and final GitHub report — this plan recommends the
scope and acceptance criteria only.

- **In scope:** module-version-map + CHANGELOG registration; backward-compatible
  data-model extension; `tests/navigation_registry/fixtures/` + offline metric harness;
  DMSC consume-schema doc + fixtures; this roadmap doc. All read-only, offline, no
  live-system access.
- **Out of scope for CR1:** live connectors, Drive/GitHub adapters, discovery runner,
  operational cache writes, any Notion/Drive/DMSC edits, new agents, new duplicate
  standards.
- **Acceptance:** offline CI green; three metric definitions runnable against seed
  fixtures; `validate-repo-structure.sh` passes; no duplicated boundary/SoT text.
- **Validation evidence:** pytest output for `tests/navigation_registry/`; validator
  output; metric harness sample run on fixtures.

## 15. Open Questions / Blockers

1. Operational cache **destination** + refresh owner not chosen (blocks live/discovery
   phases).
2. Live Notion validation blocked by a platform-side Claude.ai connector-approval bug
   (documented in `notion-navigation-client/README.md`); fixtures/mocks remain the only
   validated path until run locally with OAuth.
3. DMSC image/icon sync output format not finalized (external dependency).
4. Exact Notion page/property names + misconception locations need live verification.
5. Compute-efficiency baselines/thresholds + the safe-modification governance boundary
   are undefined (needed before compute tests can pass/fail).
6. Grade-level language + cognitive-load rubrics are undefined and belong to the
   **instructional overlays**, referenced not owned by the registry — confirm the split.
7. Test-library location: recommend reusing `tests/navigation_registry/` +
   `07_Agent_Tests/` rather than creating `09_Tests/`; confirm with governance.

---

## Standard Agent OS Review Report

- **Files reviewed:** `AGENTS.md`; `00_Governance/ownership-and-source-of-truth.md`,
  `write-authorization-policy.md`, `documentation-dependency-map/navigation-guide.md`;
  `04_Registry/agent-inheritance-registry.md`, `responsibility-matrix.md`,
  `module-version-map.md`, `navigation-alias-registry.md`, `navigation/README.md`,
  `navigation/dmsc-apps-script-bundle.md`; `02_Agent_Overlays/integration-manager.md`;
  `01_Shared_Standards/navigation/` (README, standard, architecture, data-model,
  connector-adapter-framework, workspace-discovery-service, connector-contract-adr);
  `01_Shared_Standards/notion/notion-navigation-index-standard.md`;
  `08_Tooling/notion-navigation-client/` (README, `docs/registry-fit.md`);
  `src/navigation_registry/connectors/` (`base.py`, `notion.py`);
  `tests/navigation_registry/`; `.github/workflows/navigation-registry-offline-tests.yml`;
  `05_Roadmap/`; issue #97 body + 3 comments.
- **Files changed:** this planning work adds `05_Roadmap/navigation-registry-improvement-plan.md`
  (this doc), a `04_Registry/module-version-map.md` registration row, a `CHANGELOG.md`
  entry, and a `00_Governance/markdown-line-limit-exceptions.md` entry for this doc. No
  code, no live-system writes, no new agent, no new standard.
- **Tests run:** `bash 07_Agent_Tests/validate-repo-structure.sh` (structural
  validation of the doc set). No application tests were required for a planning doc.
- **Docs updated:** as listed under Files changed.
- **Unresolved blockers:** see §15.
- **Handoff recommendations:** Integration Manager confirms scope; QA / Test Agent owns
  fixtures + metric harness; GitHub Service Agent executes the Phase-1 CR via the
  change-request template; Google Workspace Automation Engineer supports Drive fixtures
  in Phase 2.
- **Remaining risks:** over-broad implementation duplicating standards or adding
  agents/trees; over-narrow Notion-only implementation that never fixes cross-system
  routing; treating cached data as authoritative; coupling to an unfinished DMSC format.
