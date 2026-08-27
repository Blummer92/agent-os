# Governed Host Runtimes

## Governed resume runtime

Issue #1300 defines the qualified Debian host runtime behind
`/usr/local/libexec/agent-os-governed-resume`. The #1238/#1341 installation
contract remains unchanged: the system `/usr/bin/python3` receives the four
canonical Agent OS distributions and their already-qualified runtime dependencies.
It is an execution runtime, not a development/test environment.

The privileged installer remains
`08_Tooling/agent-os-execution-service/scripts/agent-os-host-install`; its
root-owned staging, exact-source-SHA, bounded sudo, hash-pinned build-tool, and
`--no-index --no-deps` publication rules remain authoritative for governed
resume. DEVVAL2 does not add pytest to that system runtime.

## DEVVAL2 test runtime

Issue #1436 adds a separate reusable runtime for the fixed DEVVAL1
`remote-validation-suite` identity. The published executable is:

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

Host application is an excluded production mutation and therefore requires a
separate authorization after exact-head repository review. Installing repository
code does not itself authorize running this script on `agent-os-test`.

## DEVVAL1 binding

The DEVVAL1 host runner continues to use `/usr/bin/python3` only to execute its
fixed repository-owned orchestration source. After exact branch/SHA checkout it
requires `/usr/local/libexec/agent-os-dev-validation-python`, verifies that the
wrapper can import exactly pytest `8.3.5`, and then runs only:

```text
-m pytest tests/agent_os_remote_validation
```

The request cannot choose the interpreter, package set, pytest path, or argv.
Missing or invalid runtime evidence fails closed as `test-runtime-unavailable` or
`test-runtime-invalid`. Scheduler, checkpoint, publication, merge, and execution
authority remain false.

## Rollback

Repository rollback reverts the DEVVAL2 installer, DEVVAL1 binding, tests, and
this documentation. Live rollback, when separately authorized, removes only:

```sh
sudo rm -f /usr/local/libexec/agent-os-dev-validation-python
sudo rm -rf /opt/agent-os/dev-validation-runtime
sudo rm -rf /var/lib/agent-os/dev-validation-runtime-staging
```

Do not alter `/usr/local/libexec/agent-os-governed-resume`, the four Agent OS
system distributions, Scheduler/checkpoint state, IAM/WIF, OS Login, or unrelated
host state as part of DEVVAL2 rollback.

## Proof

`tests/test_agent_os_dev_validation_runtime_install.py` proves the installer has a
fixed runtime path, exact hash-pinned package set, no caller-selected package
surface, and bounded rollback targets.

`08_Tooling/workflow-scheduler/tests/test_dev_validation_gce.py` proves DEVVAL1
uses only the fixed test wrapper, contains no package-install/sudo surface, fails
closed for runtime readiness, preserves exact branch/SHA identity, and keeps all
authority flags false.
