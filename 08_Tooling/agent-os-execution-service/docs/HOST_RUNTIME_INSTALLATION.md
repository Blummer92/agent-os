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

This proves installation and import/startup only. No Scheduler job, lease
acquisition, or reconstruction is executed, and no GitHub, network, cloud, IAM,
VM, SSH, or IAP effect occurs. Live GitHub-to-GCE invocation and replay
qualification remain owned by #1239, and host installation/verification by #1238.

## Rollback

Uninstall the four distributions, or discard the environment they were installed
into. No checkpoint descriptor, ResumePlan, dependency-readiness record,
Scheduler lease, workspace, or audit record is touched by installation.
