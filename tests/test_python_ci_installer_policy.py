from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GOVERNED_PATHS = (
    ROOT / ".github/workflows/agent-os-validation.yml",
    ROOT / ".github/workflows/workflow-scheduler-validation.yml",
    ROOT / ".github/actions/setup-python-dev/action.yml",
    ROOT / "cloudbuild.yaml",
    ROOT / "01_Shared_Standards/python/ci-cd/github-actions.md",
    ROOT / "01_Shared_Standards/python/environments/ci-cd-setup.md",
    ROOT / "01_Shared_Standards/python/test-environment-setup.md",
    ROOT / "03_Templates/python-project-template/.github_workflows_tests.yml",
)


def test_governed_python_ci_surfaces_do_not_upgrade_pip_unconditionally():
    for path in GOVERNED_PATHS:
        content = path.read_text(encoding="utf-8")
        assert "pip install --upgrade pip" not in content, path


def test_canonical_guidance_documents_environment_provided_pip_policy():
    guidance = (
        ROOT / "01_Shared_Standards/python/ci-cd/github-actions.md"
    ).read_text(encoding="utf-8")
    assert "environment-provided pip" in guidance
    assert "documented" in guidance
    assert "compatibility requirement" in guidance
    assert "Cache restoration never replaces dependency installation" in guidance


def test_affected_github_actions_examples_use_setup_python_v5():
    paths = (
        ROOT / "01_Shared_Standards/python/ci-cd/github-actions.md",
        ROOT / "01_Shared_Standards/python/environments/ci-cd-setup.md",
        ROOT / "01_Shared_Standards/python/test-environment-setup.md",
        ROOT / "03_Templates/python-project-template/.github_workflows_tests.yml",
    )
    for path in paths:
        content = path.read_text(encoding="utf-8")
        assert "actions/setup-python@v4" not in content, path
        assert "actions/setup-python@v5" in content, path


def test_dependency_installation_remains_explicit_in_examples_and_action():
    required = {
        ROOT / "01_Shared_Standards/python/ci-cd/github-actions.md": (
            "python -m pip install -r requirements-dev.txt"
        ),
        ROOT / "01_Shared_Standards/python/environments/ci-cd-setup.md": (
            "python -m pip install -r requirements-dev.txt"
        ),
        ROOT / "01_Shared_Standards/python/test-environment-setup.md": (
            "python -m pip install -r requirements-dev.txt"
        ),
        ROOT / "03_Templates/python-project-template/.github_workflows_tests.yml": (
            "python -m pip install -r requirements-dev.txt"
        ),
        ROOT / ".github/actions/setup-python-dev/action.yml": (
            "python -m pip install -r requirements-dev.txt"
        ),
    }
    for path, command in required.items():
        assert command in path.read_text(encoding="utf-8"), path
