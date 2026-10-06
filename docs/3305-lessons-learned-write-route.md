# #3305 Bounded Lessons Learned Write Route
GitHub controls this finite route; Notion remains the working source of truth.
Authorization is owned by `00_Governance/write-authorization-policy.md` and
Notion field definitions by
`01_Shared_Standards/notion/notion-learning-databases.md`. Neither this document
nor the reviewed catalog creates write authority.

## Owner and field boundary

ChatGPT Orchestrator owns cross-system routing. GitHub Service Agent implements
and executes the separately approved finite transport. The repository owner's
2026-10-06 authorization covers its workflow change and one live canary using
the existing `NOTION_TOKEN` and `AGENT_OS_LESSONS_LEARNED_DATA_SOURCE_ID`.
It excludes merge, closure, credentials/permissions, schema, sharing, archive,
deletion, bulk/scheduled writes, and other production changes.

Only one reviewed, non-sensitive lesson is currently representable:
`ckr6-execution-path-2026-10-05`. Its public narrative is in
`scripts/agent_os_notion_lessons_write/catalog.py`; adding another request needs
a deliberate governed repository change. Comments cannot supply lesson content,
URLs, data-source IDs, property names, API paths, filters or authority flags.

| Writable field | Live type | Ownership |
| --- | --- | --- |
| Lesson Learned | title | Routine lesson narrative |
| What Happened | rich_text | Routine context |
| What To Do Next Time | rich_text | Advisory next-time action |
| Guardrail | rich_text | Advisory caution |

Owner / Agent, Status, Lesson ID, relations, source/provenance-authority,
readiness, approval and audit fields are never supplied or changed by this route.
New records may therefore remain ineligible for CKR6 selection until their
existing separately governed activation metadata is supplied by its owner.

## Normal ingress after default-branch activation

An explicit owner-created comment on open issue #3305:

```text
/agent-os notion-write ckr6-execution-path-2026-10-05
```

The credential-free admission rejects edits, PR conversations, other actors,
targets, branches, workflow identities, reruns and expanded input. Immediately
before credential use, canonical GitHub reads verify the issue is still open
and the exact owner comment remains current.

The client reuses #2283's live Lessons Learned anchor verification and #936
reader for all prechecks/readback. The configured source must equal that live
anchor. The live schema must retain the four narrative types plus read-only
Lesson ID/Status types. One exact-title query is capped at two results/one page;
multiple matches, incomplete pagination and destination/schema drift refuse.

Identical content returns `unchanged` with zero mutation. Differing content
returns `conflict` with sanitized page/revision metadata. An owner may approve
the exact existing-target update with:

```text
/agent-os notion-write ckr6-execution-path-2026-10-05 <page-uuid> <last-edited-time>
```

The writer reacquires that revision immediately before writing. It performs at
most one POST-create or PATCH-properties, immediately GETs the exact returned
target, and verifies identity, destination and all intended fields. Updates also
verify preservation of non-routine properties. Only canonical matching readback
permits `persisted`. A failed/ambiguous write or readback reports `uncertain`;
never automatically rerun it. Creation without an exact receipt stays uncertain.

## Separately approved one-shot canary before merge

Issue-comment workflows require default-branch activation. The same workflow
also admits only the first owner-created Draft PR opening from the fixed
`issue-3305-lessons-write-20261006` branch in this same repository. Before secrets,
it verifies current Draft/open/head identity, open #3305, the exact-head/field-map
canary binding on owner comment 6026930367, and complete Actions history proving
this is the only canary run for that authorized head. Reruns, another PR on that
head, forks, new heads, synchronization, missing binding and expanded scope fail
closed. This is the explicit one-canary authorization, not standing autonomous
row-writing authority. The canary resolves an existing exact target/revision
and uses the same writer for one create/update and immediate readback.

## Evidence, limits and rollback

Contents-read workflow permissions are sufficient; no GitHub write permission
is requested. Secrets exist only in the admitted execute step. No raw Notion
values, provider diagnostics, headers or tokens are published. A bounded summary
and three-day artifact carry disposition, attempt count, exact page/revision,
readback state and a digest of the reviewed intended narrative.

#2283, its adapter and CKR6 retain their read-only contracts. The writer has no
retry, redirect, generic API, scheduler, queue or second knowledge store.
Concurrent external Notion edits remain a risk: Notion offers no atomic
compare-and-swap here. Ambiguous creates require canonical investigation before
any later request; uncertain evidence never authorizes a retry or deletion.

Rollback before activation is to leave the PR unmerged. Disabling a merged route
requires an authorized repository change removing this workflow/finite writer.
No automatic Notion rollback, archive or deletion is permitted. A previously
updated narrative may be restored only through a separately approved exact-target
write with fresh evidence; credentials/sharing/permissions remain untouched.
