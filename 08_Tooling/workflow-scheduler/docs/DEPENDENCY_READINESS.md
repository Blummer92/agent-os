# Dependency Readiness

AOS-RUNNER1D (#1185) adds task-scoped dependency readiness to the governed developer loop without creating a second runner, package manager, or environment-health model.

## Ownership
- Workflow Scheduler owns bounded dependency preparation inside the existing single-issue lifecycle.
- GEX owns `RequiredEnvironmentSpec` and `DependencyReadinessEvidence`.
- Environment health (#972) remains the source of general execution-surface health; readiness requires its current evidence ID on the same execution surface.
- Executor routing remains pure. Providers never install dependencies and never retry a failed preparation through another package manager.

## Required environment contract
`RequiredEnvironmentSpec` binds the ecosystem, package root, runtime requirement, dependency manifest identity, optional lock/constraints identity, install mode, local-project requirements, qualification-only exact pins, approved package source, and required validation-command IDs. Its `required_environment_id` is content-addressed. Only Python/pip and Node/npm are supported by this version.

## Structured source enforcement (#1197 R1)
Manifest and lock hashes prove that a dependency input did not drift; they do not prove that its contents are representable by `RequiredEnvironmentSpec`. Every dependency input is therefore validated for source form before any package-manager command runs.

For Python, requirements-file directives must resolve to the approved source or a declared local project. Alternate and extra indexes, find-links, trusted hosts, direct and bare URLs, VCS references, archive references, environment interpolation, nested `-r`/`-c` indirection, and unrecognised directives are unrepresentable in v1 and fail closed. A root `-e <path>` entry must match a `local_project_requirements` entry with the same canonical path and explicit editable authorization; a declared editable project may not enter as a plain path entry, so editable mode stays structural rather than inferred.

For npm, every lockfile entry must resolve over HTTPS to the approved registry host. Git, remote tarball, `file:`, `link:`, and directory/workspace forms fail closed unless the entry is one of the structurally declared local projects. A malformed, absent, oversized, or unparseable dependency input also fails closed.

The approved source is bound explicitly on the command line — `--index-url` for pip and `--registry` for npm, both derived from `approved_source_identity`. Ambient configuration cannot silently redirect that source: preparation runs with `PIP_CONFIG_FILE`, `NPM_CONFIG_USERCONFIG`, and `NPM_CONFIG_GLOBALCONFIG` set to the null device, so no user, global, or system config file can add an index, mirror, or scoped registry that a command-line argument could not override.

## Install-time code policy and post-preparation integrity (#1197 R2)
Install-time code execution is governed explicitly rather than inherited from package-manager defaults. npm preparation always passes `--ignore-scripts` and `--no-audit`; v1 has no structured authorization path for install scripts, so a genuine required-script case is a `needs-decision` stop rather than a silent widening. Python preparation passes `--only-binary=:all:`, the smallest bounded v1 source-build policy: third-party distributions must arrive as wheels, so no third-party build backend runs at install time, while structurally declared editable local projects still build.

Successful preparation may still run package-manager and build-backend code, so the pre-preparation observation is no longer sufficient evidence. Before READY, provider dispatch, or validation dispatch, the runtime reuses the existing #760 complete workspace-state inspection. Continuation requires that observation to be complete, clean, and still bound to the exact expected source SHA. Preparation-created tracked or source drift, an incomplete observation, or an unavailable complete-state seam all fail closed with `dependency.post-preparation-drift`. No second workspace-integrity mechanism is introduced. Only explicitly authorized source-update behaviour — authorized npm lock generation, which returns `source-update-required` rather than READY — may alter the governed source state.

## Python/pip
Normal repository preparation creates or clears one deterministic virtual environment under the Scheduler workspace parent, outside the Git worktree, then performs one bounded `python -m pip install --only-binary=:all: --index-url <approved source> -r <manifest>` operation through that virtual environment, followed by the explicitly declared local projects. Executor and validation processes inherit the environment only after READY evidence exists. Local projects are installed only when structurally declared; editable installation is explicit. Qualification-only dependencies are exact pins and do not authorize permanent manifest adoption.

When the approved source is unavailable, offline preparation is allowed only with evidence for a current, complete compatible bundle/wheelhouse and a separate bounded runtime location. An ordinary package cache is not proof of dependency closure. Resolved evidence is a hash of canonicalized `pip freeze --all` output from the prepared environment, not an arbitrary installed-package dump in the readiness packet.

## Node/npm
A committed `package-lock.json` requires `npm ci --ignore-scripts --no-audit --registry <approved source>`; there is no automatic fallback to `npm install` and no package-manager substitution. Proven complete compatible cache evidence may permit one `npm ci --offline` operation. `--prefer-offline` is not proof of offline reproducibility. Cache evidence claiming `current-complete` only authorizes that single offline attempt: if the required artifact is genuinely unavailable the command fails, the result is `FAILED`, and there is no retry and no online fallback.

For an authorized new package that has `package.json` but no lock, the only preparation operation is `npm install --package-lock-only --ignore-scripts --no-audit --registry <approved source>`. Success returns `source-update-required`; provider execution and validation remain blocked until the lockfile is committed and the packet is rebound to the new exact source head. Resolved evidence hashes the canonical `npm ls --all --json` tree.

## Failure policy
Stale #972 health evidence, runtime mismatch, missing package manager, manifest/lock/source drift, missing materialized reusable environment, unavailable packages, unavailable source without proven complete offline evidence, stale incompatible cache evidence, and failed preparation all fail closed before provider execution or validation.

No preparation path retries automatically. No path silently changes source identity, package manager, dependency manifest, lockfile semantics, or qualification-only adoption status. A dependency-input change after provider execution may trigger one new readiness check before validation; that second check is not a retry of a failed preparation.

## Evidence
`DependencyReadinessEvidence` binds execution surface and workspace identity; exact source SHA and required-environment ID; package root and ecosystem; runtime/package-manager versions; declared and lock/constraints identities; source/registry and cache state; preparation status and resolved dependency identity; upstream environment-health evidence ID; observed/expiry timestamps, reproducibility level, and bounded reason codes.

READY evidence is reusable only while current and only on the same source, workspace, execution surface, required environment, source identity, runtime, package-manager, manifest/lock, cache, and environment-health identities, with the prepared dependency environment still materialized.

## Regression fixtures
- #935: root `requirements-dev.txt` preparation must make `PyGithub==2.9.1` available in the isolated environment before local pytest/provider execution; otherwise the run blocks before execution. The fixture structurally declares all four actual root editable projects — `src`, `08_Tooling/agent-memory-context-manager`, `08_Tooling/workflow-scheduler`, and `08_Tooling/visual-asset-intake` — as `local_project_requirements`, so they carry identity and editable authorization instead of entering through raw manifest text.
- #1138: `hypothesis==6.165.9` is a qualification-only exact pin; inability to obtain it is a finite blocker and does not mutate `requirements-dev.txt`.
- #1183: package.json without a lock plus unavailable npm registry and no proven complete cache blocks. When network is available, authorized lock generation returns `source-update-required`, after which a committed/rebound head may use clean `npm ci`.

## Non-goals
This change does not add a mirror service, package cache service, provider-specific provisioning, retry service, second Scheduler, second candidate packet, or second environment-health schema. Future ecosystems require separate governed extension.
