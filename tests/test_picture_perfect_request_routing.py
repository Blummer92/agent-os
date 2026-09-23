"""Regression coverage for the Picture Perfect / PPUX routing contract (#1280, #1492, #2526)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"
PPUX_README = ROOT / "08_Tooling/instructional-materials-coach/picture-perfect-coach/README.md"
PROMPT_FIXTURE = ROOT / "08_Tooling/instructional-materials-coach/picture-perfect-coach/src/fixtures/tutorial0-prompts.ts"
ROUTING_STANDARD = ROOT / "01_Shared_Standards/instructional-design/canonical-classroom-artifact-resolution.md"
REUSABLE_CAPABILITIES = ROOT / "04_Registry/reusable-capabilities.yml"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def routing_section() -> str:
    text = read(ORCHESTRATOR)
    marker = "## Picture Perfect / PPUX Routing\n"
    assert marker in text
    return text.split(marker, 1)[1].split("\n## ", 1)[0]


def test_orchestrator_routes_resolved_picture_perfect_prompt_artifacts() -> None:
    overlay = read(ORCHESTRATOR)
    assert "canonical request/context evidence resolves" in overlay
    assert "registered Instructional Materials Coach" in overlay
    assert "existing Picture Perfect package" in overlay
    assert "before any generic image-prompt authoring" in overlay


def test_tutorial_zero_acceptance_utterances_are_explicit_without_becoming_a_phrase_parser() -> None:
    routing = routing_section()
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
    routing = routing_section()
    for invariant in (
        "Return the current canonical PPUX state without rewriting it",
        "Preserve blocked outcomes visibly",
        "If PPUX returns no ready output, say so with the canonical reason",
        "Do not silently fall back to generic generation",
        "A fully blocked PPUX result does not trigger generic fallback",
    ):
        assert invariant in routing


def test_generic_image_requests_and_provider_execution_stay_separate() -> None:
    routing = routing_section()
    assert "Generic image-generation or prompt-authoring requests" in routing
    assert "normal generic path" in routing
    assert "Prompt derivation creates no image-provider execution authority" in routing
    assert "Routing alone does not call an image provider" in routing


def test_contract_reuses_current_picture_perfect_capability_without_pinning_card_content() -> None:
    routing = routing_section()
    readme = read(PPUX_README)
    fixture = read(PROMPT_FIXTURE)
    assert "do not duplicate its prompt engine" in routing
    assert "Model -> Upload -> Review -> Prompts -> Ready" in routing
    assert "Model -> Upload -> Review -> Prompts -> Ready" in readme
    assert "tutorial0PromptCards" in fixture
    assert "tutorial0CapturedPromptCards" in fixture
    assert "Do not pin a ready-card count" in routing


def test_routing_preserves_capture_evidence_and_application_identity_when_present() -> None:
    routing = routing_section()
    readme = read(PPUX_README)
    assert "approved capture evidence" in routing
    assert "application identity" in routing
    assert "F2 captured-screen binding" in readme
    assert "recording_sha256 + source_index + source_fingerprint" in readme


def test_unknown_tutorial_and_missing_evidence_fail_visibly() -> None:
    routing = routing_section()
    assert "Unknown or ambiguous tutorials do not produce fabricated PPUX output" in routing
    assert "Never replace missing evidence with plausible controls" in routing
    assert "blocker reason codes" in routing


def test_named_classroom_artifact_resolution_continues_across_governed_sources() -> None:
    standard = read(ROUTING_STANDARD)
    assert "Notion planning/workflow context -> Google Drive companion artifacts" in standard
    assert "an empty exact-name search is not terminal evidence" in standard
    assert "bounded canonical folder" in standard
    assert "Do not ask the user to locate or restate" in standard


def test_legacy_or_semantic_matches_cannot_override_canonical_application_identity() -> None:
    standard = read(ROUTING_STANDARD)
    assert "application identity" in standard
    assert "legacy" in standard
    assert "plausible filename" in standard
    assert "reject the candidate" in standard


def test_screenshot_chronology_does_not_create_instructional_identity() -> None:
    standard = read(ROUTING_STANDARD)
    assert "chronology alone" in standard
    assert "Image 1" in standard
    assert "image count" in standard
    assert "fail closed" in standard


def test_ppux_projection_capability_is_discoverable_with_exact_2525_contract() -> None:
    registry = read(REUSABLE_CAPABILITIES)
    assert "capability_id: ppux-picture-perfect-prompt-projection" in registry
    # The invocation identity is the real statically exported #2525 entrypoint
    # contract, not a free-form label: the registry's public-interface check
    # resolves each symbol against the capability's canonical source.
    assert "promptProjectionEntrypoint:projectTutorialPromptCards" in registry
    assert "promptProjectionEntrypoint:PROMPT_PROJECTION_INPUT_VERSION" in registry
    assert "promptProjectionEntrypoint:PROMPT_PROJECTION_RESULT_VERSION" in registry
    assert "picture-perfect-prompt-projection-result-v1" in registry
    assert "projection-capability-unavailable" in registry
    assert "canonical-ppux-blocked" in registry


def test_resolved_ppux_requests_consume_governed_result_without_generic_reconstruction() -> None:
    routing = routing_section()
    assert "Invoke only the fixed governed operation `ppux-picture-perfect-prompt-projection`" in routing
    assert "Consume only `picture-perfect-prompt-projection-result-v1` evidence" in routing
    assert "policy prose, fixtures, and generic language generation are not substitutes" in routing
    assert "A fully blocked governed result is a successful routing outcome" in routing


def test_ppux_result_consumption_preserves_state_provenance_and_provider_application_separation() -> None:
    routing = routing_section()
    for invariant in (
        "source fingerprint",
        "execution SHA/projection identity",
        "prompt-card order",
        "ready/blocked state",
        "provider-neutral `portablePrompt`",
        "provenance",
        "Canva remains separate from the canonical modeled tutorial application",
    ):
        assert invariant in routing


def test_registered_ppux_capability_binds_real_projection_contract_and_behavior_tests() -> None:
    registry = read(REUSABLE_CAPABILITIES)
    record = registry.split(
        "  - capability_id: ppux-picture-perfect-prompt-projection\n", 1
    )[1].split("\n  - capability_id:", 1)[0]
    assert "picture-perfect-prompt-projection-input-v1" in record
    assert "picture-perfect-prompt-projection-result-v1" in record
    assert (
        "08_Tooling/instructional-materials-coach/picture-perfect-coach/"
        "src/promptProjectionEntrypoint.test.ts"
    ) in record

    behavior = read(
        ROOT
        / "08_Tooling/instructional-materials-coach/picture-perfect-coach/"
        "src/promptProjectionEntrypoint.test.ts"
    )
    assert "preserves ready and blocked prompt cards without rewriting either state" in behavior
    assert "keeps source/application provenance provider-neutral and non-authorizing" in behavior
    assert "fails closed on malformed or unsupported input without throwing" in behavior
