# Risk Owner Map

Each cross-cutting risk has exactly one canonical owner issue. Downstream
issues and PRs link to the owner instead of copying risk text. The rule
lives in `01_Shared_Standards/github/issue-lifecycle-standard.md`; this
file is registry data only and authorizes nothing.

| Risk | Canonical owner | Affected downstream | Mitigation or gate | State |
|---|---|---|---|---|
| Approval replay after governed input movement | #398 | #330, future WSC4+ | Content-bound approval records with deterministic invalidation | open |
| Branch, base, and tested-SHA drift | #330 | all implementation PRs | Exact final-head validation before merge | partially mitigated |
| Connected evidence incompleteness | #376 | #375, #379, future WSC5+ | Fail-closed pagination and permission evidence | open |
| Validation-policy and Cloud Build drift | #240 | #368, #369, #370 | Results bound to the exact tested SHA | open |
| Workspace, lease, and active-work collision | #330 | future WSC5-WSC7 | Isolated workspace and one lease per issue | open |
| Acceptance-parser compatibility drift | #358 | #398, readiness consumers | Canonical scanner convergence | open |
| Protected-branch enforcement gap | #231 | #233, #234, #235, #236 | Layered local safeguards, future ruleset handoff | open |
| Documentation-impact gaps | #304 | #306, #310, #323 | Documentation-impact readiness evidence | open |
| Issue-lifecycle authority and retired-scope revival | #543 | all issue intake and refactor/consolidation work | Immutable closed-body rule, prior-scope review, and behavioral/value evidence | mitigated / monitoring |

Update rows through normal registry change control when an owner issue
closes or ownership transfers. A risk with two claimed owners is a
`needs-decision` condition.
