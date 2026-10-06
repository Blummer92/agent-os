# #3305 — Bounded Lessons Learned write route

GitHub owns governance and execution; Notion owns Lessons Learned working knowledge.
ChatGPT Orchestrator routes explicit requests to GitHub Service Agent. This route
consumes `00_Governance/write-authorization-policy.md`; it creates no authority.
#2283 and CKR6 stay read-only and unchanged.

## Requests and scope

After separately authorized default-branch activation, the repository owner may
post one unedited command on open issue #3305:

```text
/agent-os notion-write <reviewed-request-id>
/agent-os notion-write <reviewed-request-id> <exact-page-uuid> <exact-last-edited-time>
```

`catalog.py` holds immutable, reviewed public request payloads keyed by slug.
Admission, reconciliation, transport and readback work for any reviewed entry;
adding an entry requires a governed repository review, not new executor code.
Only `ckr6-execution-path-2026-10-05` is currently registered. This is a finite
catalog route, not free-form routine capture: comment text cannot supply narrative,
property names, destinations, API paths or authorization. Catalog payloads are
write proposals, never a replacement canonical lesson store. Review must exclude
private/student/sensitive information; runtime shape checks cannot prove privacy.

| Writable property | Type |
| --- | --- |
| Lesson Learned | title |
| What Happened | rich_text |
| What To Do Next Time | rich_text |
| Guardrail | rich_text |

Each value is nonempty and at most 512 characters. No ownership, readiness,
approval, audit, provenance, relation, schema, sharing, deletion/archive, bulk or
scheduled operation is admitted. Existing `NOTION_TOKEN` and
`AGENT_OS_LESSONS_LEARNED_DATA_SOURCE_ID` are reused without permission changes.

## Execution and failure behavior

The workflow accepts only created owner issue comments, serializes the destination,
and refuses reruns. Admission checks repository/owner identity, issue, default-branch
workflow context, command and optional exact update binding before credentials.
Execution rereads the current issue/comment before constructing the Notion client.

The writer reuses the canonical binding verifier and read adapter, checks live
property types, and queries at most two exact-title matches. Duplicate or incomplete
results refuse. Identical content returns `unchanged` with zero writes. Changed
content requires the explicit page/revision and a second unchanged read. Create
rechecks absence. One separate POST/PATCH is followed immediately by an exact GET
that verifies page, parent, narrative and preservation of other update properties.

There is no retry. An uncertain create without a returned identity remains
`uncertain`; an update can verify its already-known target after an ambiguous
response. Concurrency with external Notion clients is not atomic CAS. Titles that
have been renamed or semantically similar lessons require human reconciliation.
Public evidence contains only bounded status, identifiers, revision and digest.

## Persistence versus CKR6 use

A successful readback proves persistence only. The existing consumer additionally
needs a stable Lesson ID and revision, recognized Status/Area/Learning Type,
valid Applies To values, guidance, `Surface Before Work? = true`, and a canonical
GitHub Source Link for sufficient evidence. Task signals must match the lesson.
The writer deliberately leaves activation metadata untouched.

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
No second live write is authorized. Current evidence and validation disposition
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
