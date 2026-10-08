"""Regression fixtures for #3089 (copy-ready prompt delivery), against the
canonical Agent Interaction Output Standard.

These are structural Markdown checks over modeled response shapes taken from
the October 2026 Photography diagnostic campaign. They prove the contract's
mechanically checkable invariants (one copy-ready region, nested-fence
delimiter rule, blockquote rejection, ordinary prose unaffected); they are not
live-model runs. Native-host rendering acceptance is tracked separately on
#3089.
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
# #3089 fixtures: long multi-section Agent OS execution prompt
# ---------------------------------------------------------------------------

_PAYLOAD_3089 = """MISSION
Investigate #3367 with a GitHub Codespace and report the findings.

REPOSITORY
Blummer92/agent-os

STEPS
1. Reacquire the issue state and comments.
2. Inspect the repository history for the relevant lineage.

### Shell evidence
Run the history search exactly as shown:

```bash
git log --oneline --grep='3367' -i | head -20
gh issue view 3367 --comments | head -60
```

### Python evidence
Normalize the retrieved rows with the existing helper:

```python
from dynamic_credentials import add_surrogate_to_request

def fetch_issue(number):
    req = build_request(f"/repos/Blummer92/agent-os/issues/{number}")
    add_surrogate_to_request(req, "custom.github")
    return read_json(req)
```

### Markdown-shaped content inside the prompt
The final report must use this shape:

### Findings
- one finding per line
- no prose outside the listed sections

REPORT
Post evidence as an issue comment and read it back before reporting done."""

_RESPONSE_3089_GOOD = """Here is the reusable prompt for the Muse/Codespaces mission. Copy the entire block below into a fresh chat.

````
""" + _PAYLOAD_3089 + """
````

Run it with a fresh chat and report back the issue comment id."""

# The 2026-10-07 nested-fence reproduction: the same payload wrapped in a
# plain triple-backtick fence, so the inner ``` examples split the outer block.
_RESPONSE_3089_BAD_NESTED = """Here is the reusable prompt for the Muse/Codespaces mission. Copy the entire block below into a fresh chat.

```
""" + _PAYLOAD_3089 + """
```

Run it with a fresh chat and report back the issue comment id."""

_PAYLOAD_3089_SHORT = "Post the investigation result as a comment on #3120, then read the comment back to prove it persisted."

_RESPONSE_3089_SHORT = """Here is the handoff instruction to paste into the execution chat:

```
""" + _PAYLOAD_3089_SHORT + """
```
"""

_RESPONSE_3089_BLOCKQUOTE = """> Post the investigation result as a comment on #3120, then read the comment back to prove it persisted.
>
> Include the exact head SHA in the report."""

_RESPONSE_3089_PROSE = """The investigation is complete. The root cause was a missing fence-delimiter rule, and the fix adds it to the output standard. No further action is needed."""


def test_3089_contract_requires_longer_outer_fence():
    from pathlib import Path

    standard = Path(__file__).resolve().parents[1].joinpath(
        "01_Shared_Standards/global-engineering/agent-interaction-output-standard.md"
    ).read_text(encoding="utf-8")
    for phrase in (
        "fence strictly longer than any fence run inside the payload",
        "no payload text escapes the copy-ready region",
    ):
        assert phrase in standard


def test_3089_long_prompt_with_examples_stays_one_region():
    region = _single_copy_ready_region(_RESPONSE_3089_GOOD)
    assert region == _PAYLOAD_3089
    # outer fence (4) strictly longer than any inner fence run (3)
    assert _longest_inner_fence_run(_PAYLOAD_3089) == 3
    assert "Here is the reusable prompt" not in region  # explanation stays outside


def test_3089_nested_fence_split_is_detected():
    # The violating shape must be mechanically distinguishable from the good one:
    # the inner ``` runs split the outer block (multiple regions and/or a
    # dangling unclosed fence), so the complete payload no longer sits in one region.
    with pytest.raises(AssertionError):
        _single_copy_ready_region(_RESPONSE_3089_BAD_NESTED)
    spans, opener = _fence_spans(_RESPONSE_3089_BAD_NESTED)
    assert len(spans) > 1 or opener is not None
    # payload text escaped: no single region holds the complete payload
    regions = ["\n".join(_RESPONSE_3089_BAD_NESTED.splitlines()[s + 1 : e]) for _, s, e in spans]
    assert not any(_PAYLOAD_3089 in r for r in regions)


def test_3089_short_prompt_one_region_explanation_outside():
    region = _single_copy_ready_region(_RESPONSE_3089_SHORT)
    assert region == _PAYLOAD_3089_SHORT
    assert "handoff instruction" not in region


def test_3089_blockquote_payload_has_no_copy_ready_region():
    spans, opener = _fence_spans(_RESPONSE_3089_BLOCKQUOTE)
    assert spans == [] and opener is None  # blockquote is not a copy-ready region
    assert _PAYLOAD_3089_SHORT in _RESPONSE_3089_BLOCKQUOTE  # fixture really carries the payload


def test_3089_ordinary_prose_unaffected():
    spans, opener = _fence_spans(_RESPONSE_3089_PROSE)
    assert spans == [] and opener is None  # prose requests no payload; none required

