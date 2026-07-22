# Agent OS GitHub Issue Provider

This package supplies read-only GitHub issue pages to the existing Agent OS issue scanner.

## Boundaries

- PyGithub is isolated to authentication and HTTP transport.
- GitHub REST `Link` headers are the pagination authority.
- Provider-owned retries are bounded to three total attempts per page.
- Composite issue revisions are deterministic `github-issue-v1:<sha256>` values.
- Scanner validation, duplicate detection, ordering, and report projection remain in `scripts/agent_os_issue_acceptance`.
- No GitHub App credentials are stored or loaded by scanner-domain modules.
- No mutation method is exposed by the provider interface.

## Dependency and license

The provider uses `PyGithub==2.9.1`, distributed under LGPL-3.0-or-later. PyGithub is consumed as an unmodified Python dependency. Its installed package metadata includes the applicable license information. Redistribution or modification beyond normal dependency installation requires a separate legal review.

## Runtime configuration

Production authentication must use a selected-repository GitHub App installation with `Issues: read` and `Metadata: read` only. Provisioning, secret storage, and live execution are governed separately by issue #531.

Offline tests use `ScriptedGitHubRestTransport` and require no GitHub credentials or network access.
