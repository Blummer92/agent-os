import pytest

from scripts.agent_os_github_git_objects.models import GitTreeEntry


SHA = "a" * 40


def test_git_tree_entry_accepts_regular_file_modes():
    assert GitTreeEntry("plain.txt", "100644", "blob", SHA).mode == "100644"
    assert GitTreeEntry("script.sh", "100755", "blob", SHA).mode == "100755"


def test_git_tree_entry_rejects_unsupported_modes():
    for mode in ("100600", "120000", "160000"):
        with pytest.raises(ValueError):
            GitTreeEntry("file", mode, "blob", SHA)
