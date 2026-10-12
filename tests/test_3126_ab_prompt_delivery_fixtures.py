"""Regression fixtures for #3126 (two runnable A/B arms), against the
canonical Agent Interaction Output Standard.

These are structural Markdown checks over modeled response shapes taken from
the October 2026 Photography diagnostic campaign. They prove the contract's
mechanically checkable invariants (two complete independently runnable arm
payloads, equivalent controls, exactly one independent variable, fresh-chat
isolation, analysis/delta-only rejection); they are not live-model runs.
Native-host response acceptance is tracked separately on #3126.
"""
import re

import pytest

# ---------------------------------------------------------------------------
# Shared Markdown fence parser (CommonMark close rule: a closing fence must be
# at least as long as the opener and carry no info string).
# ---------------------------------------------------------------------------

_FENCE_RUN_RE = re.compile(r"^`{3,}")


def _fence_spans(text):
    """Return (spans, unclosed). spans: list of (length, open_line, close_line)."""
    spans = []
    opener = None
    for idx, line in enumerate(text.splitlines()):
        stripped = line.strip()
        if not stripped.startswith("```"):
            continue
        run = len(stripped) - len(stripped.lstrip("`"))
        rest = stripped[run:]
        if "`" in rest:
            continue  # inline code, not a fence line
        if opener is None:
            opener = (run, idx)
        elif not rest and run >= opener[0]:
            spans.append((opener[0], opener[1], idx))
            opener = None
        # shorter runs and info-string fences inside are payload content
    return spans, opener


def _single_copy_ready_region(response):
    """Extract the one fenced copy-ready region or raise describing the breach."""
    spans, opener = _fence_spans(response)
    if opener is not None:
        raise AssertionError("copy-ready fence is unclosed; payload region is unbounded")
    if len(spans) != 1:
        raise AssertionError(
            f"expected exactly one copy-ready region, found {len(spans)} "
            "(payload was split across multiple fenced blocks)"
        )
    _, start, end = spans[0]
    return "\n".join(response.splitlines()[start + 1 : end])


def _longest_inner_fence_run(payload):
    runs = [len(m.group(0)) for line in payload.splitlines() for m in [_FENCE_RUN_RE.match(line.strip())] if m]
    return max(runs) if runs else 0


# ---------------------------------------------------------------------------
# #3126 fixtures: "Let's A/B test the worksheet generation maker."
# ---------------------------------------------------------------------------

_TEACHER_UTTERANCE_3126 = "Make a Rule of Thirds worksheet for my 9th graders."

_CONTROLLED_3126 = """Teacher request: """ + _TEACHER_UTTERANCE_3126 + """
Task: one-page Rule of Thirds worksheet for 9th grade.
Concept: Rule of Thirds only.
Artifact: one DOCX worksheet file.
Sources: no project files attached; generate from the prompt alone."""

_SENTENCE_A_3126 = "Include four visual examples, one for each composition technique."
_SENTENCE_B_3126 = (
    "Include four actual photographic examples, one for each composition technique. "
    "Do not use drawings, diagrams, icons, vector art, or placeholders as the examples."
)

_ARM_A_3126 = _CONTROLLED_3126 + "\n" + _SENTENCE_A_3126
_ARM_B_3126 = _CONTROLLED_3126 + "\n" + _SENTENCE_B_3126

_ARM_META_3126 = """Model: GPT-5.4. Reasoning: Low. Conversation: fresh chat (separate new chat per arm)."""

_RESPONSE_3126_GOOD = """Request: Let's A/B test the worksheet generation maker.

Run each arm in a separate fresh chat. Independent variable: visual-role wording.

## Arm A — generic visual examples
""" + _ARM_META_3126 + """
````
""" + _ARM_A_3126 + """
````

## Arm B — photographic examples
""" + _ARM_META_3126 + """
````
""" + _ARM_B_3126 + """
````

## Analysis
Arm A tests whether generic "visual examples" wording suffices; Arm B tests the explicit photographic constraint. Compare which arm produces actual photographs."""

# The 2026-10-07 Focus Test 2 reproduction: only delta clauses, no complete prompts.
_RESPONSE_3126_BAD_DELTAS = """Request: Let's A/B test the worksheet generation maker.

## Arm A
```
Include four visual examples.
```

## Arm B
```
Include four actual photographic examples. Do not use drawings, diagrams, icons, vector art, or placeholders as the examples.
```
"""

# The 2026-09-30 reproduction: experiment plan with no runnable prompts.
_RESPONSE_3126_BAD_ANALYSIS_ONLY = """Request: Let's A/B test the worksheet generation maker.

I inspected the worksheet maker and designed an A/B comparison of visual-example wording. Arm A uses generic wording and Arm B uses photographic wording. I recommend running each in a fresh chat with equivalent controls and comparing the artifacts."""

_RESPONSE_3126_SINGLE = """Request: Create a one-page Rule of Thirds worksheet for 9th graders.

Here is the runnable prompt:

```
""" + _CONTROLLED_3126 + """
```
"""


def _extract_arm_payloads(response):
    assert "## Arm A" in response and "## Arm B" in response, "both arms must be labeled"
    arm_a = response.split("## Arm A", 1)[1].split("## Arm B", 1)[0]
    arm_b = response.split("## Arm B", 1)[1].split("## Analysis", 1)[0]
    payload_a = _single_copy_ready_region(arm_a)
    payload_b = _single_copy_ready_region(arm_b)
    return payload_a, payload_b, arm_a, arm_b


def _check_two_arm_response(response):
    payload_a, payload_b, arm_a, arm_b = _extract_arm_payloads(response)
    # each arm is a COMPLETE runnable prompt: controlled text repeated in full
    assert _CONTROLLED_3126 in payload_a, "Arm A is missing the shared controlled prompt body"
    assert _CONTROLLED_3126 in payload_b, "Arm B is missing the shared controlled prompt body"
    # same realistic teacher utterance in both arms
    assert _TEACHER_UTTERANCE_3126 in payload_a and _TEACHER_UTTERANCE_3126 in payload_b
    # exactly one independent variable differs
    assert payload_a != payload_b
    assert payload_a.replace(_SENTENCE_A_3126, "") == payload_b.replace(_SENTENCE_B_3126, "")
    # clean-context instruction per arm
    assert "fresh chat" in arm_a.casefold() and "fresh chat" in arm_b.casefold()
    return payload_a, payload_b


def test_3126_contract_requires_two_runnable_arms():
    from pathlib import Path

    standard = Path(__file__).resolve().parents[1].joinpath(
        "01_Shared_Standards/global-engineering/agent-interaction-output-standard.md"
    ).read_text(encoding="utf-8")
    for phrase in (
        "one complete copy-ready prompt per arm",
        "labeled Arm A and Arm B",
        "never replaces them",
    ):
        assert phrase in standard


def test_3126_two_complete_arms_for_exact_regression_input():
    assert "Let's A/B test the worksheet generation maker." in _RESPONSE_3126_GOOD
    payload_a, payload_b = _check_two_arm_response(_RESPONSE_3126_GOOD)[:2]
    assert "Independent variable" in _RESPONSE_3126_GOOD
    # analysis may follow the runnable prompts but cannot replace them
    analysis_at = _RESPONSE_3126_GOOD.index("## Analysis")
    assert _RESPONSE_3126_GOOD.index("## Arm A") < analysis_at
    assert _RESPONSE_3126_GOOD.index("## Arm B") < analysis_at


def test_3126_delta_only_arms_are_rejected():
    with pytest.raises(AssertionError, match="shared controlled prompt body"):
        _check_two_arm_response(_RESPONSE_3126_BAD_DELTAS)


def test_3126_analysis_only_response_is_rejected():
    with pytest.raises(AssertionError, match="both arms must be labeled"):
        _check_two_arm_response(_RESPONSE_3126_BAD_ANALYSIS_ONLY)


def test_3126_ordinary_single_request_unaffected():
    region = _single_copy_ready_region(_RESPONSE_3126_SINGLE)
    assert _CONTROLLED_3126 in region
    assert "## Arm A" not in _RESPONSE_3126_SINGLE  # no arm scaffolding required
