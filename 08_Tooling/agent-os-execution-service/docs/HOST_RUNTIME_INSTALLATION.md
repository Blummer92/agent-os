# Governed Resume Host Runtime Installation

Issue #1300 (AOS-GCE2C) defines how the qualified Debian GCE host obtains the
runtime behind `/usr/local/libexec/agent-os-governed-resume`. The wrapper runs
`python3 -m agent_os_execution_service.governed_resume_entrypoint`; the installed
host therefore needs the four canonical Agent OS distributions and their runtime
dependencies without relying on a repository-root `PYTHONPATH` or editable
checkout.

| Distribution | Provides |
| --- | --- |
| `agent-os-execution-service` | governed discovery/resume entrypoints and provider packages |
| `workflow-scheduler` | Workflow Scheduler runtime and `_clone3_cgroup` |
| `agent-memory-context-manager` | context-manager runtime |
| `reusable-capability-registry` | reusable-capability registry runtime |

The packages remain canonical in their existing locations; #1341 changes only
the privileged host-install boundary, not Scheduler composition or ownership.

## Qualified Debian host

The native Scheduler extension requires the standard Debian build prerequisites:

```sh
sudo apt-get install -y build-essential python3-dev
```

For ordinary development, the four Agent OS wheels may be built from a checkout.
The privileged #1341 path is stricter: root uses a transient root-owned build-tool
directory containing exact hash-pinned `setuptools==83.0.0` and `wheel==0.47.0`,
builds with `--no-build-isolation` and `PIP_NO_INDEX=1`, and performs the final
system install with `--no-index --no-deps`. Runtime dependencies must therefore
already be present on the qualified host; the post-install import proof fails
closed if they are not.

## Bounded #1238 maintenance route

`scripts/install-host-runtime` remains the unprivileged repository-owned wrapper
for the separately authorized #1238 maintenance action. It validates the local
checkout, Debian 12, the exact `EXPECTED_SHA`, the fixed privileged helper, and
the exact bounded sudo capability. All root work is delegated to
`/usr/local/libexec/agent-os-host-install`; returned JSON evidence must report the
same source SHA and explicitly keeps `scheduler_invoked` and
`execution_authorized` false.

The existing `.github/workflows/agent-os-governed-invocation.yml` route remains
bound to the exact repository-owner comment, identity, repository, issue,
`refs/heads/main`, WIF transport, resource tuple, and current permissions. #1341
does not add Scheduler, lease, retry, fallback, VM-stop, repository-write, or
execution authority. The separately authorized workflow diff is limited to the
tracked installer digest and finite refusal mappings; the post-merge source-SHA
bump remains a separate mechanical follow-up already recorded on #1341.

## Bounded privileged installation (#1341)

The original #1238 design would have required root to execute wheels and a shell
script from paths writable by the unprivileged OS Login transport identity. The
fixed helper closes that root-equivalent path:

1. it accepts exactly `--source-sha <40-lowercase-hex>` and nothing else;
2. it must run as root and verifies every component of its own installed path;
3. sudoers authorizes exactly one literal source SHA, so the transport identity
   cannot select an older or different canonical-main commit;
4. it creates `/var/lib/agent-os/host-install-staging` as `root:root 0700`,
   refusing symlinked or untrusted ancestry and re-verifying ownership/mode;
5. it clones the fixed canonical repository URL itself, requires the authorized
   SHA to be an ancestor of canonical `main`, checks it out detached, and proves
   the staged tree is root-owned;
6. it installs only exact hash-pinned Python build tools into root-owned staging,
   disables PEP 518 build isolation, and prevents index resolution during the
   project build and final Agent OS wheel installation;
7. it installs the four locally built Agent OS wheels, runs
   `install-governed-resume` twice, and verifies `root:root 0755` integrity; and
8. an `EXIT`/`HUP`/`INT`/`TERM` trap removes staging on success and failure.

The pinned privileged Python build-tool trust anchors are:

- `setuptools==83.0.0` wheel SHA-256
  `29b23c360f22f414dc7336bb39178cc7bcbf6021ed2733cde173f09dba19abb3`;
- `wheel==0.47.0` wheel SHA-256
  `212281cab4dff978f6cedd499cd893e1f620791ca6ff7107cf270781e587eced`.

Changing those pins is security-sensitive. Debian's signed package channel
remains the trust anchor for `build-essential` and `python3-dev`.

The checks in `scripts/install-host-runtime` are **operator diagnostics, not the
security boundary**. The unprivileged transport identity could skip it entirely
and attempt to invoke the helper through sudo. The actual boundary is the literal
exact-SHA sudo rule, the privileged helper's argv/canonical-main/path-ancestry
checks, root-owned staging, and filesystem permissions.

### Host bootstrap

Live host application is separately gated. An administrator must establish the
trusted helper directory and install the reviewed helper from a trusted checkout:

```sh
sudo install -d -o root -g root -m 0755 /usr/local/libexec
sudo install -o root -g root -m 0755 \
  08_Tooling/agent-os-execution-service/scripts/agent-os-host-install \
  /usr/local/libexec/agent-os-host-install
```

The helper independently verifies that its path and ancestors are root-owned,
non-symlink, and not group- or other-writable.

The sudoers rule must authorize one literal source SHA only. Replace
`<AUTHORIZED_SOURCE_SHA>` with the exact 40-lowercase-hex canonical source SHA
that the workflow will pass as `HOST_RUNTIME_SOURCE_SHA`. Do not use a branch,
prefix, glob, regex, an older `main` commit, or a second allowed SHA.

<!-- sudoers-begin -->
```sudoers
# /etc/sudoers.d/agent-os-host-install   root:root 0440
sa_<UNIQUE_ID> ALL=(root) NOPASSWD: /usr/local/libexec/agent-os-host-install --source-sha <AUTHORIZED_SOURCE_SHA>
```
<!-- sudoers-end -->

This fenced block is meant to be copied verbatim into the sudoers fragment. It
deliberately contains nothing beyond the one authorized rule and its header
comment -- not even an inert commented-out example of the earlier wildcard
matcher -- so nothing pasteable in this file can reintroduce a character-class
match over the source SHA.

Validate the fully substituted file with `sudo visudo -c -f <file>` before
installing it and `sudo visudo -c` afterwards. The active rule's literal SHA must
equal `HOST_RUNTIME_SOURCE_SHA`; a different syntactically valid SHA must be
denied by sudo before the helper starts. Resolve `<UNIQUE_ID>` using the existing
administrative process. Do not grant `roles/compute.osAdminLogin`; that would
reintroduce broad passwordless sudo.

### Why this is no longer root-equivalent

The transport identity cannot choose privileged source code: sudo admits one
literal source SHA, while the helper independently verifies that SHA is on
canonical `main` and fetches it into a `0700` root-owned hierarchy. Python build
backend execution is explicit and hash-pinned; project builds run with build
isolation disabled and no index, and system pip installs only the four locally
built Agent OS wheels with `--no-index --no-deps`. No caller-controlled path is
executed as root, and `PYTHONPATH` is cleared before any privileged `python3`
invocation, so an ambient `PYTHONPATH` cannot shadow the `pip`/`setuptools`
modules root imports; the one intentional exception, the project wheel build,
re-sets it explicitly and only for that command.

## Proof

`tests/test_agent_os_host_privileged_install.py` exercises argv rejection,
privilege dropping, root-owned staging, ancestry, symlinks refusal, off-main and
nonexistent commits, deterministic cleanup, finite reason mappings, and the
unchanged execution-authority invariants. Root-required cases are not weakened or
deleted.

`tests/test_agent_os_host_privilege_regressions.py` adds explicit regressions for
the two independent-review findings: it parses the active sudoers rule and proves
that only a literal source placeholder is admitted, and it proves the privileged
Python build uses the exact backend hashes, `--require-hashes`,
`--no-build-isolation`, `PIP_NO_INDEX=1`, and an offline/no-dependency final
installation.

`tests/test_agent_os_host_runtime_install_workflow.py` continues to prove the
bounded GitHub-to-host maintenance route preserves its identity, resource,
permission, and non-execution invariants. No Scheduler job, admission, lease,
reconstruction, or replay is performed by installation.

## Rollback

Repository rollback reverts the maintenance-route changes, helper, tests, and
this documentation. Live host rollback, when separately authorized, removes only
the bounded host artifacts:

```sh
sudo rm -f /etc/sudoers.d/agent-os-host-install && sudo visudo -c
sudo rm -f /usr/local/libexec/agent-os-host-install
sudo rm -rf /var/lib/agent-os
```

If required, `/usr/local/libexec/agent-os-governed-resume` and the four Agent OS
distributions can be removed under the separately governed host rollback. Do not
delete or alter checkpoint descriptors, ResumePlans, dependency-readiness
evidence, Scheduler leases, workspaces, or audit records. The transient
hash-pinned build-tool directory exists only under staging and is removed by the
installer trap.

## DEVVAL2 governed test runtime

Issue #1436 adds a separate reusable runtime for the fixed DEVVAL1
`remote-validation-suite` identity without changing the governed-resume runtime
above. The published executable is fixed at:

```text
/usr/local/libexec/agent-os-dev-validation-python
```

Its package overlay is fixed at:

```text
/opt/agent-os/dev-validation-runtime
```

The wrapper always executes `/usr/bin/python3` with only that root-owned package
overlay and `PYTHONNOUSERSITE=1`. DEVVAL1 may execute the wrapper but may not
install, update, or select packages.

The separately authorized administrator-run installer is:

```text
08_Tooling/agent-os-execution-service/scripts/install-dev-validation-runtime
```

It has no caller-supplied package/argv surface. It installs only the exact
hash-pinned pytest stack declared inside the script, verifies exact versions
before publication, publishes root-owned non-writable files, and verifies the
final fixed wrapper. The initial pytest identity is `8.3.5`.

Host application is an excluded production mutation and requires separate
authorization after exact-head repository review. Repository implementation does
not authorize running this installer on `agent-os-test`.

### DEVVAL1 binding

After exact branch/SHA checkout, DEVVAL1 requires the fixed wrapper above,
verifies that it can import exactly pytest `8.3.5`, and runs only:

```text
-m pytest tests/agent_os_remote_validation
```

The request cannot choose the interpreter, package set, pytest path, or argv.
Missing or invalid runtime evidence fails closed as `test-runtime-unavailable` or
`test-runtime-invalid`. Scheduler, checkpoint, publication, merge, and execution
authority remain false.

### DEVVAL2 rollback

Repository rollback reverts the DEVVAL2 installer, DEVVAL1 binding, tests, and
this appended documentation. Live rollback, when separately authorized, removes
only:

```sh
sudo rm -f /usr/local/libexec/agent-os-dev-validation-python
sudo rm -rf /opt/agent-os/dev-validation-runtime
sudo rm -rf /var/lib/agent-os/dev-validation-runtime-staging
```

Do not alter `/usr/local/libexec/agent-os-governed-resume`, the four Agent OS
system distributions, Scheduler/checkpoint state, IAM/WIF, OS Login, or unrelated
host state as part of DEVVAL2 rollback.

### DEVVAL2 proof

`tests/test_agent_os_dev_validation_runtime_install.py` proves the installer has a
fixed runtime path, exact hash-pinned package set, no caller-selected package
surface, and bounded rollback targets.

`08_Tooling/workflow-scheduler/tests/test_dev_validation_gce.py` proves DEVVAL1
uses only the fixed test wrapper, contains no package-install/sudo surface, fails
closed for runtime readiness, preserves exact branch/SHA identity, and keeps all
authority flags false.
