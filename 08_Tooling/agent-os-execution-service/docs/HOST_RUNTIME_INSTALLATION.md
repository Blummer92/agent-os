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

## Bounded privileged installation (#1341)

The original #1238 route ran every privileged step against paths the unprivileged
OS Login transport identity could write: wheels it had just built under
`/tmp/agent-os-host-runtime-wheels-1238`, and `install-governed-resume` inside its
own `/tmp` checkout, which carried no digest at all. Any sudoers policy wide
enough to permit that is root-equivalent, because `pip install` and `sh` execute
whatever content is at those paths at the moment root runs them.

`scripts/agent-os-host-install` closes this. It is installed once, out of band, as
`root:root 0755` at `/usr/local/libexec/agent-os-host-install`, and it owns every
privileged step:

1. it refuses unless it is running as root;
2. it accepts exactly `--source-sha <40-lowercase-hex>` and nothing else — the one
   caller-supplied value is never used as a path;
3. it creates `/var/lib/agent-os/host-install-staging` as `root:root 0700`,
   refusing to follow a symlink and verifying ownership and mode after creation;
4. it clones the fixed canonical repository URL itself, requires the requested
   commit to be an ancestor of canonical `main`, checks it out detached, and
   confirms the resulting tree is root-owned;
5. it builds the four distributions and installs those wheels, runs
   `install-governed-resume` twice, and verifies idempotency and `root:root 0755`
   integrity — all entirely inside root-owned staging;
6. an `EXIT`/`HUP`/`INT`/`TERM` trap removes staging deterministically, on refusal
   as well as on success.

`scripts/install-host-runtime` keeps host preflight, the finite reason codes, and
evidence emission, and now holds no privileged step of its own.

Its checks on the helper — non-symlink, regular, executable, `root:root` mode —
are **operator diagnostics, not the security boundary**. That script runs as the
unprivileged transport identity, which could skip it entirely and invoke
`sudo /usr/local/libexec/agent-os-host-install --source-sha <sha>` directly. Their
only job is to turn a misconfigured host into a legible finite reason code. The
security boundary is three things: the no-wildcard sudoers rule, the privileged
helper's own validation of its argv and of its path ancestry, and filesystem
permissions. The same applies to its evidence check — requiring the returned JSON
to be well formed and to report the exact expected source SHA is a consistency
guarantee for the workflow, not a privilege control.

Its capability probe is `sudo -n -l <helper> --source-sha <sha>`, which asks the
policy about the exact invocation it is about to make. The old `sudo -n true`
probe must not be used with this rule: the rule deliberately does not authorize
`/usr/bin/true`, so that probe would report `host-passwordless-sudo-unavailable`
on a correctly configured host.

### Host bootstrap

Both steps require an operator who already holds administrative access to the VM;
neither is performed by the transport identity. Install the helper from a trusted
checkout, then authorize exactly it:

`/usr/local/libexec` is not part of Debian's stock `/usr/local` tree, and GNU
`install` does not create a missing parent, so establish the directory explicitly
first. Its ownership and mode are load-bearing: sudo matches the rule below on the
path string and resolves it at exec time, so a writable or symlinked ancestor
would let the transport identity substitute what root executes.

```sh
sudo install -d -o root -g root -m 0755 /usr/local/libexec
sudo install -o root -g root -m 0755 \
  08_Tooling/agent-os-execution-service/scripts/agent-os-host-install \
  /usr/local/libexec/agent-os-host-install
```

The helper does not take this on trust: at run time, as root, it walks every
component of its own installed path and of the staging parent, and refuses with
`host-privileged-installer-unsafe` or `host-staging-root-unsafe` if any component
is a symlink, is not owned by root, or is group- or other-writable.

The sudoers rule contains no `*` wildcard. Its only variable part is a
fixed-length lowercase-hex character class, so it matches a 40-character commit id
and nothing else — no path, no second argument, no shell payload:

<!-- sudoers-begin -->
```sudoers
# /etc/sudoers.d/agent-os-host-install   root:root 0440
sa_<UNIQUE_ID> ALL=(root) NOPASSWD: /usr/local/libexec/agent-os-host-install --source-sha [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]
```
<!-- sudoers-end -->

Validate with `sudo visudo -c -f <file>` before installing it, and `sudo visudo -c`
after. Resolve `<UNIQUE_ID>` with:

```sh
gcloud iam service-accounts describe \
  agent-os-transport@agent-os-502614.iam.gserviceaccount.com \
  --project agent-os-502614 --format='value(uniqueId)'
```

Do **not** grant `roles/compute.osAdminLogin` instead: it adds the identity to
`google-sudoers`, whose policy is `NOPASSWD:ALL`.

### Why this is no longer root-equivalent

Under the old policy, root executed content chosen by the transport identity. Under
this one, the only thing that identity supplies is a commit id that must already
exist in canonical `main` history — which requires repository write access and
review, not a file write in `/tmp`. Everything root executes is fetched by root
from the fixed canonical URL into a `0700` root-owned directory the identity
cannot read, write, or traverse, and the directory is verified after creation
rather than assumed. There is no window in which a path root will later use is
writable by that identity.

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

The #1341 privileged path adds exactly three host artifacts, and rollback removes
only those:

```sh
sudo rm -f /etc/sudoers.d/agent-os-host-install && sudo visudo -c
sudo rm -f /usr/local/libexec/agent-os-host-install
sudo rm -rf /var/lib/agent-os
```

`/var/lib/agent-os` holds only transient staging, which the installer already
removes on every exit; deleting it is a no-op unless an installation was killed
uncleanly. No package, checkpoint, ResumePlan, lease, or audit record is touched by
this rollback.
