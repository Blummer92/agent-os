# D8 Classroom-Ready Standard (#3259)

**Status:** Rule statement (not an enforcement mechanism).
**Enforcement:** `classroom_admission.py` (`classify_classroom_admission`).

## Rule

Classroom-ready requires a canonical `imc-build-receipt-v1` build record.
An artifact is admitted as classroom-ready only when its build receipt
evidence shows all three:

1. `contract_version == "imc-build-receipt-v1"` — the receipt is the canonical
   build evidence contract, not an ad-hoc claim.
2. `succeeded is True` — the canonical build completed successfully.
3. `terminal_qa_state == "verified"` — terminal QA verified the artifacts.

Admission rests on verifiable evidence fields only. Caller authority claims —
including any `classroom_ready` flag a caller asserts — never influence
admission. The admission predicate grants no authority; downstream governors
still own execution, production, and classroom authorization.

## Non-authoritative sources

Direct ChatGPT or local-generator output (including DOCX) is classified
**non-authoritative** for classroom-ready. These are noncanonical parallel
paths that can bypass the governed Notion → Agent OS → Drive production
pipeline (#3259 D1, D1b). They carry no canonical build receipt and therefore
cannot satisfy this standard.

Labeling ChatGPT-native output as non-authoritative is chat-side behavior
owned by chatgpt-orchestrator and is not reachable from the repository. The
repository enforces this standard at the admission boundary: no receipt, no
admission.

## Scope notes

- This standard governs the **admission question** (may this artifact be
  treated as classroom-ready?). It does not authorize production, Drive
  writes, or classroom distribution — those remain separately governed.
- Fail-closed: malformed receipts, missing fields, or any single failed
  evidence condition yields not-admitted.
- #3385 (direct ChatGPT/DOCX route) remains open as the acceptance/regression
  case until this admission mechanism is enforced and proven.
