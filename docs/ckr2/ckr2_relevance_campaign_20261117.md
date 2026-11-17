# CKR2/CKR6 relevance campaign — 2026-11-17

Base: main 6fdb6be0edc8ae5b920e077532ac534cd5c8fba6 (post-merge CKR11 fix). Owner approved 60 scenarios, 10–15 semantic mutations, and at most 3 bounded repair PRs. This is one Draft PR, not an authorization to merge or mutate Notion.

Historical ledger: Backlog Evidence 1138 notes unrelated LL-202 selected alongside LL-101; Mutation Intelligence C prototype had 16 local tests, five targeted killed mutants and disagreements on machine-generated labels. CI Mutation Evidence 586–597 records earlier CKR11 pagination mutants; do not double-count these.

Actual live A/B on the same PR head: phrase 'CKR6 mutation gate' selected nothing, while 'CKR6 mutation boundary' selected LL-51 with a sufficient, trusted failed-repair reentry result. This patch adds only two exact aliases to the caller-owned capability vocabulary; no arbitrary task-text matching or broader lesson authorization.

Scope: 25 positive selector cases, 25 negative selector cases, 10 synthetic CKR11-to-CKR2-to-CKR6 boundary cases. The 14 isolated source mutants use those same 50 selector assertions and count a mutant as killed only on an assertion failure; compile/import failures are invalid. These are synthetic oracles, not a human-reviewed semantic gold set.

Commands (from 08_Tooling/agent-memory-context-manager):

    PYTHONPATH=src python -m pytest tests/test_ckr2_relevance_campaign.py -q
    PYTHONPATH=src python -m pytest tests/test_ckr2_relevance_mutation_controls.py -q

Acceptance: current-head all 60 cases and 14 mutation controls green, independent QA, human-reviewed 10–20 task relevance gold set before generalizing; CKR6 producer admission and host-use evidence remain separate. Keep explicit false zero-read, provenance, currentness, duplicate conflicts, bounded candidates and contradictory pagination fail closed. Do not infer mutation-score global coverage.