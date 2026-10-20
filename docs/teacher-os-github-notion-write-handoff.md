# Teacher OS — GitHub-mediated Notion write handoff (proposal only)

## State and trust boundary
An inert, offline-first proposal stage for non-governed teacher planning notes,
lesson candidates, working knowledge, and handoff notes. This is NOT a live
Notion writer or an activated GitHub Actions workflow. The React console cannot
call ChatGPT's connected GitHub MCP, and no GitHub/Notion browser credential
or backend is added. There are zero new secrets, permission changes, workflow
triggers, Notion mutations, VM starts, or production claims.

## Review-only comment grammar

    /agent-os teacher-notion-propose <category> <public-safe-request-slug>

The category is one of planning-note, lesson-candidate, working-knowledge,
handoff-note. The slug is 3–40 lowercase ASCII letters, digits, and hyphens,
with no leading/trailing/doubled hyphen. No free text, Notion IDs, provider
payloads, student records, private data, URLs, properties, or arbitrary
destinations may be placed in this public GitHub comment.

scripts/agent_os_teacher_notion_handoff.proposal builds the proposed comment
and validates a synthetic GitHub issue_comment event for *review only*.
All outputs keep external_write_authorized, execution_authorized,
secret_dispatch_authorized, notion_target_verified, and
notion_write_performed false. Its parser is not wired to any workflow.

## Existing ownership and authorization

- 00_Governance/write-authorization-policy.md provides a bounded routine
  lane but does not override stricter agent overlays or grant generic writes.
- 02_Agent_Overlays/instructional-materials-coach.md blocks Notion writes;
  that agent cannot be treated as an implicitly authorized Notion writer.
- 01_Shared_Standards/notion/notion-record-update-safety.md requires Draft Mode
  unless exact approved scope supports another mode.
- 04_Registry/lp-notion-working-layer-change-request.yaml remains
  proposed-not-authorized. No LP record or schema write may use this proposal.
- The engineering Lessons Learned workflow is destination-specific and MUST
  NOT be repurposed for curriculum or teacher notes.

## Requirements before a live write route can be activated

1. Obtain a separate owner-approved GitHub Change Request and authority for
   workflow, secret, destination sharing, and each excluded external write.
2. Resolve the canonical executing agent and its overlay; obtain explicit
   approval if that overlay forbids the intended write.
3. Freeze exact Notion destination/page/data-source, schema and property
   allowlist, source-of-truth owner, append/update mode, and privacy handling.
4. Use an approved reviewed-content catalog. Public GitHub requests contain
   identifiers only, never arbitrary authored content or student data.
5. Verify GitHub actor identity through a canonical comment readback, not
   only a client claim. GitHub MCP comments may be attributed to an app/bot
   and must not silently count as owner comments.
6. Implement an authenticated, reviewable, separately authorized GitHub
   runner using a least-privilege Notion principal and bounded write adapter.
7. Check idempotency, pre-state/current revision, exact allowed fields,
   immediate canonical readback, ambiguous-result recovery, and audit receipt.
8. Independently validate all security cases before enabling any live trigger.

## Offline tests

From repository root: python3 -m unittest discover -s tests/agent_os_teacher_notion_handoff -v

## Rollback

Remove the review-only UI module and proposal package. No external data
or credentials were created, so no provider rollback is required.
