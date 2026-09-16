# Agent OS GitHub Issue Provider

This package supplies read-only GitHub issue pages to the existing Agent OS issue scanner and owns the shared PyGithub client-construction boundary used by repository GitHub adapters.

## Boundaries

- `auth.build_installation_client(...)` remains the selected-repository GitHub App client for scanner-proof work.
- `auth.build_token_client(...)` is the single `GITHUB_TOKEN` / `GH_TOKEN` PyGithub client-construction path for token-backed repository adapters. It performs no request and creates no authorization.
- Domain packages retain authorization, currentness, acceptance, lifecycle, and mutation-admission policy; they consume the shared client rather than rebuilding credentials/client configuration.
- PyGithub is isolated to authentication and HTTP transport.
- GitHub REST `Link` headers remain the issue-page pagination authority.
- Provider-owned issue-page retries remain bounded to three total attempts per page.
- Composite issue revisions are deterministic `github-issue-v1:<sha256>` values.
- Scanner validation, duplicate detection, ordering, and report projection remain in `scripts/agent_os_issue_acceptance`.
- No GitHub App credentials are stored or loaded by scanner-domain modules.
- No mutation authority is exposed by the client builder; mutation policy remains with each existing domain owner.

## Dependency and license

The repository uses its approved PyGithub dependency as an unmodified client library. Dependency/version policy remains owned by the repository dependency manifests; this package does not add another HTTP client.

## Runtime configuration

Scanner-proof production authentication continues to use a selected-repository GitHub App installation with `Issues: read` and `Metadata: read` only. Token-backed adapters consume the already-provisioned `GITHUB_TOKEN` / `GH_TOKEN` convention through `build_token_client(...)`; possession of a token never creates Agent OS write authority.

Offline tests use injected/scripted transports and require no GitHub credentials or network access.
