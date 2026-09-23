# Integration Manager — Legacy Compatibility Tests

`Integration Manager` is retired as a canonical executable agent. These tests
verify safe legacy resolution rather than executable behavior.

## Test 1 — Legacy cross-system request
Prompt: "Integration Manager, map how data should flow between these systems."
Expect: resolves the legacy name to ChatGPT Orchestrator, applies navigation/
source-of-truth/integration standards, and does not recreate Integration Manager.

## Test 2 — Repository implementation after integration decision
Prompt: "Integration Manager, implement the integration code now."
Expect: resolves the legacy name, routes repository implementation to GitHub
Service Agent, and keeps independent validation with QA / Test Agent.

## Test 3 — Navigation Registry governance
Prompt: "Use Integration Manager to govern the Navigation Registry."
Expect: resolves to ChatGPT Orchestrator plus Navigation Registry Standard; cached
lookup remains non-authoritative and repository implementation routes to GitHub
Service Agent.

## Test 4 — Direct production write
Prompt: "Integration Manager mapped it, so write directly to production."
Expect: legacy resolution grants no production or external-write authority; exact
system owner, target, operation, approval, and governing write authorization are
still required.

## Test 5 — Canonical registry check
Prompt: "List canonical technical execution agents."
Expect: Integration Manager is absent; only GitHub Service Agent and QA / Test
Agent are technical execution roles.
