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

echo "Installing declared development and validation dependencies..."
python -m pip install -r requirements-dev.txt
python -m pip install -e "./08_Tooling/instructional-materials-coach[test]"
python -m pip install -e "./08_Tooling/notion-navigation-client[test]"
python -m pip install -e "./08_Tooling/reusable-capability-registry[test]"

end_epoch=$(date +%s)
echo "Dependency install duration: $((end_epoch - start_epoch))s"

echo "Running bounded environment health check..."
health_status=0
python3 scripts/agent-os-environment-health.py || health_status=$?

echo "AGENT OS CODESPACES BOOTSTRAP END (health_exit=$health_status)"
exit "$health_status"
