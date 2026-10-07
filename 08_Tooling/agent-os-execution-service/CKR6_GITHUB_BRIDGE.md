# Finite GitHub CKR6 Bridge (#2851)

Issue #2851 adds the separately authorized GitHub-hosted Actions ingress in `.github/workflows/agent-os-ckr6.yml`. The comment form is `/agent-os ckr6 <json-object>`; `ckr6_github_bridge.py` strictly validates the bounded issue-start or failed-repair envelope, then delegates materiality to the existing CKR6 `plan_lesson_preflight` owner. A not-needed request reaches zero Lessons Learned provider reads. Only a request the existing CKR6 plan marks retrieval-required enters the step that exposes the existing `NOTION_TOKEN` and the live-verified repository variable `AGENT_OS_LESSONS_LEARNED_DATA_SOURCE_ID`. The bridge never guesses that source identity, never routes through GCE, and publishes only bounded sanitized CKR6 result evidence. It creates no merge, closure, GitHub-write, Notion-write, or execution authority.

## Result postback (#2851 result-consumption seam)

The step summary and artifact are not readable through the ChatGPT host's GitHub
MCP surface, so the workflow posts the bounded CKR6 result back to the
originating issue as a machine-readable comment. The comment form is the marker
`<!-- agent-os-ckr6-result:v1 -->` followed by one line of canonical compact JSON
(`ckr6_github_bridge.serialize_ckr6_result_comment`); it never starts with
`/agent-os ckr6` and therefore cannot retrigger the ingress. The payload carries
the existing bounded result fields plus the issue-start `handoff_projection`
(the host's consumable context-packet unit) and the requesting comment id for
correlation. When `result.json` is absent, an explicit `manual-review` fallback
is posted instead of silence. The `execute` job holds `issues: write` for this
single postback; no other GitHub write is performed and no authority is created.

## Activation completeness

A merged/callable transport is not evidence that the retrieval-required CKR6 path is usable. Activation evidence for that path must prove the existing live-verified `AGENT_OS_LESSONS_LEARNED_DATA_SOURCE_ID` binding is present and that a finite retrieval-required canary reaches bounded CKR6 result evidence. When the binding is absent or still pending, report `activation incomplete / binding pending`; do not project the retrieval path as usable and do not guess a source identity. This reuses #2854 as the binding owner and adds no second reader, registry, source store, or binding mechanism.
