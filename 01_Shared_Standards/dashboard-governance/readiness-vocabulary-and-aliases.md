# Readiness Vocabulary And Historical Aliases

Companion to `README.md` in this directory.

## Canonical readiness vocabulary

| Term | Owner | Boundary |
|---|---|---|
| Unit Generation Approval | Unit Alignment & Readiness | Not packet readiness or production authorization. |
| Modeling Handoff Ready | Teacher Modeling Coach | Not slide approval, worksheet approval, or production authorization. |
| Evidence Handoff Ready | Assessment Agent / Student Evidence Coach | Not worksheet approval or production authorization. |
| Assessment Handoff Ready | Assessment Agent / Student Evidence Coach | Not packet approval or production authorization. |
| Source-Control Gate | Curriculum Source Control | Not production authorization. |
| Packet Generation Gate | Daily Generation Packet | Not Unit Generation Approval or Production Authorized. |
| Packet Slide Readiness | Daily Generation Packet | Not slide production approval. |
| Packet Worksheet Readiness | Daily Generation Packet | Not worksheet production approval. |
| Packet Assessment Readiness | Daily Generation Packet | Not assessment production approval. |
| Production Authorized | Production Control | Final production authorization. |

## Historical alias policy

Historical labels remain discoverable. Treat them as aliases until a governed
migration renames fields or options after dependency checks.

| Historical term | Governance v1.0 interpretation |
|---|---|
| Ready for slides | Modeling Handoff Ready only, unless explicitly owned by Daily Generation Packet as packet/day slide readiness. |
| Ready for worksheet agent | Evidence Handoff Ready only. |
| Ready for assessment agent | Assessment Handoff Ready only. |
| Generation Gate | Must be qualified by owner. |
| Production Ready | Production Authorized only when owned by Production Control. |
| Generation Readiness | Unit Generation Approval or Packet Generation Gate depending owner. |
| Worksheet Agent Ready Check | Worksheet Source Packet Ready Check when used in Source Control. |
| Source-Control Production Readiness | Source-Control Routing Readiness, not final production authorization. |

Do not infer ownership from legacy wording.
