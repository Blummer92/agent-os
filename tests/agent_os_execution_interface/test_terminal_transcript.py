from __future__ import annotations

from scripts.agent_os_execution_interface.terminal_transcript import parse_terminal_transcript


def test_full_cloud_shell_transcript_extracts_command_context_and_latest_failure():
    transcript = """Welcome to Cloud Shell! Type \"help\" to get started.
To set your Cloud Platform project in this session use `gcloud config set project [PROJECT_ID]`.
zblumstein@cloudshell:~$ gcloud config set project agent-os-502614
Updated property [core/project].
zblumstein@cloudshell:~ (agent-os-502614)$ git fetch origin && git checkout agent/1557-ci-tst3c-lifecycle
fatal: not a git repository (or any parent up to mount point /)
zblumstein@cloudshell:~ (agent-os-502614)$
"""
    parsed = parse_terminal_transcript(transcript)

    assert parsed.commands == (
        "gcloud config set project agent-os-502614",
        "git fetch origin && git checkout agent/1557-ci-tst3c-lifecycle",
    )
    assert parsed.newest_actionable_failure == "fatal: not a git repository (or any parent up to mount point /)"
    assert parsed.current_directory == "~"
    assert parsed.cloud_project == "agent-os-502614"


def test_parenthesized_prompt_is_context_not_a_command():
    parsed = parse_terminal_transcript(
        "zblumstein@cloudshell:~/agent-os (agent/1571-mobile-terminal-transcript)$\n"
    )
    assert parsed.commands == ()
    assert parsed.current_directory == "~/agent-os"
    assert parsed.branch == "agent/1571-mobile-terminal-transcript"


def test_repeated_history_does_not_displace_newest_actionable_failure():
    parsed = parse_terminal_transcript(
        "user@cloudshell:~$ git fetch origin\n"
        "fatal: not a git repository\n"
        "user@cloudshell:~$ cd ~/agent-os\n"
        "user@cloudshell:~/agent-os (main)$ python -m pytest tests/x.py -q\n"
        "ModuleNotFoundError: No module named 'agent_os_execution_service'\n"
        "user@cloudshell:~/agent-os (main)$\n"
    )
    assert parsed.commands[-1] == "python -m pytest tests/x.py -q"
    assert parsed.newest_actionable_failure == "ModuleNotFoundError: No module named 'agent_os_execution_service'"
    assert parsed.current_directory == "~/agent-os"
    assert parsed.branch == "main"


def test_python_version_is_preserved_from_pytest_header():
    parsed = parse_terminal_transcript(
        "platform linux -- Python 3.12.3, pytest-9.1.1, pluggy-1.6.0\n"
    )
    assert parsed.python_version == "3.12.3"


def test_parser_is_read_only_and_deterministic():
    text = "user@host:~/repo (main)$ python -m pytest -q\nERROR: failed\n"
    first = parse_terminal_transcript(text)
    second = parse_terminal_transcript(text)
    assert first == second
    assert first.commands == ("python -m pytest -q",)
    assert first.newest_actionable_failure == "ERROR: failed"


def test_non_string_transcript_fails_closed():
    try:
        parse_terminal_transcript(None)  # type: ignore[arg-type]
    except TypeError as exc:
        assert "must be a string" in str(exc)
    else:
        raise AssertionError("non-string transcript must be rejected")
