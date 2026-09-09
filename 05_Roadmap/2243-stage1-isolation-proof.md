# #2243 Stage 1 Isolation Proof

Status: Stage 1 audit complete enough to gate topology; topology is **not yet proven safe** for blanket full-suite parallelism.

Audited main: `c716f7e777a02c9dc3e0bb6f2287864c1f0af712`.

## Decision

Do not enable blanket `pytest -n auto`, cross-suite job fan-out, or other aggregate topology changes yet.

The repository has substantial isolation-positive evidence, but Stage 1 also found process-local and shared-working-tree patterns whose behavior must be preserved explicitly before full-suite parallel execution can be called safe. The safest next implementation stage is Stage 2 bootstrap dedup; Stage 3 remains gated.

## Fixture inventory

Exact-basename runtime `conftest.py` files audited: six.

1. `tests/conftest.py`
   - function-scoped `TemporaryDirectory` fixture;
   - repository/standards path fixtures are read-only;
   - sample files are created under the per-test temporary directory;
   - collection hook only adds markers.
   - Isolation assessment: positive.

2. `tests/agent_os_issue_acceptance/conftest.py`
   - process-local `sys.path` insertion only.
   - Isolation assessment: positive across separate worker processes; no filesystem/service mutation.

3. `tests/agent_os_execution_interface/conftest.py`
   - process-local source-directory `sys.path` insertion only.
   - Isolation assessment: positive across separate worker processes.

4. `tests/agent_os_cloud_build_provider/conftest.py`
   - process-local source-directory `sys.path` insertion only.
   - Isolation assessment: positive across separate worker processes.

5. `08_Tooling/agent-memory-context-manager/tests/conftest.py`
   - function-scoped autouse monkeypatch of `os.getpid` for one named test;
   - pytest `monkeypatch` restores state after the test.
   - Isolation assessment: positive across worker processes.

6. `08_Tooling/instructional-materials-coach/tests/conftest.py`
   - function-scoped autouse fixture snapshots the working-directory default lessons directory, then removes/fails on leaked files;
   - this is intentionally a shared-working-tree sentinel.
   - Isolation assessment: safe for current sequential execution; blanket same-tree parallelism is not yet proven because concurrent tests/workers could race while snapshotting or attributing leaked files in the same default directory.

A GitHub filename search also returns `03_Templates/python-project-template/test_conftest.py`; that is a template test module, not a runtime `conftest.py`. Tracking discrepancy: #2249.

## Ports, sockets, and shared services

Repository search found no direct fixed-port/socket-binding pattern for the aggregate test surface. No evidence was found of a shared local server fixture that would inherently collide across workers.

This is encouraging negative evidence, not proof that every subprocess path is service-free.

## Environment mutation

Environment mutation is common, but the audited test examples use pytest `monkeypatch.setenv`/`delenv`, including environment-contract, execution-interface, execution-service, and instructional-materials tests. `monkeypatch` is function-scoped and restores process environment after each test.

Assessment: positive for process-based xdist isolation. It does not by itself prove safety for arbitrary thread-based execution, which is not proposed here.

## Ordering dependencies

Repository search found no `pytest-order`/explicit order markers and no direct `os.chdir`/`monkeypatch.chdir` usage in the aggregate test surface.

Assessment: no explicit ordering contract found. Absence of an order marker is not sufficient proof against hidden shared-state ordering, so the shared-working-tree sentinel remains a gate.

## Shared filesystem/state mutation

Positive patterns:
- extensive `tmp_path` / `tmp_path_factory` usage;
- subprocess-heavy repository-state tests generally construct synthetic repositories under temporary paths;
- root shared fixtures create sample files under per-test temporary directories.

Risk pattern:
- instructional-materials autouse fixture deliberately observes and cleans a default directory resolved from the process working directory. Parallel workers share that checkout path unless explicitly isolated, so attribution/cleanup can race.

Module-scoped packaging fixtures in `08_Tooling/agent-os-execution-service/tests/test_host_packaging.py` build wheels and an isolated venv under `tmp_path_factory`. xdist workers would receive separate pytest temp roots, so correctness collision risk is low, but each worker that collects the module can repeat expensive wheel/venv bootstrap. This is a compute-amplification risk even if correctness is preserved.

## Subprocess behavior

The suite is subprocess-heavy. Important patterns include:
- git/repository-state helpers executing against explicit temporary `cwd` repositories;
- host-packaging tests building wheels, creating a venv, and invoking pip offline under pytest temporary roots;
- validation-runner tests and execution-service tests spawning fixed argv with explicit cwd/env.

Assessment: no single subprocess pattern proves a correctness collision, but worker fan-out can multiply expensive package-build/venv subprocesses. Topology design must account for this rather than assuming CPU parallelism is free.

## Coverage behavior

Canonical `scripts/validate-all.sh` applies coverage only to the workflow-scheduler suite:

`python -m pytest tests --cov=src/workflow_scheduler --cov-report=term`

No Stage 3 change may drop or weaken this. Cross-suite process parallelism could keep this suite as one isolated sequential command and therefore preserve its current coverage semantics. Intra-suite xdist for workflow-scheduler is not approved by this audit because coverage equivalence under the chosen worker configuration has not yet been demonstrated.

## Deterministic failure reporting

`validate-all.sh` currently executes suites one by one through `run_check`, recording for each suite:
- suite name;
- exact command;
- exit code;
- elapsed duration;
- failed-package entry;
- aggregate overall status and exit code.

Any Stage 3 topology must reproduce this deterministic per-suite evidence even if execution becomes concurrent. Raw interleaved worker output is not an acceptable replacement.

## Stage 1 gate result

**Partial pass / Stage 3 remains gated.**

Safe evidence established:
- six runtime conftests inventoried;
- no fixed-port/socket fixture found;
- environment mutation is predominantly pytest-monkeypatch scoped;
- no explicit test-order or cwd-mutation mechanism found;
- broad temporary-directory isolation is present;
- existing failure/timing evidence contract is understood.

Unresolved before blanket topology change:
1. prove or isolate the instructional-materials default-directory sentinel under concurrent workers;
2. measure/contain module-scoped packaging bootstrap duplication under worker fan-out;
3. demonstrate workflow-scheduler `--cov` equivalence for any proposed intra-suite process parallelism;
4. design deterministic per-suite output capture before cross-suite concurrent execution.

Therefore Stage 2 bootstrap dedup may proceed independently, while Stage 3 must not be enabled yet.

## Stage 2 evidence already confirmed

`requirements-dev.txt` already installs `-e ./08_Tooling/reusable-capability-registry`, while `.github/workflows/agent-os-validation.yml` subsequently installs `-e "./08_Tooling/reusable-capability-registry[test]"` in both focused and aggregate bootstrap. This is a real duplicate package installation, but removing it changes workflow bootstrap and remains separately authorization-gated by #2243.

`pytest-xdist>=3.8.0` is already installed by `requirements-dev.txt`; presence of the dependency is not permission to enable it.

No removal decision has been made for `black`, `flake8`, `mypy`, or `isort`; indirect test consumption still needs a bounded executable-consumer audit before Stage 2 removes any of them.

## Rollback boundary

No runtime, workflow, validation-runner, dependency, or topology behavior is changed by this Stage 1 evidence record.
