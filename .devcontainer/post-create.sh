#!/usr/bin/env bash
# Deterministic, fail-closed bootstrap for the agent-os-codespaces-v1 profile.
# Runs once as the devcontainer postCreateCommand. No retries, no fallback
# runtime substitution: a failing step stops the script and leaves the
# Codespace running for inspection (Codespaces do not tear down on a failed
# postCreateCommand).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "AGENT OS CODESPACES BOOTSTRAP START"
start_epoch=$(date +%s)

echo "Verifying repository identity before installing anything..."
python3 scripts/agent-os-environment-health.py --check repository-identity

# Dependency installation may contact configured package indexes. This is a
# bounded bootstrap operation, not OS-level egress enforcement. The
# AGENT_OS_NETWORK_MODE=local-only value controls Agent OS application behavior;
# network availability does not grant GitHub or external-system write authority.
echo "Installing declared development and validation dependencies..."
python -m pip install -r requirements-dev.txt
python -m pip install -e "./08_Tooling/instructional-materials-coach[test]"
python -m pip install -e "./08_Tooling/notion-navigation-client[test]"
python -m pip install -e "./08_Tooling/reusable-capability-registry[test]"
# Execution-service runtime (#3333 Gate 4). Its workflow-scheduler,
# agent-memory-context-manager and instructional-workflow-contracts requirements
# are already satisfied by the editable installs in requirements-dev.txt, which
# must run first because none of them is on a package index. This installs the
# package only; it binds no AGENT_OS_* host path and does not qualify a host.
python -m pip install -e "./08_Tooling/agent-os-execution-service"

end_epoch=$(date +%s)
echo "Dependency install duration: $((end_epoch - start_epoch))s"

# Approved Codespaces checkpoint-store root (#3333). Idempotent; the existing
# #1218 stores create their other subdirectories on demand. Matches
# devcontainer.json containerEnv and the discovery program's explicit binding.
CHECKPOINT_STORE_ROOT="/workspaces/agent-os-state/checkpoints"
mkdir -p -m 0700 "$CHECKPOINT_STORE_ROOT/invocations"
chmod 0700 "$CHECKPOINT_STORE_ROOT" "$CHECKPOINT_STORE_ROOT/invocations"

echo "Running bounded environment health check..."
health_status=0
python3 scripts/agent-os-environment-health.py || health_status=$?

echo "AGENT OS CODESPACES BOOTSTRAP END (health_exit=$health_status)"
exit "$health_status"
