"""Regression contract for #3029 connected refresh continuation."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OVERLAY=ROOT/"02_Agent_Overlays/chatgpt-orchestrator.md"

def test_3029_literal_connector_gap_does_not_skip_governed_refresh_route():
    text=" ".join(OVERLAY.read_text(encoding="utf-8").split())
    for phrase in ("Before declaring a refresh execution surface unavailable","resolve the registered governed refresh capability","attempt the existing linked-issue trigger route","lacks a literal direct branch-refresh action","report that concrete rejection instead of a generic execution-surface blocker"):
        assert phrase in text
