"""Finite GitHub ruleset administration adapter for GH-ADMIN1 (#1893).

This is intentionally not a generic GitHub administration client.  It exposes
one operation for one repository/ruleset/consumer combination and reuses the
repository's existing GITHUB_TOKEN/GH_TOKEN credential convention.  Possessing
that credential does not grant protected-setting authorization; the caller must
still supply the separately-authorized #1883 request identity.

The live mutation shape is fixed: one GET of Protect main, at most one PUT that
preserves the observed ruleset and appends the canonical aggregate-validation
required-status-check rule, then one immediate GET read-back.  There is no
caller-supplied URL, HTTP method, arbitrary rule payload, retry, or fallback.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Optional

from workflow_scheduler.adapters.base_adapter import TaskAdapter
from workflow_scheduler.models import Task

GITHUB_API_BASE = "https://api.github.com"
REPOSITORY = "Blummer92/agent-os"
RULESET_ID = 19123362
RULESET_NAME = "Protect main"
AUTHORIZATION_ISSUE = 1883
REQUIRED_CONTEXT = "Run aggregate validation"
REQUIRED_INTEGRATION_ID = 15368
_API_VERSION = "2026-03-10"


class GitHubRulesetAdminAdapterError(RuntimeError):
    """Controlled terminal failure; mutation failures are never retryable."""


JsonGet = Callable[[str, Dict[str, str], float], Any]
JsonPut = Callable[[str, Dict[str, str], Dict[str, Any], float], Any]


def _request_json(method: str, url: str, headers: Dict[str, str], body: Dict[str, Any] | None, timeout: float) -> Any:
    data = None if body is None else json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise GitHubRulesetAdminAdapterError(f"GitHub API returned HTTP {exc.code}: {exc.reason}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise GitHubRulesetAdminAdapterError(f"GitHub API transport failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise GitHubRulesetAdminAdapterError("GitHub API returned invalid JSON") from exc


def _default_get(url: str, headers: Dict[str, str], timeout: float) -> Any:
    return _request_json("GET", url, headers, None, timeout)


def _default_put(url: str, headers: Dict[str, str], body: Dict[str, Any], timeout: float) -> Any:
    return _request_json("PUT", url, headers, body, timeout)


def mutation_prestate_sha256(payload: object) -> str:
    """Digest only fields the mutation must preserve/currentness-bind."""
    if not isinstance(payload, dict):
        raise GitHubRulesetAdminAdapterError("ruleset response must be an object")
    material = {
        "id": payload.get("id"),
        "name": payload.get("name"),
        "target": payload.get("target"),
        "enforcement": payload.get("enforcement"),
        "conditions": payload.get("conditions"),
        "rules": payload.get("rules"),
        "bypass_actors": payload.get("bypass_actors"),
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def required_status_rule() -> Dict[str, Any]:
    return {
        "type": "required_status_checks",
        "parameters": {
            "required_status_checks": [
                {"context": REQUIRED_CONTEXT, "integration_id": REQUIRED_INTEGRATION_ID}
            ],
            "strict_required_status_checks_policy": True,
            "do_not_enforce_on_create": False,
        },
    }


class GitHubRulesetAdminAdapter(TaskAdapter):
    """One finite action: apply #1883's exact required-check rule."""

    def __init__(
        self,
        token: Optional[str] = None,
        http_get: Optional[JsonGet] = None,
        http_put: Optional[JsonPut] = None,
        timeout: float = 10.0,
    ) -> None:
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise TypeError("timeout must be a finite positive number")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a finite positive number")
        self.token = token if token is not None else (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"))
        self._http_get = http_get or _default_get
        self._http_put = http_put or _default_put
        self.timeout = timeout

    def execute(self, task: Task) -> Dict[str, Any]:
        try:
            return self._apply(task.payload or {})
        except GitHubRulesetAdminAdapterError as exc:
            return {"status": "failure", "message": str(exc)}

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": _API_VERSION,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    @staticmethod
    def _require_exact(payload: Dict[str, Any], field: str, expected: object) -> None:
        if payload.get(field) != expected:
            raise GitHubRulesetAdminAdapterError(f"{field} must equal the fixed authorized value")

    def _validate_request(self, payload: Dict[str, Any]) -> str:
        self._require_exact(payload, "action", "apply_1883_required_validation_gate")
        self._require_exact(payload, "repository_full_name", REPOSITORY)
        self._require_exact(payload, "ruleset_id", RULESET_ID)
        self._require_exact(payload, "authorization_issue", AUTHORIZATION_ISSUE)
        expected = payload.get("expected_prestate_sha256")
        if type(expected) is not str or len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
            raise GitHubRulesetAdminAdapterError("expected_prestate_sha256 must be 64 lowercase hex characters")
        extra = set(payload) - {
            "action", "repository_full_name", "ruleset_id", "authorization_issue", "expected_prestate_sha256"
        }
        if extra:
            raise GitHubRulesetAdminAdapterError(f"unsupported request fields: {sorted(extra)}")
        return expected

    @staticmethod
    def _validate_prestate(current: Any) -> Dict[str, Any]:
        if not isinstance(current, dict):
            raise GitHubRulesetAdminAdapterError("ruleset response must be an object")
        fixed = {
            "id": RULESET_ID,
            "name": RULESET_NAME,
            "target": "branch",
            "source_type": "Repository",
            "source": REPOSITORY,
            "enforcement": "active",
        }
        for key, expected in fixed.items():
            if current.get(key) != expected:
                raise GitHubRulesetAdminAdapterError(f"ruleset {key} does not match the fixed target")
        conditions = current.get("conditions")
        rules = current.get("rules")
        bypass = current.get("bypass_actors")
        if not isinstance(conditions, dict) or not isinstance(rules, list) or not isinstance(bypass, list):
            raise GitHubRulesetAdminAdapterError("ruleset preservation fields are malformed")
        required = [rule for rule in rules if isinstance(rule, dict) and rule.get("type") == "required_status_checks"]
        if required:
            if len(required) == 1 and required[0] == required_status_rule():
                return current
            raise GitHubRulesetAdminAdapterError("ruleset already has a conflicting required_status_checks rule")
        return current

    @staticmethod
    def _put_body(current: Dict[str, Any]) -> Dict[str, Any]:
        rules = list(current["rules"])
        rules.append(required_status_rule())
        return {
            "name": current["name"],
            "target": current["target"],
            "enforcement": current["enforcement"],
            "bypass_actors": current["bypass_actors"],
            "conditions": current["conditions"],
            "rules": rules,
        }

    @staticmethod
    def _verify_readback(before: Dict[str, Any], after: Any) -> Dict[str, Any]:
        if not isinstance(after, dict):
            raise GitHubRulesetAdminAdapterError("ruleset read-back must be an object")
        for field in ("id", "name", "target", "source_type", "source", "enforcement", "conditions", "bypass_actors"):
            if after.get(field) != before.get(field):
                raise GitHubRulesetAdminAdapterError(f"ruleset read-back changed preserved field: {field}")
        expected_rules = list(before["rules"])
        if not any(isinstance(rule, dict) and rule.get("type") == "required_status_checks" for rule in expected_rules):
            expected_rules.append(required_status_rule())
        if after.get("rules") != expected_rules:
            raise GitHubRulesetAdminAdapterError("ruleset read-back did not converge to the exact authorized rules")
        return after

    def _apply(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        expected_digest = self._validate_request(payload)
        url = f"{GITHUB_API_BASE}/repos/{REPOSITORY}/rulesets/{RULESET_ID}"
        headers = self._headers()
        current = self._validate_prestate(self._http_get(url, headers, self.timeout))
        observed_digest = mutation_prestate_sha256(current)
        if observed_digest != expected_digest:
            raise GitHubRulesetAdminAdapterError("ruleset pre-state moved; mutation refused")

        already_converged = any(
            isinstance(rule, dict) and rule.get("type") == "required_status_checks"
            for rule in current["rules"]
        )
        mutation_attempted = False
        if not already_converged:
            mutation_attempted = True
            response = self._http_put(url, headers, self._put_body(current), self.timeout)
            if not isinstance(response, dict):
                raise GitHubRulesetAdminAdapterError("ruleset mutation response must be an object")

        readback = self._verify_readback(current, self._http_get(url, headers, self.timeout))
        return {
            "status": "success",
            "message": "Protect main required validation rule converged",
            "output": {
                "repository": REPOSITORY,
                "ruleset_id": RULESET_ID,
                "authorization_issue": AUTHORIZATION_ISSUE,
                "required_context": REQUIRED_CONTEXT,
                "integration_id": REQUIRED_INTEGRATION_ID,
                "prestate_sha256": observed_digest,
                "mutation_attempted": mutation_attempted,
                "readback_sha256": mutation_prestate_sha256(readback),
                "credential_source": "environment-managed",
                "credential_value_exposed": False,
            },
        }

    ACTIONS = {"apply_1883_required_validation_gate"}
