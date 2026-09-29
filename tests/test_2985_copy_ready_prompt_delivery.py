"""Regression contract for #2985 reusable prompt delivery."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
STANDARD=ROOT/"01_Shared_Standards/global-engineering/agent-interaction-output-standard.md"

def test_2985_requested_reusable_prompt_is_one_copy_ready_block_not_blockquote():
    text=" ".join(STANDARD.read_text(encoding="utf-8").split())
    for phrase in ("explicitly asks for a prompt to paste elsewhere","one dedicated fenced copy-ready block","explanation outside it","never as a blockquote"):
        assert phrase in text
