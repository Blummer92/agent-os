# #3305 — Bounded Lessons Learned write route

GitHub owns governance and execution; Notion owns Lessons Learned working knowledge.
ChatGPT Orchestrator routes explicit requests to GitHub Service Agent. This route
consumes `00_Governance/write-authorization-policy.md`; it creates no authority.
#2283 and CKR6 stay read-only and unchanged.

## Requests and scope

The repository owner may post one unedited command on **any ordinary (non-PR)
issue** in this repository (#3417). The issue's open/closed state is not an
authorization signal: the reviewed catalog entry authorizes content and the owner
comment authorizes the one write. The original #3305-open binding was removed
because closing the implementation issue made the route unreachable.

```text
/agent-os notion-write <reviewed-request-id>
/agent-os notion-write <reviewed-update-request-id> <LL-n> <exact-last-edited-time>
```

`catalog.py` holds immutable, reviewed public request entries keyed by slug.
Each entry is `{target_lesson_id, properties}`:

- **create entry** (`target_lesson_id = None`): the four narrative fields are
  required; reconciliation is by exact title and an existing lesson with
  different content is never overwritten
  (`existing-lesson-requires-reviewed-update-entry`).
- **update entry** (`target_lesson_id = "LL-n"`): any nonempty subset of writable
  fields of that reviewed target. The command must name the same Lesson ID and
  the exact current `last_edited_time`; a stale revision is refused with zero
  writes (`stale-revision-refused`).

New or refined lessons enter **only** through an ordinary reviewed catalog PR by
GitHub Service Agent; admission, reconciliation, transport and readback need no
executor change. Comment text cannot supply narrative, property names, values,
destinations, API paths, targets or authorization. Catalog payloads are write
proposals, never a replacement canonical lesson store. Review must exclude
private/student/sensitive information; runtime shape checks cannot prove privacy.

| Writable property | Type | Class |
| --- | --- | --- |
| Lesson Learned | title | narrative |
| What Happened | rich_text | narrative |
| What To Do Next Time | rich_text | narrative |
| Guardrail | rich_text | narrative |
| Area | select | descriptive (owner decision D1) |
| Learning Type | select | descriptive (D1) |
| Applies To | multi_select | descriptive (D1) |
| Source Link | url (`https://github.com/Blummer92/agent-os/issues|pull/<n>` only) | descriptive (D1) |

Text values are nonempty and at most 512 characters. Select and multi-select
values must already exist as live options; otherwise the write is refused
(`descriptive-option-not-in-live-schema`) because Notion would otherwise create
an option, which is a schema change. **`Status` and `Surface Before Work?` are
activation fields: no catalog entry may name them and the writer never sends
them** (`protected-activation-field-refused`). Descriptive metadata never
activates a lesson. No ownership, readiness, approval, audit, relation, schema,
sharing, deletion/archive, bulk or scheduled operation is admitted. Existing
`NOTION_TOKEN` and `AGENT_OS_LESSONS_LEARNED_DATA_SOURCE_ID` are reused without
permission changes.

Registered entries: `ckr6-execution-path-2026-10-05` (create; the LL-93 canary
narrative) and `ll-93-descriptive-metadata-2026-10-08` (update of LL-93:
Area=Governance, Learning Type=Mistake, Applies To=Notion, Source Link=#3305).
Executing the latter still requires the owner's per-action command and does not
set Status or Surface Before Work?.

## Execution and failure behavior

The workflow accepts only created owner comments on ordinary issues, serializes the
destination, and refuses reruns. Admission checks repository/owner identity, the
non-PR issue, default-branch workflow context, command and optional exact Lesson ID
update binding before credentials. Execution rereads the event's own issue and
comment before constructing the Notion client.

The writer reuses the canonical binding verifier and read adapter, checks live
property types and options, and queries at most two exact-title matches (create)
or two `Lesson ID` unique_id matches (update). Duplicate or incomplete results
refuse. Identical content returns `unchanged` with zero writes. An update requires
the bound revision to equal the live revision and a second unchanged read at the
mutation boundary. Create rechecks absence. One separate POST/PATCH is followed immediately by an exact GET
that verifies page, parent, narrative and preservation of other update properties.

There is no retry. An uncertain create without a returned identity remains
`uncertain`; an update can verify its already-known target after an ambiguous
response. Concurrency with external Notion clients is not atomic CAS. Titles that
have been renamed or semantically similar lessons require human reconciliation.
Public evidence contains only bounded status, identifiers and revision.

## Persistence versus CKR6 use

A successful readback proves persistence only. The existing consumer additionally
needs a stable Lesson ID and revision, recognized Status/Area/Learning Type,
valid Applies To values, guidance, `Surface Before Work? = true`, and a canonical
GitHub Source Link for sufficient evidence. Task signals must match the lesson.
Reviewed entries may now supply Area, Learning Type, Applies To and Source Link
(D1); Status and `Surface Before Work?` remain separately governed, per-action
owner decisions outside this writer.

Offline tests exercise missing metadata rejection and selection with synthetic
owner-supplied metadata; they do not prove live activation. Any live metadata repair
belongs to the Notion field owner, routed by ChatGPT Orchestrator under separate
per-action approval where required. Acceptance is fresh exact-page readback plus
selection by the unchanged CKR6 path, followed by evidence of use in a real task.

## Historical live write evidence

The single authorized canary was consumed on 2026-10-06 at head
`78a02b647f99dcac89a2f9fe1c05a08a9771da4b`:

- [Authorization](https://github.com/Blummer92/agent-os/issues/3305#issuecomment-6026930367).
- [Successful run](https://github.com/Blummer92/agent-os/actions/runs/37544722979):
  one mutation, immediate verified readback, 44 original focused tests passed.
- Page `3f17ac78-3131-81c5-ba2f-f2c98de26ed4`, revision `2026-10-06T23:07:00.000Z`.
- Narrative SHA-256 `44c16eccf067de9cd830e8595795ae7d9e11c31b90117cd2a716b9a29f8a127c`.
- [Durable handoff](https://github.com/Blummer92/agent-os/issues/3305#issuecomment-6027106093).

The canary module, PR-open write trigger and canary-only tests are removed.
Each further live write needs its own owner command under the write policy. Current evidence and validation disposition
remain on #3305 / PR #3358; old-head passes do not validate the revised head.

## Live consumer evidence and owner handoff

[Read-only run 37548974650](https://github.com/Blummer92/agent-os/actions/runs/37548974650)
on `fd22a463158a4f0dab138d11071074c2986d3d9d` verified the same page/revision as
**LL-93**, with matching narrative and zero Notion writes. Existing CKR6 known-ID
retrieval returned `insufficient`, `no-relevant-candidate`, no selected lessons;
normalization rejected `ambiguous-status-vocabulary`.

The bounded live metadata checks found: Status ineligible; Surface Before Work
false; Area and Learning Type invalid/unset; Applies To empty; canonical Source
Link absent/rejected. These are observed gaps, not an authorization to fill them.
ChatGPT Orchestrator must route LL-93 to its Notion metadata owner for a reviewed
eligible Status, meaningful Area/Learning Type/Applies To, a canonical Source Link
and an explicit surfacing decision. Then repeat read-only known-ID and task-relevant
selection. No later execution use is proven until a real task consumes the result.
The temporary read-only verification job is removed from the final workflow.

## Validation and rollback

Run `python -m unittest discover -s tests/agent_os_notion_lessons_write -t . -q`
with `PYTHONPATH=src:08_Tooling/workflow-scheduler/src:.` and PyYAML installed.
The existing focused profile also collects these tests through pytest. Required
exact-head aggregate validation remains independent of focused passes.

Leave the PR unmerged until separately authorized release. Rollback is a reviewed
repository revert or disabling activation; no automatic Notion deletion, archive,
metadata reversal, credential rotation or permission change is allowed.
