# Standard Dashboard Structure

Companion to `README.md` in this directory.

Each governance dashboard should document these sections:

1. Dashboard Mission
2. Owns
3. Consumes
4. Hands Off To
5. Governance Rules
6. Boundaries
7. Common Routing Mistakes
8. Production Relationship
9. References

### Dashboard Mission

One sentence stating the dashboard's canonical role.

### Owns

List only the decisions, fields, summaries, or readiness states for which this
dashboard is the canonical owner.

### Consumes

List upstream summaries used by this dashboard and identify the owner of each
summary.

### Hands Off To

List downstream dashboards or production agents that consume this dashboard's
summary.

### Governance Rules

State what this dashboard may decide and what it must not decide.

### Boundaries

Clarify common false approvals. For example, Modeling Handoff Ready is not slide
approval, and Packet Generation Gate is not Production Authorized.

### Common Routing Mistakes

Document frequent incorrect interpretations and the correct owner or route.

### Production Relationship

State how the dashboard relates to Production Control and whether it can or
cannot authorize generation.

### References

Link to the Governance v1.0 baseline, ownership map, relevant source dashboards,
and downstream consumers.
