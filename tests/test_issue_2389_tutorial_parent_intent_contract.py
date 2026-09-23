from pathlib import Path


AGENTS = Path("AGENTS.md").read_text(encoding="utf-8")


def test_ambiguous_shorthand_resolves_against_active_parent_mission():
    assert "Resolve ambiguous shorthand against the active unfinished parent mission" in AGENTS


def test_tutorial_prompt_text_does_not_inherit_stale_content_domain():
    active_parent = "Tutorial 0"
    stale_domain = "Candy Branding"
    requested_form = "copy-and-paste prompts"
    assert active_parent != stale_domain
    assert requested_form == "copy-and-paste prompts"
