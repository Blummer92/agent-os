"""Fixed host-side credential bridge for the bounded #531 scanner proof.

This repository module does not mutate or prove IAM, Secret Manager, GitHub
App installation, or host configuration. It consumes one fixed root-owned host
credential-provider entrypoint, validates the exact read-only GitHub App
installation boundary observed in the same invocation, and delegates the
one-page read to the existing :mod:`scanner_proof` composition.

The validator principal and Secret Manager resource below are expected-currentness
identities for the separately governed host/runtime prerequisite. This module does
not claim that executing the helper proves those external bindings.
"""
from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from dataclasses import asdict
from typing import Callable, Mapping, Sequence

from .auth import GitHubAppSecretProvider
from .pagination import PaginationDiagnosticError, parse_link_header
from .request import GitHubRequestError, request_json
from .scanner_proof import (
    APP_ID,
    INSTALLATION_ID,
    REPOSITORY,
    ScannerProofEvidence,
    run_scanner_proof,
)

VALIDATOR_PRINCIPAL = "agent-os-github-app-validator@agent-os-502614.iam.gserviceaccount.com"
SECRET_RESOURCE = "projects/agent-os-502614/secrets/agent-os-github-app-private-key"
SECRET_PROVIDER_ENTRYPOINT = "/usr/local/libexec/agent-os-github-app-secret-provider"
INSTALLATION_REPOSITORY_PAGE_SIZE = 2
EXPECTED_PERMISSIONS = {"issues": "read", "metadata": "read"}

_PRIVATE_KEY_RE = re.compile(
    r"\A-----BEGIN (?:RSA )?PRIVATE KEY-----\r?\n"
    r"[A-Za-z0-9+/=\r\n]{128,16384}"
    r"-----END (?:RSA )?PRIVATE KEY-----\r?\n?\Z",
    re.ASCII,
)


class ScannerProofHostBridgeError(RuntimeError):
    """Fail-closed host bridge error carrying one bounded reason code."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _safe_provider_env() -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }


class FixedHostGitHubAppSecretProvider:
    """Consume one fixed root-owned helper.

    Repository code verifies only the helper path/ownership/mode and returned key
    shape. IAM principal and Secret Manager source currentness must be proven
    separately before any live scanner invocation.
    """

    def __init__(
        self,
        *,
        run_command: Callable[..., object] = subprocess.run,
        lstat: Callable[[str], os.stat_result] = os.lstat,
    ) -> None:
        self._run_command = run_command
        self._lstat = lstat

    def _validate_entrypoint(self) -> None:
        try:
            metadata = self._lstat(SECRET_PROVIDER_ENTRYPOINT)
        except OSError as error:
            raise ScannerProofHostBridgeError(
                "scanner-proof-secret-provider-unavailable"
            ) from error
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or metadata.st_mode & 0o022
            or not metadata.st_mode & stat.S_IXUSR
        ):
            raise ScannerProofHostBridgeError(
                "scanner-proof-secret-provider-unavailable"
            )

    def private_key(self) -> str:
        self._validate_entrypoint()
        try:
            completed = self._run_command(
                (SECRET_PROVIDER_ENTRYPOINT,),
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
                stdin=subprocess.DEVNULL,
                env=_safe_provider_env(),
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ScannerProofHostBridgeError(
                "scanner-proof-secret-provider-unavailable"
            ) from error
        if getattr(completed, "returncode", None) != 0:
            raise ScannerProofHostBridgeError(
                "scanner-proof-secret-provider-unavailable"
            )
        private_key = getattr(completed, "stdout", None)
        if not isinstance(private_key, str) or _PRIVATE_KEY_RE.fullmatch(private_key) is None:
            raise ScannerProofHostBridgeError("scanner-proof-secret-provider-invalid")
        return private_key


class FixedInstallationSnapshotReader:
    """Verify fixed App/install permissions and singleton repository scope."""

    @staticmethod
    def _request(
        client: object, path: str, parameters: Mapping[str, object]
    ) -> tuple[Mapping[str, str], object]:
        try:
            result = request_json(
                client,
                "GET",
                path,
                parameters=parameters,
                max_attempts=1,
            )
        except (GitHubRequestError, TypeError, ValueError) as error:
            raise ScannerProofHostBridgeError("scanner-proof-github-read-failed") from error
        return result.headers, result.payload

    @staticmethod
    def _link_header(headers: Mapping[str, object]) -> str | None:
        for key, value in headers.items():
            if str(key).lower() == "link":
                if not isinstance(value, str):
                    raise ScannerProofHostBridgeError(
                        "scanner-proof-installation-pagination-unproven"
                    )
                return value
        return None

    def read(self, client: object) -> tuple[Mapping[str, object], bool, bool, int]:
        _, installation = self._request(client, "/installation", {})
        if not isinstance(installation, Mapping):
            raise ScannerProofHostBridgeError("scanner-proof-installation-metadata-invalid")
        if installation.get("app_id") != APP_ID:
            raise ScannerProofHostBridgeError("scanner-proof-app-mismatch")
        if installation.get("id") != INSTALLATION_ID:
            raise ScannerProofHostBridgeError("scanner-proof-installation-mismatch")
        if installation.get("repository_selection") != "selected":
            raise ScannerProofHostBridgeError("scanner-proof-repository-scope-mismatch")
        permissions = installation.get("permissions")
        if not isinstance(permissions, Mapping) or dict(permissions) != EXPECTED_PERMISSIONS:
            raise ScannerProofHostBridgeError("scanner-proof-permission-drift")

        headers, payload = self._request(
            client,
            "/installation/repositories",
            {"page": 1, "per_page": INSTALLATION_REPOSITORY_PAGE_SIZE},
        )
        if not isinstance(payload, Mapping):
            raise ScannerProofHostBridgeError("scanner-proof-installation-metadata-invalid")
        total_count = payload.get("total_count")
        repositories = payload.get("repositories")
        if (
            total_count != 1
            or not isinstance(repositories, Sequence)
            or isinstance(repositories, (str, bytes))
            or len(repositories) != 1
            or not isinstance(repositories[0], Mapping)
        ):
            raise ScannerProofHostBridgeError("scanner-proof-repository-scope-mismatch")
        selected = repositories[0]
        full_name = selected.get("full_name")
        if not isinstance(full_name, str) or full_name.lower() != REPOSITORY.lower():
            raise ScannerProofHostBridgeError("scanner-proof-repository-scope-mismatch")
        try:
            relations = parse_link_header(self._link_header(headers))
        except (PaginationDiagnosticError, TypeError) as error:
            raise ScannerProofHostBridgeError(
                "scanner-proof-installation-pagination-unproven"
            ) from error
        if "next" in relations:
            raise ScannerProofHostBridgeError(
                "scanner-proof-installation-pagination-unproven"
            )
        snapshot = {
            "repository_selection": "selected",
            "repositories": [dict(selected)],
        }
        return snapshot, True, True, INSTALLATION_ID


def run_host_scanner_proof(
    *,
    secrets: GitHubAppSecretProvider | None = None,
    installation_snapshot_reader: object | None = None,
) -> ScannerProofEvidence:
    """Run only the existing scanner proof with fixed host-side adapters."""
    return run_scanner_proof(
        secrets=secrets or FixedHostGitHubAppSecretProvider(),
        installation_snapshot_reader=(
            installation_snapshot_reader or FixedInstallationSnapshotReader()
        ),
    )


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    result = (
        ScannerProofEvidence(status="blocked", reason="scanner-proof-host-argv-invalid")
        if args
        else run_host_scanner_proof()
    )
    print(json.dumps(asdict(result), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
