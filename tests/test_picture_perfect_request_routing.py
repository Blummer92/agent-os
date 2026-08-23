"""Regression coverage for the Picture Perfect / PPUX routing contract (#1280)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"
ROUTING = ROOT / "02_Agent_Overlays/chatgpt-orchestrator-picture-perfect-routing.md"
PPUX_README = ROOT / "08_Tooling/instructional-materials-coach/picture-perfect-coach/README.md"
PROMPT_FIXTURE = ROOT / "08_Tooling/instructional-materials-coach/picture-perfect-coach/src/fixtures/tutorial0-prompts.ts"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_orchestrator_routes_resolved_picture_perfect_prompt_artifacts() -> None:
    overlay = read(ORCHESTRATOR)
    assert "canonical request/context evidence resolves" in overlay
    assert "registered Instructional Materials Coach" in overlay
    assert "chatgpt-orchestrator-picture-perfect-routing.md" in overlay
    assert "never reconstruct missing software UI as a fallback" in overlay


def test_tutorial_zero_acceptance_utterances_are_explicit_without_becoming_a_phrase_parser() -> None:
    routing = read(ROUTING)
    for intent in (
        "Show me what tutorial 0 looks like in image prompts",
        "Picture Perfect Tutorial 0 prompts",
        "Tutorial 0 image prompts",
        "show me Tutorial 0 prompts",
    ):
        assert intent in routing
    assert "regression inputs, not a new phrase-matching vocabulary" in routing
    assert "routing provenance and state fidelity only" in routing
    assert "does not assert a card count or specific interface text" in routing


def test_routing_preserves_current_ppux_state_and_blockers_without_generic_fallback() -> None:
    routing = read(ROUTING)
    for invariant in (
        "Return the current canonical PPUX state without rewriting it",
        "Preserve blocked outcomes visibly",
        "If PPUX returns no ready output, say so with the canonical reason",
        "Do not silently fall back to generic generation",
        "A fully blocked PPUX result does not trigger generic fallback",
    ):
        assert invariant in routing


def test_generic_image_requests_and_provider_execution_stay_separate() -> None:
    routing = read(ROUTING)
    assert "generic image-generation or generic prompt-authoring request" in routing
    assert "normal generic path" in routing
    assert "Prompt derivation creates no image-provider execution authority" in routing
    assert "Routing alone does not call an image provider" in routing


def test_contract_reuses_current_picture_perfect_capability_without_pinning_card_content() -> None:
    routing = read(ROUTING)
    readme = read(PPUX_README)
    fixture = read(PROMPT_FIXTURE)
    assert "Do not duplicate the prompt engine" in routing
    assert "Model -> Upload -> Review -> Prompts -> Ready" in routing
    assert "Model -> Upload -> Review -> Prompts -> Ready" in readme
    assert "tutorial0PromptCards" in fixture
    assert "tutorial0CapturedPromptCards" in fixture
    assert "Do not pin a ready-card count" in routing


def test_routing_preserves_capture_evidence_and_application_identity_when_present() -> None:
    routing = read(ROUTING)
    readme = read(PPUX_README)
    assert "approved capture evidence" in routing
    assert "application identity" in routing
    assert "F2 captured-screen binding" in readme
    assert "recording_sha256 + source_index + source_fingerprint" in readme


def test_unknown_tutorial_and_missing_evidence_fail_visibly() -> None:
    routing = read(ROUTING)
    assert "unknown or ambiguous tutorial does not produce fabricated PPUX output" in routing
    assert "Missing approved application identity or visual evidence remains blocked" in routing
    assert "Blocked reason codes and teacher-facing explanations are not filtered out" in routing
