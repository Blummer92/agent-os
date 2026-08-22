"""Regression coverage for the independent #1343 privilege-boundary review."""

from pathlib import Path

ROOT = Path(__file__).parents[1]
PRIVILEGED = (
    ROOT
    / "08_Tooling/agent-os-execution-service/scripts/agent-os-host-install"
)
DOCS = (
    ROOT
    / "08_Tooling/agent-os-execution-service/docs/HOST_RUNTIME_INSTALLATION.md"
)


def _active_sudoers_rule() -> str:
    text = DOCS.read_text(encoding="utf-8")
    block = text.split("<!-- sudoers-begin -->", 1)[1].split(
        "<!-- sudoers-end -->", 1
    )[0]
    rules = [line.strip() for line in block.splitlines() if line.strip().startswith("sa_")]
    assert len(rules) == 1
    return rules[0]


def test_sudoers_rule_binds_one_literal_authorized_source_sha() -> None:
    rule = _active_sudoers_rule()
    assert "*" not in rule
    assert "[0-9a-f]" not in rule
    assert rule.count("<AUTHORIZED_SOURCE_SHA>") == 1

    allowed = "a" * 40
    denied = "b" * 40
    rendered = rule.replace("<UNIQUE_ID>", "123456789").replace(
        "<AUTHORIZED_SOURCE_SHA>", allowed
    )
    assert rendered.endswith(f"--source-sha {allowed}")
    assert denied not in rendered


def test_privileged_build_uses_hash_pinned_offline_backend() -> None:
    text = PRIVILEGED.read_text(encoding="utf-8")
    assert "SETUPTOOLS_VERSION=83.0.0" in text
    assert (
        "SETUPTOOLS_SHA256="
        "29b23c360f22f414dc7336bb39178cc7bcbf6021ed2733cde173f09dba19abb3"
    ) in text
    assert "WHEEL_VERSION=0.47.0" in text
    assert (
        "WHEEL_SHA256="
        "212281cab4dff978f6cedd499cd893e1f620791ca6ff7107cf270781e587eced"
    ) in text
    assert "--require-hashes" in text
    assert 'PYTHONPATH="$build_tools" PIP_NO_INDEX=1 python3 -m pip wheel' in text
    assert "--no-build-isolation" in text

    system_install = text.split("PIP_NO_INDEX=1 python3 -m pip install", 1)[1]
    system_install = system_install.split("(", 1)[0]
    assert "--no-index" in system_install
    assert "--no-deps" in system_install
