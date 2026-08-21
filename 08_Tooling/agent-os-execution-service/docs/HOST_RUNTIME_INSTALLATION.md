# Governed Resume Host Runtime Installation

Issue #1300 (AOS-GCE2C) freezes how the qualified Debian GCE host obtains the
Python runtime behind `/usr/local/libexec/agent-os-governed-resume`. See
`GOVERNED_RESUME_ENTRYPOINT.md` for the entrypoint and composition contracts.

The wrapper runs `python3 -m agent_os_execution_service.governed_resume_entrypoint`,
so the host interpreter must resolve the complete production import graph without
a repository-root `PYTHONPATH`, an editable checkout, or the current working
directory. Four existing distributions carry that graph.

| Distribution | Provides |
| --- | --- |
| `agent-os-execution-service` | `agent_os_execution_service`, `scripts.agent_os_candidate_packet`, `scripts.agent_os_github_issue_provider` |
| `workflow-scheduler` | `workflow_scheduler` (incl. the native extension), `scripts.agent_os_execution_capabilities`, `scripts.agent_os_execution_checkpoint`, `scripts.agent_os_issue_acceptance`, `scripts.agent_os_remote_validation` |
| `agent-memory-context-manager` | `agent_memory_context_manager` |
| `reusable-capability-registry` | `reusable_capability_registry` |

Each `scripts.*` package stays canonical exactly where it already lives: the
distributions declare those directories rather than copying them, and no module
is carried by two distributions. `scripts` is a namespace package, so the two
distributions contribute disjoint subpackages to it. In particular there remains
exactly one canonical checkpoint descriptor loader,
`scripts/agent_os_execution_checkpoint/invocation_descriptor.py`.

`agent-os-execution-service` declares `workflow-scheduler`,
`agent-memory-context-manager`, `PyGithub`, and `requests`; `workflow-scheduler`
declares `PyYAML` and `reusable-capability-registry`. An installation missing any
of them fails with an explicit `ModuleNotFoundError` instead of silently
selecting alternate code.

## Qualified Debian host

The `_clone3_cgroup` C extension is built by the existing `workflow-scheduler`
distribution -- no separate build system is involved -- so the host needs only
the standard toolchain prerequisites before installing:

```sh
sudo apt-get install -y build-essential python3-dev
```

None of these distributions is published to an index, so build them from the
checkout and install from those wheels:

```sh
python3 -m pip wheel --no-deps --wheel-dir /tmp/agent-os-wheels \
  ./08_Tooling/reusable-capability-registry \
  ./08_Tooling/agent-memory-context-manager \
  ./08_Tooling/workflow-scheduler \
  ./08_Tooling/agent-os-execution-service
python3 -m pip install --find-links /tmp/agent-os-wheels agent-os-execution-service
```

The `workflow-scheduler` wheel is platform-tagged and contains the compiled
`_clone3_cgroup` extension; if the toolchain is absent the wheel build fails
loudly rather than producing a Scheduler whose containment is silently degraded.
Build on the qualified host (or on a matching Debian/CPython pair): that wheel is
not portable across interpreters or platforms.

Containment behavior itself is unchanged. `cgroup_v2_containment` and
`clone3_cgroup_launcher` already report "the `_clone3_cgroup` native extension is
not built/importable" as a degraded reason when the extension is missing; #1300
only gives the host a deterministic way to build it.

## Bounded #1238 maintenance route

The tracked `scripts/install-host-runtime` wrapper is the repository-owned host
installation procedure for the separately authorized #1238 maintenance action.
It accepts only an absolute repository checkout and an exact lowercase 40-hex
`EXPECTED_SHA`, requires that checkout to be on `main`, verifies Debian 12 and
passwordless bounded `sudo`, builds the four canonical distributions from that
checkout, force-reinstalls only those wheels, verifies the discovery entrypoint,
governed-resume entrypoint, and `_clone3_cgroup` native extension from outside the
checkout with `PYTHONPATH` removed, then runs `scripts/install-governed-resume`
twice to prove idempotency and root:root `0755` integrity. It emits bounded JSON
with the installed target hash and explicitly reports that no Scheduler execution
was authorized or invoked.

The existing `.github/workflows/agent-os-governed-invocation.yml` may route the
exact repository-owner comment `/agent-os install-host-runtime` on issue #1238 to
this installer only after that workflow change is itself reviewed and merged.
The route reuses the existing `issue_comment`/`refs/heads/main` WIF trust envelope,
existing `agent-os-transport` service account, exact resource tuple
`agent-os-502614 / us-central1-a / agent-os-test`, IAP/OS Login path, and current
GitHub permissions (`contents: read`, `id-token: write`). It adds no IAM/WIF
configuration, no secret, no VM-stop authority, no repository-write permission,
and no Scheduler/lease/retry/execution authority. Comment text is matched exactly
and is never forwarded to the host; the workflow transfers only the tracked
installer whose SHA-256 is pinned in the workflow and checks out the pinned
canonical `main` source SHA on the host before installation.

Because GitHub loads `issue_comment` workflows from the default branch and the
WIF provider is bound to the exact workflow on `refs/heads/main`, this maintenance
route cannot perform a live host mutation while it exists only on a feature
branch. Merge remains separately authorized. Before merge, only offline syntax,
policy, and regression validation can be performed. After merge, one exact owner
comment can perform the already-authorized host installation, after which normal
`/agent-os discover` should be reissued on #1238.

## Proof

`tests/test_host_packaging.py` proves this contract offline. It builds the real
wheels, installs them into an isolated environment that inherits no system site
packages and no editable install, and then imports `agent_os_execution_service`,
`workflow_scheduler`, the native extension, the canonical descriptor loader,
`production_host_composition`, and the entrypoint module from a working directory
outside the repository with `PYTHONPATH` scrubbed -- asserting every resolved
path lies inside the installation and that no repository path is on `sys.path`.
It also runs `python3 -m agent_os_execution_service.governed_resume_entrypoint`
with no arguments and requires the frozen argv contract to reject it, proving the
installed dependency graph loads before argv parsing without any dispatch.

`tests/test_agent_os_host_runtime_install_workflow.py` additionally proves the
maintenance route is bound to owner ID `32861845`, repository ID `1289370915`,
issue #1238, run-attempt 1, `issue_comment`, `refs/heads/main`, and the exact
workflow reference; preserves the existing least-privilege GitHub permissions;
pins the canonical source and installer digest; fixes the one GCE resource tuple;
contains no VM-stop or Scheduler-dispatch path; and keeps the host installer free
of gcloud, arbitrary command evaluation, or a second execution authority.

This proves installation and import/startup only. No Scheduler job, lease
acquisition, or reconstruction is executed by installation. Live GitHub-to-GCE
invocation and replay qualification remain separately governed; host
installation/verification remains #1238 until live evidence is green.

## Rollback

Repository rollback reverts the maintenance route, its bounded installer, tests,
and this documentation. Host rollback removes `/usr/local/libexec/agent-os-governed-resume`
and uninstalls the four Agent OS distributions if the installation itself must be
reverted. Do not delete or alter checkpoint descriptors, ResumePlans,
dependency-readiness evidence, Scheduler leases, workspaces, or audit records.
