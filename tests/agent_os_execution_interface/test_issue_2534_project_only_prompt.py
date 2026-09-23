from scripts.agent_os_execution_interface.terminal_transcript import parse_terminal_transcript


def test_project_only_cloud_shell_prompt_is_not_a_git_branch() -> None:
    parsed = parse_terminal_transcript("user@cloudshell:~ (agent-os-502614)$\n")
    assert parsed.current_directory == "~"
    assert parsed.cloud_project == "agent-os-502614"
    assert parsed.branch is None


def test_repository_directory_prompt_remains_branch_context() -> None:
    parsed = parse_terminal_transcript(
        "user@cloudshell:~/agent-os (agent/2534-project-prompt)$\n"
    )
    assert parsed.current_directory == "~/agent-os"
    assert parsed.branch == "agent/2534-project-prompt"
