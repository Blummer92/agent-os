# Agent OS Notion execution-surface routing (#2282)

Issue #2282 routes bounded read-only Agent OS Notion knowledge retrieval through one of two execution surfaces without creating a second reader or source of truth.

```text
requested typed Notion read
  curriculum-assets | curriculum-content | lesson-planning | lessons-learned
    native ChatGPT Notion available -> host-supplied native read executor
    native ChatGPT Notion unavailable -> existing #2141 Scheduler-backed NotionReadOnlyAdapter
```

The supported content classes are deliberately explicit. A caller cannot ask for an untyped workspace-wide read. Each result retains `content_class` and `source_authority=preserve-source-contract` so downstream code must continue to honor the selected source's existing provenance, currentness, safe-use, and authority rules.

## Lessons Learned / CKR6

The existing `activate_agent_os_issue_start_lessons_tool` remains the CKR6/CKR11 entrypoint. `not-needed` still causes zero native reads and zero fallback composition. When retrieval is required, native connector availability is explicit capability evidence; native absence routes lazily to the existing #2141 Lessons Learned composition. Existing #2142 unavailable/manual-review semantics and #2247 substantial-hypothesis admission remain authoritative.

## Curriculum assets and content

`read_agent_os_notion_knowledge_tool` provides the typed read seam for `curriculum-assets`, `curriculum-content`, and `lesson-planning`. The fallback uses the same canonical Scheduler `NotionReadOnlyAdapter` through class-specific source bindings. Missing source identity fails closed as unavailable; the router does not guess a database or broaden to workspace-wide access.

Class-specific runtime source bindings are:

- `AGENT_OS_CURRICULUM_ASSETS_DATA_SOURCE_ID`
- `AGENT_OS_CURRICULUM_CONTENT_DATA_SOURCE_ID`
- `AGENT_OS_LESSON_PLANNING_DATA_SOURCE_ID`
- `AGENT_OS_LESSONS_LEARNED_DATA_SOURCE_ID`

These names establish the repository-side binding seam only. #2283 owns any live source sharing, credential, secret-storage, runtime injection, or production activation required to populate them.

Each class resolves only its own binding, and a request may shape the bounded query but may never override the fields the binding owns. `action` and `data_source_id` are governed: a query carrying either is rejected before it reaches the adapter, so one content class cannot re-point a read at another class's source identity or swap the bounded `query_data_source` action for the deprecated compatibility action. Page, page-count, and result bounds stay owned by the canonical adapter rather than being re-declared here.

## Authority boundary

All paths are read-only and use `query_data_source`. This implementation performs no Notion mutation and creates no new Notion client, selector, cache, mirror, RAG system, credential store, scheduler, worker, or persistence path. GitHub remains authoritative for Agent OS governance/code/tests. Notion content retains its existing source-specific working/advisory role, and classroom artifact destination rules remain unchanged.
