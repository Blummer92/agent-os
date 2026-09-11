# #2283 GitHub-Controlled Notion Read Path

## Status

Implementation contract for issue #2283. This document records the repository owner's 2026-09-11 decision that sanitized curriculum and Visual Asset Library read results may be returned through the public `Blummer92/agent-os` GitHub surface.

This decision does **not** permit credentials, API headers, sensitive student/private information, unrestricted raw Notion payloads, or other secrets to become public.

## Target architecture

```text
ChatGPT
-> GitHub MCP
-> bounded GitHub issue-comment request
-> admitted GitHub Actions read job
-> Notion read-only API
-> sanitized bounded GitHub result
-> ChatGPT reads the result through GitHub MCP
```

GitHub remains the Agent OS governance/control surface. Notion remains the teacher-planning/current-curriculum and Visual Asset Library working source. Public GitHub result evidence is a request-scoped projection, not a second curriculum or asset source of truth.

## Existing capabilities to reuse

The implementation must reuse existing Agent OS behavior rather than introducing another curriculum or asset system:

- the existing governed `issue_comment` admission pattern for GitHub-triggered work;
- #936 read-only Notion adapter semantics;
- #980 request-sensitive curriculum read planning;
- #975 provider-neutral evidence semantics;
- #973 currentness/conflict disposition;
- #971 relation-first Visual Asset Library semantics;
- #2282 execution-surface routing and fail-closed read boundaries.

## Public result decision

The repository owner accepts public visibility of sanitized curriculum/asset results needed for ordinary Agent OS teacher requests.

Allowed public result content may include bounded fields such as:

- request id and finite request class;
- canonical unit identity;
- curriculum/asset source identity;
- source revision/currentness and provenance;
- semantic/value owner classification;
- bounded teacher-planning or curriculum evidence required by the request;
- bounded Visual Asset Library metadata;
- approved-use, reuse and human-review evidence;
- explicit missing/stale/conflicting/inaccessible state;
- `write_allowed=false` and `production_authorized=false` authority evidence;
- generated timestamp.

The result channel must not contain:

- Notion credentials or tokens;
- authorization/API headers;
- secret values or secret-derived diagnostics;
- sensitive student/private information;
- unrestricted raw page/workspace dumps;
- arbitrary page body content unrelated to the bounded request;
- credentials for GitHub or another provider.

## Request admission

Use a finite repository-owned request vocabulary. Do not execute free-form issue/comment text.

The trigger must validate the trusted actor, canonical repository, expected event, request shape and request class before any secret-bearing step. Unknown request classes, arbitrary URLs, arbitrary Notion ids, shell syntax, extra executable tokens, write actions and workspace-wide search fail closed.

Initial request classes should map to existing curriculum planning semantics, for example:

- `canonical-unit`
- `current-curriculum`
- `visual-assets`
- `teacher-modeling`
- `packet-materials`

Exact request-schema implementation remains subordinate to existing Agent OS request/admission contracts and must not create a second general command protocol.

## Read-only boundary

Only bounded Notion reads required by the existing curriculum/asset path are reachable. No create, update, archive, delete, share, comment, schema mutation, bulk synchronization or workspace-wide crawl is permitted.

The Notion integration/principal must be read-only and shared only to the approved curriculum/asset sources required by the request-sensitive path.

## Visual Asset Library boundary

Preserve relation-first retrieval through canonical curriculum identity. Titles, filenames, prompts, notes or keyword similarity cannot substitute for the governed `Canonical Unit` relation.

Asset existence is not approval. Public result projection must preserve approved-use, reuse, human-review and production-authority boundaries.

## Result projection

The GitHub result must be a sanitized provider-neutral projection, not an unrestricted Notion response. It may be returned on an approved public GitHub evidence surface because the repository owner explicitly accepts public visibility of the sanitized curriculum/asset information.

Sensitive/private/student data is always excluded regardless of this public-result decision.

## Cost boundary

Routine reads must not require persistent GCE. The selected ordinary path uses a standard GitHub-hosted runner only while the repository remains public and the current GitHub billing model continues to make standard hosted runners free for public repositories. Repository visibility or billing-policy drift requires re-evaluation before continued activation.

## Tests required before live activation

1. Only the trusted admitted actor/request reaches the secret-bearing job.
2. Malformed/free-form/arbitrary commands fail closed.
3. Unknown request classes and unapproved targets fail before Notion dispatch.
4. Only approved Notion read operations are reachable.
5. Secret/token/header values cannot enter public output, logs, summaries, artifacts, fixtures or repository files.
6. Sensitive student/private information is rejected from public projection.
7. Relation-first Visual Asset Library behavior survives the round trip.
8. Asset existence never becomes approved use or production authority.
9. Missing/stale/conflicting/inaccessible evidence remains explicit.
10. No GCE dependency, Drive/classroom write, second curriculum source of truth, second scheduler, arbitrary proxy or workspace-wide crawl is introduced.

## Excluded-surface checkpoint

Creating or modifying `.github/workflows/**`, creating/changing GitHub secrets, creating/rotating a Notion integration credential, changing Notion sharing/permissions, and live/production activation remain separately authorization-gated Tier-2 surfaces.

This contract intentionally allows the implementation lineage and review to exist before those excluded surfaces are activated.

## Rollback

Disable/remove the bounded workflow, revoke/remove the Notion credential and its source access, and stop producing request-scoped GitHub result projections. No canonical curriculum or asset data requires rollback because Notion remains the working source.
