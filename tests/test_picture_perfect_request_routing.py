"""Regression coverage for the Picture Perfect / PPUX routing contract (#1280)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"
ROUTING = ROOT / "02_Agent_Overlays/chatgpt-orchestrator-picture-perfect-routing.md"
PPUX_README = ROOT / "08_Tooling/instructional-materials-coach/picture-perfect-coach/README.md"
PROMPT_FIXTURE = ROOT / "08_Tooling/instructional-materials-coach/picture-perfect-coach/src/fixtures/tutorial0-prompts.ts"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_orchestrator_routes_existing_picture_perfect_prompt_artifacts() -> None:
    overlay = read(ORCHESTRATOR)
    assert "Picture Perfect / PPUX tutorial prompt artifact" in overlay
    assert "canonical Instructional Materials Coach Picture Perfect capability" in overlay
    assert "chatgpt-orchestrator-picture-perfect-routing.md" in overlay
    assert "generic image-prompt authoring" in overlay


def test_tutorial_zero_natural_language_regression_is_explicit() -> None:
    routing = read(ROUTING)
    for intent in (
        "Show me what tutorial 0 looks like in image prompts",
        "Picture Perfect Tutorial 0 prompts",
        "Tutorial 0 image prompts",
        "show me Tutorial 0 prompts",
    ):
        assert intent in routing
    assert "three ready Adobe Express prompt cards" in routing
    assert "unsupported final-state details remain blocked" in routing


def test_routing_fails_closed_instead_of_fabricating_tutorial_steps() -> None:
    routing = read(ROUTING)
    for invariant in (
        "Do not silently fall back to generic generation",
        "Never replace missing evidence with plausible controls",
        "unknown or ambiguous tutorial does not produce fabricated PPUX output",
        "Missing approved application identity remains blocked",
        "Unsupported UI details remain blocked",
    ):
        assert invariant in routing


def test_generic_image_requests_and_provider_execution_stay_separate() -> None:
    routing = read(ROUTING)
    assert "generic image-generation or generic prompt-authoring request" in routing
    assert "normal generic path" in routing
    assert "Prompt derivation creates no image-provider execution authority" in routing
    assert "Routing alone does not call an image provider" in routing


def test_contract_reuses_existing_ppux_owners_and_tutorial_fixture() -> None:
    routing = read(ROUTING)
    readme = read(PPUX_README)
    fixture = read(PROMPT_FIXTURE)
    assert "Do not duplicate the prompt engine or Tutorial 0 fixture" in routing
    assert "Model -> Upload -> Review -> Prompts -> Ready" in routing
    assert "Model -> Upload -> Review -> Prompts -> Ready" in readme
    assert "Adobe Express" in fixture
    for ready_step in (
        "tutorial0-step-01-organize-location",
        "tutorial0-step-03-square-file",
        "tutorial0-step-05-landscape-file",
    ):
        assert ready_step in fixture
    assert "tutorial0BlockedFinalState" in fixture
    assert "Exact favorite-food filenames" in fixture
