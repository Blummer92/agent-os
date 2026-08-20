"""AOS-GCE2C (#1300): isolated host installation/importability proof.

These tests build the real distributions, install them into an isolated
environment, and prove that the frozen governed-resume runtime behind
``/usr/local/libexec/agent-os-governed-resume`` imports its complete production
dependency graph there -- with no repository-root ``PYTHONPATH``, no editable
checkout, no conftest path injection, and no dependence on the current working
directory.

Everything here is offline: wheels are built from this checkout and installed
with ``--no-index``. No GitHub, network, cloud, IAM, VM, SSH, or IAP effect
occurs, and no Scheduler job, lease acquisition, or reconstruction is executed --
this proves installation and import/startup only. Live qualification stays with
#1239.

The isolated environment does **not** inherit system site packages. The
developer loop installs several Agent OS distributions editable (see
``requirements-dev.txt``), and an editable install registers a meta-path finder
that would otherwise resolve ``workflow_scheduler`` and the ``scripts.*``
packages straight back to this checkout -- exactly the editable-checkout
accident #1300 must prove the host does not depend on. So every Agent OS
distribution is installed from a freshly built wheel, and only the third-party
dependencies (PyGithub/requests/PyYAML and their own dependencies) are vendored
in from the running environment, offline, by copying the distributions pip
already resolved. Provenance of every imported module is asserted below.
"""

from __future__ import annotations

from email.parser import Parser
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import venv
import zipfile

import pytest


ROOT = Path(__file__).parents[3]
EXECUTION_SERVICE_PROJECT = ROOT / "08_Tooling" / "agent-os-execution-service"
WORKFLOW_SCHEDULER_PROJECT = ROOT / "08_Tooling" / "workflow-scheduler"
CONTEXT_MANAGER_PROJECT = ROOT / "08_Tooling" / "agent-memory-context-manager"
CAPABILITY_REGISTRY_PROJECT = ROOT / "08_Tooling" / "reusable-capability-registry"

RUNTIME_PROJECTS = (
    CAPABILITY_REGISTRY_PROJECT,
    CONTEXT_MANAGER_PROJECT,
    WORKFLOW_SCHEDULER_PROJECT,
    EXECUTION_SERVICE_PROJECT,
)

# The canonical descriptor loader production host composition binds (#1287).
CANONICAL_DESCRIPTOR_LOADER = "scripts/agent_os_execution_checkpoint/invocation_descriptor.py"


def _clean_env() -> dict[str, str]:
    """Environment with no repository-root path injection of any kind."""
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    return env


def _run(
    command: list[str], *, cwd: Path, check: bool = True
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=_clean_env(),
        check=False,
        capture_output=True,
        text=True,
    )
    if check and completed.returncode != 0:
        raise AssertionError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


def _build_wheels(output: Path) -> dict[str, Path]:
    output.mkdir(parents=True, exist_ok=True)
    _run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(output),
            *(str(project) for project in RUNTIME_PROJECTS),
        ],
        cwd=output,
    )
    wheels = {wheel.name.split("-")[0]: wheel for wheel in output.glob("*.whl")}
    assert set(wheels) == {
        "agent_os_execution_service",
        "workflow_scheduler",
        "agent_memory_context_manager",
        "reusable_capability_registry",
    }, sorted(wheels)
    return wheels


def _wheel_names(wheel: Path) -> tuple[str, ...]:
    with zipfile.ZipFile(wheel) as archive:
        return tuple(sorted(archive.namelist()))


def _wheel_metadata(wheel: Path) -> Parser:
    with zipfile.ZipFile(wheel) as archive:
        metadata_paths = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        assert len(metadata_paths) == 1
        metadata = archive.read(metadata_paths[0]).decode("utf-8")
    return Parser().parsestr(metadata)


def _venv_python(environment: Path) -> Path:
    if os.name == "nt":
        return environment / "Scripts" / "python.exe"
    return environment / "bin" / "python"


def _venv_site_packages(python: Path) -> Path:
    location = _run(
        [str(python), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
        cwd=python.parent,
    ).stdout.strip()
    return Path(location)


def _third_party_requirements(wheels: dict[str, Path]) -> set[str]:
    """Declared requirements that are not Agent OS distributions themselves."""
    agent_os_names = {name.replace("_", "-") for name in wheels}
    required: set[str] = set()
    for wheel in wheels.values():
        for requirement in _wheel_metadata(wheel).get_all("Requires-Dist", []):
            if "extra ==" in requirement:
                continue
            name = re.split(r"[;\[<>=!~ ]", requirement, maxsplit=1)[0].strip()
            if name and name.lower().replace("_", "-") not in agent_os_names:
                required.add(name)
    return required


def _copy_into(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return
    if source.is_dir():
        shutil.copytree(source, destination)
    elif source.is_file():
        shutil.copy2(source, destination)


def _copy_distribution(distribution: importlib.metadata.Distribution, site_packages: Path) -> None:
    """Copy one installed distribution into ``site_packages``.

    ``Distribution.files`` is ``None`` for distributions installed without a
    ``RECORD`` (system-packaged ones, for example), so fall back to the
    distribution's declared top-level names next to its metadata directory.
    """
    base = Path(distribution.locate_file(""))
    recorded = distribution.files
    if recorded is not None:
        for relative in recorded:
            source = Path(distribution.locate_file(relative))
            if source.is_file():
                _copy_into(source, site_packages / str(relative))
        return

    metadata_directory = getattr(distribution, "_path", None)
    if metadata_directory is not None:
        _copy_into(Path(metadata_directory), site_packages / Path(metadata_directory).name)
    top_level = distribution.read_text("top_level.txt") or ""
    names = [line.strip() for line in top_level.splitlines() if line.strip()]
    if not names:
        names = [(distribution.metadata["Name"] or "").replace("-", "_")]
    for name in names:
        package = base / name
        if package.is_dir():
            _copy_into(package, site_packages / name)
            continue
        for pattern in (f"{name}.py", f"{name}.pyi", f"{name}*.so"):
            for source in base.glob(pattern):
                _copy_into(source, site_packages / source.name)


def _vendor_offline(names: set[str], site_packages: Path) -> None:
    """Copy already-resolved third-party distributions into the environment.

    Offline by construction: nothing is downloaded, and only distributions
    reachable from the declared third-party requirements are copied, so no
    Agent OS source or editable finder can leak into the isolated environment.
    """
    site_packages.mkdir(parents=True, exist_ok=True)
    # ``required`` separates what the Agent OS wheels themselves declare -- whose
    # absence is an environment gap worth reporting -- from dependencies
    # discovered while walking, which may legitimately be absent here.
    pending: list[tuple[str, bool]] = [(name, True) for name in names]
    seen: set[str] = set()
    while pending:
        name, required = pending.pop()
        key = name.lower().replace("_", "-")
        if key in seen:
            continue
        seen.add(key)
        try:
            distribution = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:  # pragma: no cover
            if required:
                pytest.skip(
                    f"declared runtime dependency {name!r} is not installed here, so an "
                    "isolated installation cannot be assembled without network access"
                )
            continue
        _copy_distribution(distribution, site_packages)
        for requirement in distribution.requires or ():
            dependency = re.split(r"[;\[<>=!~ ]", requirement, maxsplit=1)[0].strip()
            if dependency:
                pending.append((dependency, False))


@pytest.fixture(scope="module")
def built_wheels(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    return _build_wheels(tmp_path_factory.mktemp("governed-resume-wheels"))


@pytest.fixture(scope="module")
def installed_runtime(
    built_wheels: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, Path]:
    """Install the supported governed-resume runtime into a clean environment."""
    environment = tmp_path_factory.mktemp("governed-resume-install") / "runtime"
    venv.EnvBuilder(with_pip=True, system_site_packages=False).create(environment)
    python = _venv_python(environment)
    wheel_dir = next(iter(built_wheels.values())).parent
    _vendor_offline(_third_party_requirements(built_wheels), _venv_site_packages(python))
    _run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--find-links",
            str(wheel_dir),
            "agent-os-execution-service",
        ],
        cwd=wheel_dir,
    )
    outside_repository = wheel_dir.parent / "outside-repository"
    outside_repository.mkdir(exist_ok=True)
    return python, outside_repository


def test_distributions_carry_one_canonical_copy_of_every_runtime_module(
    built_wheels: dict[str, Path],
) -> None:
    """No module -- above all the descriptor loader -- is shipped twice."""
    service_names = _wheel_names(built_wheels["agent_os_execution_service"])
    scheduler_names = _wheel_names(built_wheels["workflow_scheduler"])

    service_modules = {name for name in service_names if name.endswith(".py")}
    scheduler_modules = {name for name in scheduler_names if name.endswith(".py")}
    assert service_modules & scheduler_modules == set()

    # The canonical descriptor loader is carried by exactly one distribution.
    carriers = [
        name
        for name, wheel in built_wheels.items()
        if CANONICAL_DESCRIPTOR_LOADER in _wheel_names(wheel)
    ]
    assert carriers == ["workflow_scheduler"]

    # It is distributed, never copied: the shipped bytes are the canonical file.
    with zipfile.ZipFile(built_wheels["workflow_scheduler"]) as archive:
        shipped = archive.read(CANONICAL_DESCRIPTOR_LOADER)
    assert shipped == (ROOT / CANONICAL_DESCRIPTOR_LOADER).read_bytes()


def test_explicit_package_lists_still_cover_every_source_module(
    built_wheels: dict[str, Path],
) -> None:
    """Guard the cost of listing packages explicitly.

    ``packages.find`` cannot discover the out-of-tree ``scripts.*`` packages, so
    both distributions list their packages by hand. A new subpackage added to
    either source tree would otherwise be dropped from the wheel silently.
    """
    shipped = {
        name
        for wheel in built_wheels.values()
        for name in _wheel_names(wheel)
        if name.endswith(".py")
    }
    sources = {
        WORKFLOW_SCHEDULER_PROJECT / "src" / "workflow_scheduler": "workflow_scheduler",
        EXECUTION_SERVICE_PROJECT / "src" / "agent_os_execution_service": "agent_os_execution_service",
    }
    for package in (
        "agent_os_candidate_packet",
        "agent_os_execution_capabilities",
        "agent_os_execution_checkpoint",
        "agent_os_github_issue_provider",
        "agent_os_issue_acceptance",
        "agent_os_remote_validation",
    ):
        sources[ROOT / "scripts" / package] = f"scripts/{package}"

    missing = []
    for source_root, shipped_prefix in sources.items():
        for module in source_root.rglob("*.py"):
            if "__pycache__" in module.parts:
                continue
            relative = module.relative_to(source_root).as_posix()
            if f"{shipped_prefix}/{relative}" not in shipped:
                missing.append(f"{shipped_prefix}/{relative}")
    assert missing == []


def test_execution_service_declares_a_deterministic_scheduler_dependency(
    built_wheels: dict[str, Path],
) -> None:
    requirements = _wheel_metadata(
        built_wheels["agent_os_execution_service"]
    ).get_all("Requires-Dist", [])
    scheduler = [
        requirement.replace(" ", "")
        for requirement in requirements
        if requirement.lower().startswith("workflow-scheduler")
    ]
    assert len(scheduler) == 1
    assert ">=0.18.0" in scheduler[0]
    assert "<0.19.0" in scheduler[0]

    # The Scheduler distribution must not depend back on the execution service.
    scheduler_requirements = _wheel_metadata(
        built_wheels["workflow_scheduler"]
    ).get_all("Requires-Dist", [])
    assert not any(
        requirement.lower().startswith("agent-os-execution-service")
        for requirement in scheduler_requirements
    )


def test_native_clone3_cgroup_extension_is_built_by_the_scheduler_wheel(
    built_wheels: dict[str, Path],
) -> None:
    """The qualified Debian host builds the extension from this distribution."""
    scheduler_wheel = built_wheels["workflow_scheduler"]
    extensions = [
        name
        for name in _wheel_names(scheduler_wheel)
        if name.startswith("workflow_scheduler/execution/_clone3_cgroup")
        and name.endswith(".so")
    ]
    assert len(extensions) == 1
    # A platform wheel, not a pure-Python one: the C extension really compiled.
    assert not scheduler_wheel.name.endswith("-py3-none-any.whl")


def test_isolated_installation_imports_the_production_governed_resume_graph(
    installed_runtime: tuple[Path, Path],
) -> None:
    """The #1287 production composition imports from a clean installation."""
    python, outside_repository = installed_runtime
    probe = _run(
        [
            str(python),
            "-c",
            (
                "import json, sys; "
                "import agent_os_execution_service as service; "
                "import workflow_scheduler; "
                "from workflow_scheduler.execution import _clone3_cgroup; "
                "from scripts.agent_os_execution_checkpoint.invocation_descriptor "
                "import load_invocation_descriptor; "
                "import agent_os_execution_service.production_host_composition as phc; "
                "import agent_os_execution_service.governed_resume_entrypoint as entrypoint; "
                "print(json.dumps({"
                "'service': service.__file__, "
                "'scheduler_paths': list(workflow_scheduler.__path__), "
                "'native': _clone3_cgroup.__file__, "
                "'loader': load_invocation_descriptor.__module__, "
                "'composition': phc.__file__, "
                "'entrypoint': entrypoint.__file__, "
                "'one_loader': phc.load_invocation_descriptor is load_invocation_descriptor, "
                "'sys_path': sys.path}))"
            ),
        ],
        cwd=outside_repository,
    )
    observed = json.loads(probe.stdout)

    environment_root = python.parent.parent.resolve()
    repository_root = ROOT.resolve()
    located = {key: observed[key] for key in ("service", "native", "composition", "entrypoint")}
    # ``workflow_scheduler`` is a namespace package, so it is located by its
    # search path rather than by a module file.
    located.update(
        {f"scheduler[{index}]": entry for index, entry in enumerate(observed["scheduler_paths"])}
    )
    assert observed["scheduler_paths"]
    for key, location in located.items():
        module_path = Path(location).resolve()
        assert module_path.is_relative_to(environment_root), (key, location)
        assert not module_path.is_relative_to(repository_root), (key, location)

    # Production composition binds the one canonical descriptor loader.
    assert observed["loader"] == "scripts.agent_os_execution_checkpoint.invocation_descriptor"
    assert observed["one_loader"] is True

    # The success above cannot be a repository-root or checkout accident.
    for entry in observed["sys_path"]:
        if not entry:
            continue
        resolved = Path(entry).resolve()
        assert not resolved.is_relative_to(repository_root), entry


def test_installed_entrypoint_reaches_its_argv_boundary_without_dispatching(
    installed_runtime: tuple[Path, Path],
) -> None:
    """``python3 -m ...governed_resume_entrypoint`` is what the wrapper runs.

    Import/startup only: with no ``--handoff-id`` the frozen contract rejects
    argv before reconstruction or dispatch can occur, which is exactly the
    boundary #1300 proves. No Scheduler job, lease, or reconstruction runs.
    """
    python, outside_repository = installed_runtime
    result = _run(
        [
            str(python),
            "-m",
            "agent_os_execution_service.governed_resume_entrypoint",
        ],
        cwd=outside_repository,
        check=False,
    )
    assert result.returncode != 0
    assert "--handoff-id" in result.stderr
    assert "ModuleNotFoundError" not in result.stderr
    assert "ImportError" not in result.stderr


def test_missing_runtime_dependency_fails_explicitly(
    built_wheels: dict[str, Path], tmp_path: Path
) -> None:
    """An incomplete installation must fail loudly, never silently degrade."""
    environment = tmp_path / "incomplete"
    venv.EnvBuilder(with_pip=True, system_site_packages=False).create(environment)
    python = _venv_python(environment)
    wheel_dir = built_wheels["agent_os_execution_service"].parent
    _run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            str(built_wheels["agent_os_execution_service"]),
        ],
        cwd=wheel_dir,
    )
    result = _run(
        [str(python), "-c", "import agent_os_execution_service"],
        cwd=tmp_path,
        check=False,
    )
    assert result.returncode != 0
    assert "ModuleNotFoundError" in result.stderr
