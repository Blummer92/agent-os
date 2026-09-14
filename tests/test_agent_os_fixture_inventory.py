import pytest

from scripts.agent_os_fixture_inventory import select_exact_basename


def test_runtime_conftest_inventory_excludes_template_substring_match():
    paths = (
        "tests/conftest.py",
        "tests/agent_os_issue_acceptance/conftest.py",
        "tests/agent_os_execution_interface/conftest.py",
        "tests/agent_os_cloud_build_provider/conftest.py",
        "08_Tooling/agent-memory-context-manager/tests/conftest.py",
        "08_Tooling/instructional-materials-coach/tests/conftest.py",
        "03_Templates/python-project-template/test_conftest.py",
    )
    result = select_exact_basename(paths, "conftest.py")
    assert len(result) == 6
    assert "03_Templates/python-project-template/test_conftest.py" not in result


def test_template_file_remains_discoverable_when_explicitly_requested():
    paths = ("tests/conftest.py", "03_Templates/python-project-template/test_conftest.py")
    assert select_exact_basename(paths, "test_conftest.py") == ("03_Templates/python-project-template/test_conftest.py",)


def test_order_and_duplicates_are_deterministic():
    assert select_exact_basename(("b/conftest.py", "a/conftest.py", "b/conftest.py"), "conftest.py") == ("a/conftest.py", "b/conftest.py")


@pytest.mark.parametrize("basename", ["", "a/b", "a\\b"])
def test_invalid_basename_fails_closed(basename):
    with pytest.raises(ValueError):
        select_exact_basename((), basename)
