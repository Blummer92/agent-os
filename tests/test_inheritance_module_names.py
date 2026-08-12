from pathlib import Path


REGISTRY = Path("04_Registry/agent-inheritance-registry.md")
MODULE_VERSION_MAP = Path("04_Registry/module-version-map.md")
COMMON_OVERLAY = Path("02_Agent_Overlays/_common-overlay-rules.md")
OVERLAY_DIR = Path("02_Agent_Overlays")

BASELINE_MODULES = {
    "Global Engineering": "0.4.0",
    "Read-Only Default": "0.1.0",
    "Source-of-Truth Checks": "0.1.0",
}

EXPECTED_AGENT_ROWS = {
    "ChatGPT Orchestrator": (
        ("Global Engineering",),
        "chatgpt-orchestrator",
    ),
    "GitHub Service Agent": (
        ("Global Engineering",),
        "github-service-agent",
    ),
    "Google Workspace Automation Engineer": (
        (
            "Global Engineering",
            "Python Standards",
            "Google Workspace Standards",
            "Notion Standards",
        ),
        "google-workspace-automation-engineer",
    ),
    "Modeling & Dashboard Governance Agent": (
        ("Global Engineering", "Dashboard Governance", "Notion Standards"),
        "modeling-dashboard-governance-agent",
    ),
    "Integration Manager": (
        ("Global Engineering", "Google Workspace Standards", "Notion Standards"),
        "integration-manager",
    ),
    "QA / Test Agent": (
        ("Global Engineering", "QA/Test Standards"),
        "qa-test-agent",
    ),
    "Agent Orchestrator": (
        ("Global Engineering", "Instructional Design Standards"),
        "agent-orchestrator",
    ),
    "Unit Alignment Agent": (
        (
            "Global Engineering",
            "Instructional Design Standards",
            "Notion Standards",
        ),
        "unit-alignment-agent",
    ),
    "Teacher Modeling Coach": (
        ("Global Engineering", "Instructional Design Standards"),
        "teacher-modeling-coach",
    ),
    "Instructional Materials Coach": (
        (
            "Global Engineering",
            "Google Workspace Standards",
            "Python Standards",
            "Instructional Design Standards",
        ),
        "instructional-materials-coach",
    ),
}


def _registry_rows() -> dict[str, tuple[tuple[str, ...], str]]:
    text = REGISTRY.read_text(encoding="utf-8")
    first_section = text.split("## Legacy Alias Resolution", 1)[0]
    rows: dict[str, tuple[tuple[str, ...], str]] = {}
    for line in first_section.splitlines():
        if not line.startswith("|") or line.startswith("|---") or "| Agent |" in line:
            continue
        columns = [part.strip() for part in line.strip("|").split("|")]
        if len(columns) != 3:
            continue
        tokens = tuple(
            token.strip() for token in columns[1].split(",") if token.strip()
        )
        rows[columns[0]] = (tokens, columns[2])
    return rows


def _inheritance_tokens() -> list[str]:
    return [
        token
        for tokens, _overlay in _registry_rows().values()
        for token in tokens
    ]


def _module_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for line in MODULE_VERSION_MAP.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or line.startswith("|---") or "| Module |" in line:
            continue
        columns = [part.strip() for part in line.strip("|").split("|")]
        if len(columns) == 2:
            versions[columns[0]] = columns[1]
    return versions


def test_no_shorthand_in_inheritance_registry() -> None:
    shorthand = {
        "Global",
        "Source-of-Truth",
        "Testing/Release",
        "Python",
        "Workspace",
        "Notion",
        "QA/Test",
        "Instructional Design",
        "Navigation Registry",
    }
    assert shorthand.isdisjoint(_inheritance_tokens())


def test_inheritance_tokens_are_canonical_modules() -> None:
    canonical = set(_module_versions())
    assert set(_inheritance_tokens()).issubset(canonical)


def test_baseline_modules_remain_standalone_and_versioned() -> None:
    versions = _module_versions()
    for module, version in BASELINE_MODULES.items():
        assert versions[module] == version


def test_common_overlay_declares_the_universal_baseline() -> None:
    content = COMMON_OVERLAY.read_text(encoding="utf-8")
    assert "baseline for all overlays" in content
    for module, version in BASELINE_MODULES.items():
        assert f"- {module} {version}" in content


def test_registry_documents_common_baseline_without_copying_policy() -> None:
    content = REGISTRY.read_text(encoding="utf-8")
    assert "Every registered agent overlay inherits the universal baseline" in content
    assert "`02_Agent_Overlays/_common-overlay-rules.md`" in content
    assert "are not repeated in\nindividual agent rows" in content


def test_individual_rows_do_not_repeat_universal_safety_modules() -> None:
    safety_modules = {"Read-Only Default", "Source-of-Truth Checks"}
    for agent, (tokens, _overlay) in _registry_rows().items():
        assert safety_modules.isdisjoint(tokens), agent


def test_canonical_agent_rows_preserve_expected_inheritance() -> None:
    assert _registry_rows() == EXPECTED_AGENT_ROWS


def test_every_canonical_agent_overlay_inherits_common_rules() -> None:
    for agent, (_tokens, overlay_slug) in _registry_rows().items():
        overlay = OVERLAY_DIR / f"{overlay_slug}.md"
        assert overlay.exists(), f"missing overlay for {agent}: {overlay}"
        content = overlay.read_text(encoding="utf-8")
        assert "See `_common-overlay-rules.md` plus:" in content, agent


GLOBAL_ENGINEERING = Path("01_Shared_Standards/global-engineering/README.md")


def test_mobile_terminal_command_ux_is_inherited_from_global_engineering() -> None:
    content = GLOBAL_ENGINEERING.read_text(encoding="utf-8")
    required_phrases = (
        "Mobile Terminal And Cloud Shell UX",
        "brief natural-language explanation immediately before the command",
        "one copy-and-paste command whenever practical",
        "dependent shell operations with `&&`",
        "or an equivalently fail-closed construction",
        "missing repository directory",
        "wrong working directory",
        "missing local branch",
        "remote branch fetch",
        "inactive virtual environment",
        "optional tool authentication",
        "narrow mobile displays",
        "shell prompts",
        "terminal output",
        "heredoc continuation prompts",
        "incomplete heredocs",
        "Python source directly as Bash commands",
        "Use multiple commands only when operator input is required between steps",
        "repository verification",
        "protected-branch",
        "stop-condition safeguards",
        "separate authorization is required",
        "potentially destructive operation requires inspection first",
    )
    for phrase in required_phrases:
        assert phrase in content


def test_mobile_terminal_command_ux_is_not_duplicated_in_agent_overlays() -> None:
    marker = "Mobile Terminal And Cloud Shell UX"
    for overlay in OVERLAY_DIR.glob("*.md"):
        if overlay.name == "_common-overlay-rules.md":
            continue
        assert marker not in overlay.read_text(encoding="utf-8"), overlay
