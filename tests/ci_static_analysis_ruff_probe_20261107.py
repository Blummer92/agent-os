"""Disposable Ruff negative control. NEVER MERGE.

The undefined symbol is deliberate. Ruff's F821 correctness rule should
reject this file; no test or production runtime imports this module.
"""

def audit_ruff_undefined_symbol() -> object:
    return CI_TRUST_RUFF_UNDEFINED_NAME_20261107
