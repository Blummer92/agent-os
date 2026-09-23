# Candidate-Bound Pre-PR Cloud Build Activation

Issue #1456 owns only the production composition seam between existing canonical components.

Required sequence:

`CandidatePacket execution-candidate -> current ExecutionAuthorizationEvidence -> existing validation command plan -> existing pre-PR dispatch decision -> existing CloudBuildProviderInvocation -> existing CloudBuildProviderAdapter -> canonical terminal validation evidence`.

The composition must preserve exact repository, issue/invocation, non-protected branch, expected/tested SHA, fixed command identity, validation-only behavior, concurrency 1, and automatic retry false.

It must not accept arbitrary shell commands, argv, caller-selected test paths, selectors, or environment extensions. It must not infer execution authorization from readiness or candidate state. Provider success grants no merge, publication, production, or external-write authority.

Normal tests must use injected provider clients and perform no live Cloud Build, GitHub mutation, credential/IAM, workflow, or production effect.

If current canonical components cannot be composed without changing their public authority or validation semantics, stop `needs-decision` rather than adding another executor/provider/authorization model.
