"""#1238 regression coverage for governed host-runtime publication permissions."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
PRIVILEGED = (
    ROOT / "08_Tooling/agent-os-execution-service/scripts/agent-os-host-install"
)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _build_probe_wheel(root: Path) -> Path:
    wheel = root / "agent_os_permission_probe-0.0.0-py3-none-any.whl"
    files = {
        "agent_os_permission_probe/__init__.py": b"VALUE = 42\n",
        "agent_os_permission_probe-0.0.0.dist-info/WHEEL": (
            b"Wheel-Version: 1.0\nGenerator: agent-os-test\n"
            b"Root-Is-Purelib: true\nTag: py3-none-any\n"
        ),
        "agent_os_permission_probe-0.0.0.dist-info/METADATA": (
            b"Metadata-Version: 2.1\nName: agent-os-permission-probe\n"
            b"Version: 0.0.0\n"
        ),
    }
    record = "agent_os_permission_probe-0.0.0.dist-info/RECORD"
    rows: list[list[str]] = []
    for name, data in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest())
        rows.append(
            [name, f"sha256={digest.rstrip(b'=').decode('ascii')}", str(len(data))]
        )
    rows.append([record, "", ""])
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(rows)
    files[record] = buffer.getvalue().encode("utf-8")

    with zipfile.ZipFile(wheel, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return wheel


def _pip_install_with_umask(wheel: Path, target: Path, mask: str) -> None:
    command = (
        f"umask {mask}; exec {shlex_quote(sys.executable)} -m pip install "
        "--disable-pip-version-check --no-deps --no-index "
        f"--target {shlex_quote(str(target))} {shlex_quote(str(wheel))}"
    )
    completed = subprocess.run(
        ["/bin/sh", "-c", command],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def _pip_force_reinstall_with_umask(wheel: Path, target: Path, mask: str) -> None:
    command = (
        f"umask {mask}; exec {shlex_quote(sys.executable)} -m pip install "
        "--disable-pip-version-check --no-deps --no-index --upgrade --force-reinstall "
        f"--target {shlex_quote(str(target))} {shlex_quote(str(wheel))}"
    )
    completed = subprocess.run(
        ["/bin/sh", "-c", command],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def shlex_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _normalize_probe_tree(package_root: Path) -> None:
    for current_root, dir_names, file_names in os.walk(package_root, followlinks=False):
        current = Path(current_root)
        assert not current.is_symlink()
        current.chmod(0o755)
        for dir_name in dir_names:
            assert not (current / dir_name).is_symlink()
        for file_name in file_names:
            child = current / file_name
            assert child.is_file() and not child.is_symlink()
            prior_mode = _mode(child)
            child.chmod(0o755 if prior_mode & 0o100 else 0o644)


def test_privileged_installer_scopes_runtime_umask_without_weakening_staging() -> None:
    text = PRIVILEGED.read_text(encoding="utf-8")

    initial_077 = text.index("umask 077")
    staging_0700 = text.index('chmod 0700 "$STAGING_ROOT"')
    build_tools_0700 = text.index('chmod 0700 "$build_tools"')
    wheel_dir_0700 = text.index('chmod 0700 "$wheel_dir"')
    runtime_022 = text.index("umask 022")
    system_install = text.index("PIP_NO_INDEX=1 python3 -m pip install", runtime_022)
    restored_077 = text.index("umask 077", system_install)
    normalization = text.index("for package_name in package_roots", restored_077)
    import_check = text.index("env -u PYTHONPATH", normalization)

    assert initial_077 < staging_0700 < build_tools_0700 < wheel_dir_0700 < runtime_022
    assert runtime_022 < system_install < restored_077 < normalization < import_check
    assert text.count("umask 022") == 1
    assert text.count("umask 077") == 2

    runtime_block = text[runtime_022:restored_077]
    for wheel_name in (
        '"$capability_wheel"',
        '"$context_wheel"',
        '"$scheduler_wheel"',
        '"$service_wheel"',
    ):
        assert wheel_name in runtime_block
    assert "--no-index" in runtime_block
    assert "--no-deps" in runtime_block
    assert "chmod" not in runtime_block
    assert "setfacl" not in text
    assert "chmod -R" not in text
    assert "777" not in runtime_block
    assert '"reusable_capability_registry"' in text
    assert '"agent_memory_context_manager"' in text
    assert '"workflow_scheduler"' in text
    assert '"agent_os_execution_service"' in text
    assert "os.walk(package_root, followlinks=False)" in text
    assert "os.walk(site_root" not in text


def test_repair_in_place_normalizes_preexisting_restrictive_package_tree() -> None:
    base = Path(tempfile.mkdtemp(prefix="agent-os-1238-repair-in-place-", dir="/tmp"))
    base.chmod(0o755)
    try:
        wheel = _build_probe_wheel(base)
        runtime = base / "runtime"
        runtime.mkdir(mode=0o755)

        _pip_install_with_umask(wheel, runtime, "077")
        package = runtime / "agent_os_permission_probe"
        module = package / "__init__.py"
        assert _mode(package) == 0o700
        assert _mode(module) == 0o600

        _pip_force_reinstall_with_umask(wheel, runtime, "022")
        assert _mode(package) == 0o700
        assert _mode(module) == 0o644

        _normalize_probe_tree(package)
        assert _mode(package) == 0o755
        assert _mode(module) == 0o644
        assert _mode(package) & 0o022 == 0
        assert _mode(module) & 0o022 == 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_pip_runtime_publication_mask_is_nonroot_readable_without_write_bits() -> None:
    base = Path(tempfile.mkdtemp(prefix="agent-os-1238-permissions-", dir="/tmp"))
    base.chmod(0o755)
    try:
        wheel = _build_probe_wheel(base)
        restrictive = base / "u077"
        runtime = base / "u022"
        restrictive.mkdir(mode=0o755)
        runtime.mkdir(mode=0o755)

        _pip_install_with_umask(wheel, restrictive, "077")
        _pip_install_with_umask(wheel, runtime, "022")

        restrictive_package = restrictive / "agent_os_permission_probe"
        runtime_package = runtime / "agent_os_permission_probe"
        restrictive_module = restrictive_package / "__init__.py"
        runtime_module = runtime_package / "__init__.py"

        assert _mode(restrictive_package) == 0o700
        assert _mode(restrictive_module) == 0o600
        assert _mode(runtime_package) == 0o755
        assert _mode(runtime_module) == 0o644
        assert _mode(runtime_package) & 0o022 == 0
        assert _mode(runtime_module) & 0o022 == 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


@pytest.mark.skipif(shutil.which("sudo") is None, reason="needs sudo for cross-user import")
def test_runtime_publication_imports_from_a_different_unprivileged_identity() -> None:
    if shutil.which("/usr/bin/python3") is None:
        pytest.skip("qualified system interpreter unavailable")
    exact_probe = subprocess.run(
        ["sudo", "-n", "-u", "nobody", "/usr/bin/true"],
        check=False,
        capture_output=True,
        text=True,
    )
    if exact_probe.returncode != 0:
        pytest.skip("passwordless sudo to nobody unavailable for cross-user import")

    base = Path(tempfile.mkdtemp(prefix="agent-os-1238-runtime-user-", dir="/tmp"))
    base.chmod(0o755)
    try:
        wheel = _build_probe_wheel(base)
        restrictive = base / "u077"
        runtime = base / "u022"
        restrictive.mkdir(mode=0o755)
        runtime.mkdir(mode=0o755)
        _pip_install_with_umask(wheel, restrictive, "077")
        _pip_install_with_umask(wheel, runtime, "022")

        probe = "import agent_os_permission_probe as p; print(p.VALUE)"
        allowed = subprocess.run(
            [
                "sudo",
                "-n",
                "-u",
                "nobody",
                "/usr/bin/python3",
                "-c",
                f"import sys; sys.path.insert(0, {str(runtime)!r}); {probe}",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        restrictive_result = subprocess.run(
            [
                "sudo",
                "-n",
                "-u",
                "nobody",
                "/usr/bin/python3",
                "-c",
                f"import sys; sys.path.insert(0, {str(restrictive)!r}); {probe}",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        assert allowed.returncode == 0, allowed.stdout + allowed.stderr
        assert allowed.stdout.strip() == "42"
        assert not (
            restrictive_result.returncode == 0
            and restrictive_result.stdout.strip() == "42"
        ), restrictive_result.stdout + restrictive_result.stderr
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_permission_repair_does_not_add_execution_or_external_control_paths() -> None:
    text = PRIVILEGED.read_text(encoding="utf-8")
    assert "gcloud" not in text
    assert "compute instances" not in text
    assert "systemd-run" not in text
    assert "scheduler_invoked" in text
    assert '"scheduler_invoked": False' in text
    assert '"execution_authorized": False' in text
    assert "PIP_NO_INDEX=1" in text
    assert "--no-index" in text
    assert "--no-deps" in text
