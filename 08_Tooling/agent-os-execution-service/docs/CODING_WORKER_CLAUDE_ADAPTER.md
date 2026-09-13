# Claude Code coding-worker adapter — #2319

## Purpose

#2319 supplies the first concrete provider adapter behind the canonical #2318 semantic coding-worker contract. It deliberately reuses the existing #722 Claude Code CLI adapter rather than creating another runner, provider registry, Scheduler path, credential system, validation framework, or lifecycle.

```text
CodingWorkerRequest
-> coding_worker_claude_adapter
-> existing #722 ClaudeCodeInvocation
-> Claude Code runtime
-> existing #722 terminal normalization
-> coding_worker_claude_adapter
-> CodingWorkerResult
```

The bridge itself never launches the provider. Runtime/process execution remains owned by the existing governed execution path.

## Request translation

The bridge accepts one canonical `CodingWorkerRequest`, the already-owned #934 Implementation Packet material, and caller-supplied #722 provider/runtime evidence. The provider prompt contains the implementation packet plus the canonical request and requires the provider's `result` string to contain a complete canonical `CodingWorkerResult` JSON object.

Provider/model name, executable path, observed version, authentication evidence, CLI flags, output framing, and turn bounds remain adapter/runtime details and do not enter the #2318 wire contract.

The current #722 Claude route disables `Bash`, web tools, and MCP tools. Therefore the canonical `test` operation is explicitly unsupported by this adapter and fails closed so #918/#1401 capability routing can choose a capable surface. The adapter also rejects provider claims that commands or tests ran on this route.

## Result translation

The bridge first applies the existing #722 native terminal-result normalization. Native timeout, non-zero exit, provider errors, malformed output, oversized output, or rejected output become canonical `execution-failure` evidence without retaining provider prose.

On native success, the provider `result` string must reconstruct as an exact `CodingWorkerResult`. The adapter then verifies request ID, task ID, repository, base SHA, and workspace identity against the originating request.

Reported inspected/changed paths are rechecked against the canonical allowed/forbidden path envelope. Any mismatch is preserved as canonical `scope-violation` evidence rather than accepted because the provider reported success.

All authority fields remain fixed false by the canonical result constructor. Provider success cannot authorize validation, Ready-for-Review, merge, issue closure, or external writes.

## Contract sufficiency findings

The first adapter demonstrates that #2318 is sufficient for the core semantic seam without provider-specific additions:

- request identity/currentness/scope bindings are sufficient to bind a native invocation;
- provider details remain isolated outside the core request/result schema;
- the canonical result can represent provider success, execution failure, and scope violation without a provider-specific status vocabulary;
- capability mismatch belongs to existing execution-surface routing rather than the worker contract;
- no new positive authority fields are required.

One important limitation is intentionally outside the contract: the existing bounded Claude adapter cannot execute shell commands or tests. That does not require a #2318 schema change; it requires routing to a surface whose declared capabilities satisfy the requested operation.

## Canary boundary

Repository fixtures can prove deterministic translation and normalization without a live provider. #2319's real-runtime canary still requires a separately authorized host/runtime invocation with a supported Claude Code executable, authenticated principal, network/provider access, isolated workspace, and fresh request/source identities.

A live canary must remain one bounded task and must not grant merge, issue-closure, workflow/protected-setting, credential/IAM, production, or external-write authority. Independent Agent OS validation remains required after any provider-produced repository change.

## Validation

Focused coverage is in `tests/test_coding_worker_claude_adapter.py` and should be run with the canonical #2318 contract tests and the existing #722 Claude adapter tests before exact-head aggregate validation.
