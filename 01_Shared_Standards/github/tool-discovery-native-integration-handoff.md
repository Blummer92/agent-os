# Tool Discovery Native Integration Handoff

## Purpose

This handoff freezes the remaining #1608 integration requirement after repository conformance landed. It is not a second continuation policy.

## Required native behavior

When an authorized finite Agent OS mission is unfinished and tool/schema discovery succeeds, discovery is an intermediate state. The execution interface must either invoke the next admitted operation in the same interaction or emit an explicit terminal blocker naming the unavailable capability owner and clearing condition.

The interface must not end the turn solely because tool descriptions or schemas were loaded.

## Canonical repository contracts consumed

- `01_Shared_Standards/github/tool-discovery-continuation.md`
- `02_Agent_Overlays/chatgpt-orchestrator.md`
- `07_Agent_Tests/chatgpt-orchestrator.tests.md`
- `tests/test_tool_discovery_continuation_policy.py`

## Live acceptance reproductions

1. #1573: `Complete the handoff` -> GitHub capability discovery succeeds -> next GitHub operation occurs without a new owner prompt.
2. PR #1582: exact failed run is known and workflow/job/log capability is available -> first diagnostic read occurs without a new owner prompt.
3. Unauthorized next operation -> explicit authorization blocker; no mutation.
4. Insufficient discovered capability -> consume #1237 reroute semantics or return the bounded capability blocker.

## #3014 finite repository Actions-variable integration

#3014 adds one native-integration requirement for the connected GitHub capability surface. The repository cannot make an external GitHub MCP provider expose new settings methods, but it can freeze the exact bounded contract that the native integration must implement before Agent OS may treat repository Actions-variable administration as available.

The initial live consumer is #2854. Its current authorized target is:

- repository: `Blummer92/agent-os`;
- resource family: repository Actions variables only;
- variable: `AGENT_OS_LESSONS_LEARNED_DATA_SOURCE_ID`;
- authorization source: #2854;
- live-verified value source: #2854 bounded verification evidence;
- protected-setting mutation authority: separate, content-bound owner authorization only.

### Required operation family

The connected GitHub surface must expose an equivalent of these finite operations:

- `read_repository_actions_variable(repository, name)`
- `set_repository_actions_variable(repository, name, value, authorization_binding, expected_prestate_sha256)`
- `delete_repository_actions_variable(repository, name, authorization_binding, expected_current_sha256)`

Equivalent names are acceptable, but the capability must remain limited to the repository Actions-variable resource family. A generic REST passthrough, generic repository-settings API, arbitrary endpoint path, arbitrary HTTP method, or generic administration tool does not satisfy this handoff.

### Read contract

The read operation must:

1. require an exact repository and exact variable name;
2. return bounded current pre-state;
3. distinguish absent from present;
4. include the exact current non-secret value when present;
5. include a deterministic pre-state digest suitable for write currentness binding;
6. expose no credentials, request headers, OAuth tokens, installation tokens, or unrelated settings;
7. perform no mutation.

For the #2854 canary, the admitted repository/name pair is exactly:

`Blummer92/agent-os / AGENT_OS_LESSONS_LEARNED_DATA_SOURCE_ID`.

### Set contract

The set operation must fail closed unless all of the following are current and exact:

- repository identity;
- variable name;
- requested value;
- explicit authorization binding;
- expected pre-state digest;
- capability health and permission state.

The integration must read current pre-state immediately before mutation, refuse a stale or mismatched digest, perform only the one variable create/update, then immediately read the exact same variable back and prove convergence.

A successful result must report bounded evidence including:

- repository;
- variable name;
- whether the variable previously existed;
- observed pre-state digest;
- mutation attempted: true/false;
- readback value;
- readback digest;
- authorization binding identity;
- rollback operation identity;
- credential value exposed: false.

The operation must not infer authorization from issue labels, readiness, issue type, caller identity alone, or the mere presence of a verified value.

### Delete/restore rollback contract

Delete is available only as bounded rollback for the exact same repository Actions variable and only when bound to the expected current digest and the same content-bound authorization lineage.

Rollback must never become a generic delete-variable capability. If pre-state showed an existing value, the integration must preserve enough bounded non-secret evidence to restore that exact prior value. If pre-state showed absence, rollback may delete only the value created by the admitted mutation.

### Rejection contract

The native integration must reject:

- repository expansion away from the authorized target;
- arbitrary variable names when the authorization binding names one exact variable;
- arbitrary API paths or HTTP methods;
- GitHub Actions secrets;
- environment or organization variables;
- rulesets or branch protection;
- workflow-file mutation;
- repository permissions;
- GitHub App/OAuth/PAT/credential administration;
- IAM/WIF;
- unrelated repository settings;
- stale authorization or stale pre-state;
- missing/ambiguous pre-state;
- mutation without immediate canonical readback.

### #2854 live acceptance

After the connected GitHub surface implements this native capability, the first finite canary is:

1. read `Blummer92/agent-os / AGENT_OS_LESSONS_LEARNED_DATA_SOURCE_ID`;
2. consume current #2854 authorization and current live-verified Lessons Learned source identity;
3. set only that exact variable;
4. immediately read it back;
5. rerun the existing retrieval-required CKR6 canary unchanged;
6. prove bounded CKR6 result evidence is produced;
7. use delete/restore only if rollback is required.

Repository conformance is not live capability proof. #3014 remains externally incomplete until capability discovery on the connected GitHub surface exposes the operation family and the #2854 canary completes without leaving the connected-agent path.

## Authority boundary

This handoff grants no implementation, merge, closure, workflow, protected-setting, credential, production, or external-write authority. It creates no mission database, background worker, retry framework, Scheduler, or second router.

The #3014 section is a native integration contract only. Repository conformance does not itself authorize a protected-setting mutation and does not convert GitHub MCP possession into settings-write authority.
