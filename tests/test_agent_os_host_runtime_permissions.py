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


def shlex_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def test_privileged_installer_scopes_runtime_umask_without_weakening_staging() -> None:
    text = PRIVILEGED.read_text(encoding="utf-8")

    initial_077 = text.index("umask 077")
    staging_0700 = text.index('chmod 0700 "$STAGING_ROOT"')
    build_tools_0700 = text.index('chmod 0700 "$build_tools"')
    wheel_dir_0700 = text.index('chmod 0700 "$wheel_dir"')
    runtime_022 = text.index("umask 022")
    system_install = text.index("PIP_NO_INDEX=1 python3 -m pip install", runtime_022)
    restored_077 = text.index("umask 077", system_install)
    import_check = text.index("env -u PYTHONPATH", restored_077)

    assert initial_077 < staging_0700 < build_tools_0700 < wheel_dir_0700 < runtime_022
    assert runtime_022 < system_install < restored_077 < import_check
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
    if subprocess.run(
        ["sudo", "-n", "true"], check=False, capture_output=True
    ).returncode != 0:
        pytest.skip("passwordless sudo unavailable for cross-user import")
    if shutil.which("/usr/bin/python3") is None:
        pytest.skip("qualified system interpreter unavailable")

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
        denied = subprocess.run(
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
        assert denied.returncode != 0
        assert "ModuleNotFoundError" in denied.stderr
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
