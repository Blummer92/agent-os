# Writer-side CKR2 relevance qualification (Draft, #3417 / #4026)

The existing governed Notion writer can persist a valid reviewed catalog entry and verify it with canonical readback, but **persistence is not proof that a future task will find the lesson**. The writer's descriptive properties are projected by CKR11 into a coarse CKR2 vocabulary. A broad `Area` or `Learning Type` can produce false positives while a specific task mechanism remains unmatched.

`scripts/agent_os_notion_lessons_write/relevance_qualification.py` is a **pre-publication review helper**, not a new Notion writer or matcher. For a reviewed **create** catalog entry it synthesizes a local Notion property readback from the exact existing writer fields, passes that shape through the **existing CKR11 normalizer**, and runs the **canonical CKR2 selector** against bounded typed positive and unrelated hard-negative task requests. It refuses missing descriptive metadata, negative false positives, or positive no-matches.

The synthetic Notion Status and Surface Before Work flag are solely for exercising the normalization/selection algorithm; they do **not** imply that a live Notion page has those protected fields, or grant publication, activation, workflow or CKR6 admission authority. Review evidence cannot establish live source currentness or semantic truth. A qualified result means only that these explicit scenarios behaved as expected against this isolated candidate, not that the real live corpus will rank it in the top three. Existing reviewed entries remain unchanged, and this helper is **not wired into the live owner-triggered writer**, because the repository has no approved persistent representation or independently established test cases for every historical entry.

Before using this helper to qualify a new lesson: obtain reviewed issue/PR provenance; author the four finite narratives plus `Area`, `Learning Type`, and `Source Link`; define representative positive and hard-negative typed task signals; execute the review using the in-repository memory-context-manager source on the Python path; inspect false-positive and miss reason codes. If a relevant task cannot match under the current controlled schema, stop for a source-reviewed contract/metadata repair under #4026 rather than force a lesson ID or inject generic keywords. Then use the existing owner-authorized write/readback process and independently evaluate actual CKR6 selection.

Focused command (repo root):

```sh
python -m pytest tests/agent_os_notion_lessons_write/test_relevance_qualification.py -q
```

Not in this PR: catalog auto-generation, a new Notion schema or capability property, protected activation changes, new write endpoints, automatic publication, generic prose matching, runtime CKR2 policy changes, or proof of native host consumption.
