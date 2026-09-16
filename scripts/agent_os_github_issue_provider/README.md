# Agent OS GitHub Issue Provider

This package supplies read-only GitHub issue pages to the existing Agent OS issue scanner and owns the shared PyGithub client-construction and bounded request-execution boundaries used by repository GitHub adapters.

## Boundaries

- `auth.build_installation_client(...)` remains the selected-repository GitHub App client for scanner-proof work.
- `auth.build_token_client(...)` is the single `GITHUB_TOKEN` / `GH_TOKEN` PyGithub client-construction path for token-backed repository adapters. It performs no request and creates no authorization.
- `request.request_json(...)` is the canonical bounded PyGithub request-execution path for commodity REST mechanics: requester invocation, standard GitHub headers, bounded low-level retry selection, response-header normalization, and provider/transport failure normalization. Callers choose retry policy explicitly.
- Domain packages retain authorization, currentness, acceptance, lifecycle, mutation admission, pagination interpretation, and domain-specific outcome policy. They consume raw request evidence from `request_json(...)` rather than rebuilding requester plumbing or moving policy into this package.
- The #2507 migration rule is delete-after-migration: once a caller family is proven to preserve its domain semantics through `request_json(...)`, its private `requestJsonAndCheck(...)` plumbing and duplicate header/error normalization should be removed rather than retained as a compatibility fallback.
- Current migrated read callers include execution-service `HostGitHubReadTransport` and scanner-proof `FixedInstallationSnapshotReader`; both retain their existing domain-specific outcome/scope/pagination interpretation while sharing the commodity request boundary.
- PyGithub is isolated to authentication and HTTP transport.
- GitHub REST `Link` headers remain the issue-page pagination authority.
- Provider-owned issue-page retries remain bounded to three total attempts per page.
- Composite issue revisions are deterministic `github-issue-v1:<sha256>` values.
- Scanner validation, duplicate detection, ordering, and report projection remain in `scripts/agent_os_issue_acceptance`.
- No GitHub App credentials are stored or loaded by scanner-domain modules.
- Neither client construction nor bounded request execution creates mutation authority; mutation policy and required post-mutation readback remain with each existing domain owner.

## Dependency and license

The repository uses its approved PyGithub dependency as an unmodified client library. Dependency/version policy remains owned by the repository dependency manifests; this package does not add another HTTP client.

## Runtime configuration

Scanner-proof production authentication continues to use a selected-repository GitHub App installation with `Issues: read` and `Metadata: read` only. Token-backed adapters consume the already-provisioned `GITHUB_TOKEN` / `GH_TOKEN` convention through `build_token_client(...)`; possession of a token never creates Agent OS write authority.

Offline tests use injected/scripted transports and require no GitHub credentials or network access.
