# Agent Tests

Test prompts and structural checks that prove Agent OS is working — that
overlays are followed correctly and the knowledge base stays internally
consistent.

## Two Kinds of Test

1. **Agent compliance tests** (`*.tests.md`, one per overlay) — copy a
   prompt into a session running that agent/overlay and check the
   response against `common-test-checklist.md` plus the file's own
   agent-specific checks. These test the *standards*, not code.
2. **Repo structure tests** (`validate-repo-structure.sh`) — an automated
   script that checks the knowledge base itself: line limits, no
   reintroduced duplication, registry/overlay consistency. Run it with:
   ```
   bash 07_Agent_Tests/validate-repo-structure.sh
   ```

## How to Run an Agent Compliance Test

1. Open the `.tests.md` file matching the overlay you want to verify.
2. Paste each numbered prompt to an agent operating under that overlay.
3. Score the response against `common-test-checklist.md` first, then the
   file's agent-specific expectations.
4. Any unchecked box is a compliance gap — file it as a governance review
   item per `00_Governance/standards-change-control.md`.
