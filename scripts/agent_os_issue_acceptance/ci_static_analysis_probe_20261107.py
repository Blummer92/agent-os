"""Disposable static-analysis audit fixture. NEVER MERGE.

Deliberately includes a Python type mismatch and an isolated call-graph
candidate. No security exploit, credentials, external I/O, or production calls.
Pyan3 analyzes this directory but its findings are advisory, not mandatory
lint errors. Pylance is an editor service; Pyright is the CLI analogue.
"""

def audit_type_mismatch() -> int:
    result: int = "not-an-integer"
    return result


def audit_pyan3_disconnected_candidate() -> str:
    return "AUDIT_PYAN3_DISCONNECTED_CANDIDATE_20261107"
