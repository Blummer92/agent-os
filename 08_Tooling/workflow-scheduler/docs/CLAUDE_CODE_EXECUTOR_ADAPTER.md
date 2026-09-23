# Claude Code Executor Adapter

Issue #722 binds one bounded Claude Code CLI invocation to the existing Workflow Scheduler runtime. The adapter is a pure construction/result-normalization layer; it never launches Claude itself.

## Frozen provider contract

- Minimum supported Claude Code version: `2.1.233`.
- Caller supplies the normalized absolute `claude` executable path, observed version, authentication-status boolean, prepared worktree cwd, #934 Implementation Packet, and its two source fingerprints.
- The adapter never reads credentials, environment variables, files, Git state, or network state to infer those values.
- Provider invocation is a tuple, never a shell command.
- Allowed provider tools are only `Read`, `Edit`, `Write`, `Glob`, and `Grep`.
- `Bash`, web tools, and all MCP tools are explicitly disallowed.
- Session persistence, Chrome integration, and slash commands are disabled.
- Maximum turns are bounded at 32.

## Ownership boundary

Agent OS remains responsible for authorization, lease/worktree creation, containment, process execution, timeout/output enforcement, changed-path evidence, independent validation, cleanup, quarantine, Git reconciliation, and GitHub publication. Provider success grants none of those authorities.

The adapter does not create a second executor, scheduler, worktree manager, validation runner, provider registry, retry system, packet schema, or GitHub writer. It is designed for `ClaudeCodeInvocation.argv` to be supplied later as the existing `ConcreteRuntimeConfiguration.executor_argv`.

## Result evidence

`normalize_claude_code_result(...)` consumes already-bounded process output. It retains only terminal classification, byte count, provider error flag, and a digest of an accepted result string. Full provider prose is not persisted as canonical evidence.

Malformed JSON, nonzero exit, timeout, oversized output, provider-reported errors, and common secret markers fail closed. Every result remains non-authorizing: validation, GitHub writes, merge, and automatic retry stay false.

## Live execution boundary

Normal #722 tests are offline and credential-free. They must never invoke Claude. The first live coding-provider invocation remains owned by #935 and requires a fresh candidate-specific packet plus separate exact authorization.

## Rollback

Remove the adapter module, its lazy exports, focused tests, and this document; restore the Workflow Scheduler version records. No provider, credential, worktree, service, or external resource requires cleanup.
