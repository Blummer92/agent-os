# Dependency Readiness

AOS-RUNNER1D (#1185) adds task-scoped dependency readiness to the governed developer loop without creating a second runner, package manager, or environment-health model.

## Ownership

- Workflow Scheduler owns bounded dependency preparation inside the existing single-issue lifecycle.
- GEX owns `RequiredEnvironmentSpec` and `DependencyReadinessEvidence`.
- Environment health (#972) remains the source of general execution-surface health; readiness evidence references its evidence ID and exact execution surface.
- Executor routing remains pure. Providers never install dependencies and never retry a failed preparation through another package manager.

## Required environment contract

`RequiredEnvironmentSpec` binds the ecosystem, package root, runtime requirement, dependency manifest identity, optional lock/constraints identity, install mode, local-project requirements, qualification-only exact pins, approved package source, and required validation-command IDs. Its `required_environment_id` is content-addressed.

Only Python/pip and Node/npm are supported by this version.

## Python/pip

Normal repository preparation uses one bounded `python -m pip install -r <manifest>` operation. Local projects are installed only when structurally declared; editable installation is explicit. Qualification-only dependencies are exact pins and do not authorize permanent manifest adoption.

When the approved source is unavailable, offline preparation is allowed only with evidence for a current, complete compatible bundle/wheelhouse. An ordinary package cache is not proof of dependency closure.

## Node/npm

A committed `package-lock.json` requires `npm ci`; there is no automatic fallback to `npm install` and no package-manager substitution. Proven complete compatible cache evidence may permit one `npm ci --offline` operation.

For an authorized new package that has `package.json` but no lock, the only preparation operation is `npm install --package-lock-only --ignore-scripts`. Success returns `source-update-required`; provider execution and validation remain blocked until the lockfile is committed and the packet is rebound to the new exact source head.

## Failure policy

Runtime mismatch, missing package manager, manifest/lock/source drift, unavailable packages, unavailable source without proven complete offline evidence, stale incompatible cache evidence, and failed preparation all fail closed before provider execution or validation.

No preparation path retries automatically. No path silently changes source identity, package manager, dependency manifest, lockfile semantics, or qualification-only adoption status.

## Evidence

`DependencyReadinessEvidence` binds:

- execution surface and workspace identity;
- exact source SHA and required-environment ID;
- package root and ecosystem;
- runtime/package-manager versions;
- declared and lock/constraints identities;
- source/registry and cache state;
- preparation status and resolved dependency identity;
- upstream environment-health evidence ID;
- observed/expiry timestamps, reproducibility level, and bounded reason codes.

READY evidence is reusable only while current and only on the same source, workspace, execution surface, required environment, source identity, runtime, and package-manager versions.

## Regression fixtures

- #935: `requirements-dev.txt` preparation must make `PyGithub==2.9.1` available before local pytest/provider execution; otherwise the run blocks before execution.
- #1138: `hypothesis==6.165.9` is a qualification-only exact pin; inability to obtain it is a finite blocker and does not mutate `requirements-dev.txt`.
- #1183: package.json without a lock plus unavailable npm registry and no proven complete cache blocks. When network is available, authorized lock generation returns `source-update-required`, after which a committed/rebound head may use clean `npm ci`.

## Non-goals

This change does not add a mirror service, package cache service, provider-specific provisioning, retry service, second Scheduler, second candidate packet, or second environment-health schema. Future ecosystems require separate governed extension.
