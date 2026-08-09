"""Bounded PyGithub transport for the Git database endpoints used by GHC1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

import requests.exceptions
try:
    from github import Github
    from github.GithubException import GithubException, RateLimitExceededException
except ModuleNotFoundError:  # dependency is optional at import time for offline tests
    Github = Any  # type: ignore[misc,assignment]

    class GithubException(Exception):
        def __init__(self, status: int | None = None, data: object = None, headers: object = None) -> None:
            super().__init__(str(data))
            self.status = status

    class RateLimitExceededException(GithubException):
        pass

from .models import (
    GitBlobSnapshot,
    GitChangedFile,
    GitCommitSnapshot,
    GitCompareSnapshot,
    GitRefSnapshot,
    GitTreeEntry,
    GitTreeSnapshot,
    MutationState,
    require_branch,
    require_repository,
    require_sha40,
)

_API_VERSION = "2026-03-10"
_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": _API_VERSION,
}


class GitObjectTransportError(RuntimeError):
    def __init__(
        self,
        operation: str,
        kind: str,
        *,
        mutation_state: MutationState = MutationState.NOT_ATTEMPTED,
    ) -> None:
        super().__init__(f"{operation}:{kind}")
        self.operation = operation
        self.kind = kind
        self.mutation_state = mutation_state


class GitHubGitObjectTransport(Protocol):
    def get_ref(self, repository: str, branch: str) -> GitRefSnapshot: ...
    def get_commit(self, repository: str, commit_sha: str) -> GitCommitSnapshot: ...
    def get_tree(
        self, repository: str, tree_sha: str, *, recursive: bool = False
    ) -> GitTreeSnapshot: ...
    def get_blob(self, repository: str, blob_sha: str) -> GitBlobSnapshot: ...
    def create_tree(
        self,
        repository: str,
        *,
        base_tree_sha: str,
        entries: tuple[GitTreeEntry, ...],
    ) -> str: ...
    def create_commit(
        self,
        repository: str,
        *,
        tree_sha: str,
        parent_sha: str,
        message: str,
    ) -> str: ...
    def compare(
        self, repository: str, *, base_sha: str, head_sha: str
    ) -> GitCompareSnapshot: ...
    def update_ref(
        self,
        repository: str,
        *,
        branch: str,
        commit_sha: str,
        force: bool = False,
    ) -> GitRefSnapshot: ...


@dataclass(slots=True)
class PyGithubGitObjectTransport:
    client: Github
    max_read_attempts: int = 3

    def __post_init__(self) -> None:
        if not 1 <= self.max_read_attempts <= 3:
            raise ValueError("max_read_attempts must be from 1 to 3")

    def get_ref(self, repository: str, branch: str) -> GitRefSnapshot:
        repository = require_repository(repository)
        branch = require_branch(branch, allow_protected=True)
        payload = self._read(
            "get-ref", f"/repos/{repository}/git/ref/heads/{quote(branch, safe='')}"
        )
        obj = _mapping(payload, "ref response")
        _require_exact_ref(obj.get("ref"), branch, "get-ref")
        target = _mapping(obj.get("object"), "ref object")
        return GitRefSnapshot(repository, branch, _text(target.get("sha"), "ref sha"))

    def get_commit(self, repository: str, commit_sha: str) -> GitCommitSnapshot:
        repository = require_repository(repository)
        commit_sha = require_sha40(commit_sha, "commit_sha")
        payload = self._read("get-commit", f"/repos/{repository}/git/commits/{commit_sha}")
        obj = _mapping(payload, "commit response")
        tree = _mapping(obj.get("tree"), "commit tree")
        parents = _list(obj.get("parents"), "commit parents")
        return GitCommitSnapshot(
            _text(obj.get("sha"), "commit sha"),
            _text(tree.get("sha"), "tree sha"),
            tuple(_text(_mapping(parent, "parent").get("sha"), "parent sha") for parent in parents),
        )

    def get_tree(
        self, repository: str, tree_sha: str, *, recursive: bool = False
    ) -> GitTreeSnapshot:
        repository = require_repository(repository)
        tree_sha = require_sha40(tree_sha, "tree_sha")
        payload = self._read(
            "get-tree",
            f"/repos/{repository}/git/trees/{tree_sha}",
            parameters={"recursive": "1"} if recursive else None,
        )
        obj = _mapping(payload, "tree response")
        raw_entries = _list(obj.get("tree"), "tree entries")
        entries: list[GitTreeEntry] = []
        for raw in raw_entries:
            item = _mapping(raw, "tree entry")
            if item.get("type") != "blob" or item.get("mode") != "100644":
                continue
            entries.append(
                GitTreeEntry(
                    path=_text(item.get("path"), "entry path"),
                    mode="100644",
                    type="blob",
                    sha=_text(item.get("sha"), "entry sha"),
                )
            )
        truncated = obj.get("truncated", False)
        if type(truncated) is not bool:
            raise GitObjectTransportError("get-tree", "malformed-response")
        returned_sha = _text(obj.get("sha"), "tree sha")
        if returned_sha != tree_sha:
            raise GitObjectTransportError("get-tree", "malformed-response")
        return GitTreeSnapshot(returned_sha, tuple(entries), truncated)

    def get_blob(self, repository: str, blob_sha: str) -> GitBlobSnapshot:
        repository = require_repository(repository)
        blob_sha = require_sha40(blob_sha, "blob_sha")
        payload = self._read("get-blob", f"/repos/{repository}/git/blobs/{blob_sha}")
        obj = _mapping(payload, "blob response")
        size = obj.get("size")
        if type(size) is not int or size < 0:
            raise GitObjectTransportError("get-blob", "malformed-response")
        encoding = obj.get("encoding", "none")
        if not isinstance(encoding, str):
            raise GitObjectTransportError("get-blob", "malformed-response")
        content = obj.get("content")
        if content is not None and not isinstance(content, str):
            raise GitObjectTransportError("get-blob", "malformed-response")
        return GitBlobSnapshot(
            _text(obj.get("sha"), "blob sha"), size, encoding, content
        )

    def create_tree(
        self,
        repository: str,
        *,
        base_tree_sha: str,
        entries: tuple[GitTreeEntry, ...],
    ) -> str:
        repository = require_repository(repository)
        base_tree_sha = require_sha40(base_tree_sha, "base_tree_sha")
        if not entries:
            raise ValueError("entries must not be empty")
        payload = self._write(
            "create-tree",
            "POST",
            f"/repos/{repository}/git/trees",
            {
                "base_tree": base_tree_sha,
                "tree": [
                    {"path": entry.path, "mode": entry.mode, "type": entry.type, "sha": entry.sha}
                    for entry in entries
                ],
            },
        )
        try:
            return require_sha40(
                _text(_mapping(payload, "tree response").get("sha"), "tree sha"),
                "tree_sha",
            )
        except Exception as error:
            raise GitObjectTransportError(
                "create-tree",
                "malformed-success-response",
                mutation_state=MutationState.UNCERTAIN,
            ) from error

    def create_commit(
        self,
        repository: str,
        *,
        tree_sha: str,
        parent_sha: str,
        message: str,
    ) -> str:
        repository = require_repository(repository)
        tree_sha = require_sha40(tree_sha, "tree_sha")
        parent_sha = require_sha40(parent_sha, "parent_sha")
        payload = self._write(
            "create-commit",
            "POST",
            f"/repos/{repository}/git/commits",
            {"message": message, "tree": tree_sha, "parents": [parent_sha]},
        )
        try:
            return require_sha40(
                _text(_mapping(payload, "commit response").get("sha"), "commit sha"),
                "commit_sha",
            )
        except Exception as error:
            raise GitObjectTransportError(
                "create-commit",
                "malformed-success-response",
                mutation_state=MutationState.UNCERTAIN,
            ) from error

    def compare(
        self, repository: str, *, base_sha: str, head_sha: str
    ) -> GitCompareSnapshot:
        repository = require_repository(repository)
        base_sha = require_sha40(base_sha, "base_sha")
        head_sha = require_sha40(head_sha, "head_sha")
        payload = self._read(
            "compare", f"/repos/{repository}/compare/{base_sha}...{head_sha}"
        )
        obj = _mapping(payload, "compare response")
        files = _list(obj.get("files"), "compare files")
        changed: list[GitChangedFile] = []
        additions = 0
        deletions = 0
        for raw in files:
            item = _mapping(raw, "compare file")
            file_additions = item.get("additions")
            file_deletions = item.get("deletions")
            if type(file_additions) is not int or type(file_deletions) is not int:
                raise GitObjectTransportError("compare", "malformed-response")
            additions += file_additions
            deletions += file_deletions
            changed.append(
                GitChangedFile(
                    path=_text(item.get("filename"), "filename"),
                    status=_text(item.get("status"), "status"),
                    blob_sha=_text(item.get("sha"), "file sha"),
                    previous_path=item.get("previous_filename"),
                )
            )
        return GitCompareSnapshot(
            status=_text(obj.get("status"), "status"),
            ahead_by=_integer(obj.get("ahead_by"), "ahead_by"),
            behind_by=_integer(obj.get("behind_by"), "behind_by"),
            total_commits=_integer(obj.get("total_commits"), "total_commits"),
            changed_files=tuple(changed),
            additions=additions,
            deletions=deletions,
        )

    def update_ref(
        self,
        repository: str,
        *,
        branch: str,
        commit_sha: str,
        force: bool = False,
    ) -> GitRefSnapshot:
        repository = require_repository(repository)
        branch = require_branch(branch)
        commit_sha = require_sha40(commit_sha, "commit_sha")
        if force is not False:
            raise ValueError("force ref updates are not supported")
        payload = self._write(
            "update-ref",
            "PATCH",
            f"/repos/{repository}/git/refs/heads/{quote(branch, safe='')}",
            {"sha": commit_sha, "force": False},
        )
        try:
            obj = _mapping(payload, "ref response")
            _require_exact_ref(obj.get("ref"), branch, "update-ref")
            target = _mapping(obj.get("object"), "ref object")
            return GitRefSnapshot(
                repository, branch, _text(target.get("sha"), "ref sha")
            )
        except Exception as error:
            raise GitObjectTransportError(
                "update-ref",
                "malformed-success-response",
                mutation_state=MutationState.UNCERTAIN,
            ) from error

    def _read(
        self, operation: str, url: str, *, parameters: dict[str, str] | None = None
    ) -> Any:
        for attempt in range(1, self.max_read_attempts + 1):
            try:
                _headers, payload = self.client.requester.requestJsonAndCheck(
                    "GET", url, parameters=parameters, headers=_HEADERS
                )
                return payload
            except RateLimitExceededException as error:
                raise GitObjectTransportError(operation, "rate-limited") from error
            except GithubException as error:
                if error.status is not None and 500 <= error.status < 600 and attempt < self.max_read_attempts:
                    continue
                raise GitObjectTransportError(operation, _github_error_kind(error.status)) from error
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, TimeoutError, ConnectionError) as error:
                if attempt < self.max_read_attempts:
                    continue
                raise GitObjectTransportError(operation, "transport-unavailable") from error
            except GitObjectTransportError:
                raise
            except Exception as error:
                raise GitObjectTransportError(operation, "internal-error") from error
        raise GitObjectTransportError(operation, "transport-unavailable")

    def _write(self, operation: str, method: str, url: str, payload: dict[str, Any]) -> Any:
        try:
            _headers, response = self.client.requester.requestJsonAndCheck(
                method, url, input=payload, headers=_HEADERS
            )
            return response
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, TimeoutError, ConnectionError) as error:
            raise GitObjectTransportError(
                operation, "mutation-uncertain", mutation_state=MutationState.UNCERTAIN
            ) from error
        except GithubException as error:
            state = MutationState.UNCERTAIN if error.status is None or error.status >= 500 else MutationState.FAILED_BEFORE_SIDE_EFFECT
            raise GitObjectTransportError(
                operation, _github_error_kind(error.status), mutation_state=state
            ) from error
        except Exception as error:
            raise GitObjectTransportError(
                operation, "mutation-uncertain", mutation_state=MutationState.UNCERTAIN
            ) from error


def _require_exact_ref(value: Any, branch: str, operation: str) -> None:
    """Require the response to name exactly the branch ref that was requested.

    A missing, prefix-matched, or otherwise different ``ref`` is a malformed
    response, not a usable answer about another branch.
    """
    if not isinstance(value, str) or value != f"refs/heads/{branch}":
        raise GitObjectTransportError(operation, "malformed-response")


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GitObjectTransportError(name, "malformed-response")
    return value


def _list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise GitObjectTransportError(name, "malformed-response")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise GitObjectTransportError(name, "malformed-response")
    return value


def _integer(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise GitObjectTransportError(name, "malformed-response")
    return value


def _github_error_kind(status: int | None) -> str:
    if status in {401, 403}:
        return "permission-denied"
    if status == 404:
        return "not-found"
    if status == 409:
        return "conflict"
    if status == 422:
        return "invalid-request"
    if status == 429:
        return "rate-limited"
    if status is not None and 400 <= status < 500:
        return "api-rejected"
    return "transport-unavailable"
