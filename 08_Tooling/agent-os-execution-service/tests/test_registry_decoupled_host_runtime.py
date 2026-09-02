"""#1737 clean-wheel proof that the governed host runtime does not need the registry."""

from __future__ import annotations

from email.parser import Parser
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv
import zipfile

import pytest

ROOT = Path(__file__).parents[3]
PROJECTS = (
    ROOT / "08_Tooling/agent-memory-context-manager",
    ROOT / "08_Tooling/workflow-scheduler",
    ROOT / "08_Tooling/agent-os-execution-service",
)


def _run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return completed


def _metadata(wheel: Path) -> Parser:
    with zipfile.ZipFile(wheel) as archive:
        names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        assert len(names) == 1
        return Parser().parsestr(archive.read(names[0]).decode("utf-8"))


def _venv_python(environment: Path) -> Path:
    return environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def test_scheduler_metadata_does_not_require_reusable_capability_registry(tmp_path: Path) -> None:
    wheel_dir = tmp_path / "wheels"
    wheel_dir.mkdir()
    _run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheel_dir),
            str(ROOT / "08_Tooling/workflow-scheduler"),
        ],
        cwd=wheel_dir,
    )
    wheel = next(wheel_dir.glob("workflow_scheduler-*.whl"))
    requirements = _metadata(wheel).get_all("Requires-Dist", [])
    assert not any(
        requirement.lower().startswith("reusable-capability-registry")
        for requirement in requirements
    )


def test_clean_three_wheel_runtime_imports_without_registry(tmp_path: Path) -> None:
    wheel_dir = tmp_path / "wheels"
    wheel_dir.mkdir()
    _run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheel_dir),
            *(str(project) for project in PROJECTS),
        ],
        cwd=wheel_dir,
    )
    wheels = {wheel.name.split("-")[0]: wheel for wheel in wheel_dir.glob("*.whl")}
    assert set(wheels) == {
        "agent_memory_context_manager",
        "workflow_scheduler",
        "agent_os_execution_service",
    }
    assert not list(wheel_dir.glob("reusable_capability_registry-*.whl"))

    environment = tmp_path / "runtime"
    venv.EnvBuilder(with_pip=True, system_site_packages=False).create(environment)
    python = _venv_python(environment)

    # The governed host uses --no-deps and relies on qualified third-party
    # runtime dependencies already being present. Copy PyYAML into this isolated
    # environment without consulting an index so the test remains offline.
    try:
        yaml_distribution = __import__("importlib.metadata", fromlist=["distribution"]).distribution("PyYAML")
    except Exception:  # pragma: no cover - environment capability gap
        pytest.skip("PyYAML is not installed in the developer environment")
    site = Path(
        _run(
            [str(python), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
            cwd=tmp_path,
        ).stdout.strip()
    )
    for relative in yaml_distribution.files or ():
        source = Path(yaml_distribution.locate_file(relative))
        if not source.is_file():
            continue
        destination = site / str(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    _run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            *(str(wheel) for wheel in wheels.values()),
        ],
        cwd=wheel_dir,
    )
    outside = tmp_path / "outside-repository"
    outside.mkdir()
    probe = _run(
        [
            str(python),
            "-c",
            (
                "import importlib.util, json; "
                "import workflow_scheduler; "
                "import workflow_scheduler.execution.single_issue_pilot; "
                "import scripts.agent_os_issue_acceptance; "
                "import agent_os_execution_service.production_host_bootstrap; "
                "print(json.dumps({'registry': importlib.util.find_spec('reusable_capability_registry')}))"
            ),
        ],
        cwd=outside,
    )
    assert json.loads(probe.stdout)["registry"] is None
