from __future__ import annotations

from email.parser import Parser
import json
import os
from pathlib import Path
import subprocess
import sys
import venv
import zipfile


ROOT = Path(__file__).parents[1]
CONTRACTS_PROJECT = ROOT / "src"
COACH_PROJECT = ROOT / "08_Tooling" / "instructional-materials-coach"


def _clean_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    return env


def _run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=_clean_env(),
        check=True,
        capture_output=True,
        text=True,
    )


def _build_wheel(project: Path, output: Path) -> Path:
    output.mkdir(parents=True)
    before = set(output.glob("*.whl"))
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
            str(project),
        ],
        cwd=output,
    )
    created = set(output.glob("*.whl")) - before
    assert len(created) == 1
    return created.pop()


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


def test_distribution_ownership_dependency_and_noneditable_install(tmp_path: Path) -> None:
    root_wheel = _build_wheel(ROOT, tmp_path / "root-wheel")
    contracts_wheel = _build_wheel(CONTRACTS_PROJECT, tmp_path / "contracts-wheel")
    coach_wheel = _build_wheel(COACH_PROJECT, tmp_path / "coach-wheel")

    root_names = _wheel_names(root_wheel)
    assert any(name.startswith("navigation_registry/") for name in root_names)
    assert not any(name.startswith("instructional_workflow_contracts/") for name in root_names)

    contracts_names = _wheel_names(contracts_wheel)
    assert any(name.startswith("instructional_workflow_contracts/") for name in contracts_names)
    assert not any(name.startswith("navigation_registry/") for name in contracts_names)
    assert not any(name.startswith("instructional_materials_coach/") for name in contracts_names)

    coach_metadata = _wheel_metadata(coach_wheel)
    coach_requirements = coach_metadata.get_all("Requires-Dist", [])
    contracts_requirements = [
        requirement.replace(" ", "")
        for requirement in coach_requirements
        if requirement.lower().startswith("instructional-workflow-contracts")
    ]
    assert len(contracts_requirements) == 1
    assert ">=0.1.0" in contracts_requirements[0]
    assert "<0.2.0" in contracts_requirements[0]

    contracts_metadata = _wheel_metadata(contracts_wheel)
    contracts_dependencies = contracts_metadata.get_all("Requires-Dist", [])
    assert not any(
        requirement.lower().startswith("instructional-materials-coach")
        for requirement in contracts_dependencies
    )

    environment = tmp_path / "installed"
    # #944 permits inheriting preinstalled Google/PyYAML validation dependencies only.
    # The contracts package is force-installed from its wheel and provenance-checked below.
    venv.EnvBuilder(with_pip=True, system_site_packages=True).create(environment)
    python = _venv_python(environment)
    _run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            "--ignore-installed",
            str(contracts_wheel),
        ],
        cwd=tmp_path,
    )
    _run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--find-links",
            str(contracts_wheel.parent),
            str(coach_wheel),
        ],
        cwd=tmp_path,
    )

    outside_repo = tmp_path / "outside-repository"
    outside_repo.mkdir()
    probe = _run(
        [
            str(python),
            "-c",
            (
                "import json; "
                "import instructional_materials_coach as coach; "
                "import instructional_workflow_contracts as contracts; "
                "print(json.dumps({'coach': coach.__file__, 'contracts': contracts.__file__}))"
            ),
        ],
        cwd=outside_repo,
    )
    locations = json.loads(probe.stdout)
    repository_root = ROOT.resolve()
    environment_root = environment.resolve()
    for location in locations.values():
        module_path = Path(location).resolve()
        assert module_path.is_relative_to(environment_root)
        assert not module_path.is_relative_to(repository_root)
