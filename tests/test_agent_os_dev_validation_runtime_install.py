from pathlib import Path

SCRIPT=Path("08_Tooling/agent-os-execution-service/scripts/install-dev-validation-runtime")

def source():return SCRIPT.read_text(encoding="utf-8")

def test_runtime_installer_is_fixed_and_hash_pinned():
 text=source();assert "PYTEST_VERSION=8.3.5" in text;assert "--require-hashes" in text;assert "pytest==8.3.5 --hash=sha256:" in text;assert "iniconfig==2.1.0 --hash=sha256:" in text;assert "packaging==25.0 --hash=sha256:" in text;assert "pluggy==1.5.0 --hash=sha256:" in text;assert "Pygments==2.19.2 --hash=sha256:" in text

def test_runtime_installer_has_no_caller_selected_package_surface():
 text=source();pip_install_block=text.split("\"$PYTHON\" -m pip install")[1].split(">&2")[0]
 assert "$@" not in pip_install_block;assert "PIP_CONFIG_FILE=/dev/null" in text;assert "unset PYTHONPATH" in text;assert "--only-binary=:all:" in text;assert "--target \"$STAGING_ROOT/site\"" in text

def test_runtime_publication_is_separate_from_dev_validation():
 text=source();assert "/usr/local/libexec/agent-os-dev-validation-python" in text;assert "/opt/agent-os/dev-validation-runtime" in text;assert "scheduler_invoked" in text;assert '"execution_authorized": False' in text;assert '"publication_invoked": False' in text;assert '"merge_authorized": False' in text

def test_runtime_installer_has_bounded_rollback_targets_only():
 text=source();assert "rm -rf \"$RUNTIME_ROOT\"" in text;assert "agent-os-governed-resume" not in text;assert "sudoers" not in text;assert "gcloud" not in text

def test_runtime_installer_verifies_versions_via_package_metadata():
 text=source()
 assert "from importlib.metadata import version" in text
 assert 'version(name)' in text
 assert "iniconfig.__version__" not in text
