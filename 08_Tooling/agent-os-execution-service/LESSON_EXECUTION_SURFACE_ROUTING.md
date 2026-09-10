# Lessons Learned execution-surface routing (#2282)

The issue-start CKR6 tool consumes explicit native ChatGPT Notion capability evidence and selects one read ingress without changing CKR6 semantics.

```text
plan/consume CKR6
  not-needed -> zero native read, zero fallback composition
  retrieval required
    native ChatGPT Notion available -> use the host-supplied native read executor
    native ChatGPT Notion unavailable -> lazily compose the existing #2141 Agent OS reader
      -> lesson_reader_composition.build_lesson_read_executor
      -> existing workflow-scheduler NotionReadOnlyAdapter
      -> existing CKR11 normalization and CKR6/CKR2 selection
```

The route result reports `lesson_read_route`, native capability evidence, whether the fallback was invoked, and fallback availability. The CKR6 result remains the existing result from the #2247 issue-start boundary: selected lesson identity, provenance/currentness projection, dispositions, and `substantial_hypothesis_admissible` are not reimplemented here.

A missing native connector is execution-surface capability evidence only. It does not mean Notion is unavailable and does not permit CKR6 to be skipped. If the fallback reader is also unavailable, the existing CKR6/#2142 capability disposition remains authoritative; specialized-required work fails closed.

No Notion mutation, new client, credential store, schema, selector, database, cache, scheduler, worker, persistence path, or authority is introduced. The fallback uses the existing `AGENT_OS_LESSONS_LEARNED_DATA_SOURCE_ID` composition and `NotionReadOnlyAdapter`; credential/runtime activation remains separately governed.
