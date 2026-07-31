"""Visual Asset Sync reconciliation planner and bounded read adapters.

The planner core is deterministic and offline. Optional adapters may perform
separately authorized bounded reads. No package component performs an external
write.
"""

__version__ = "0.1.0"
