#!/usr/bin/env bash
# Run the same aggregate producer and receipt check locally or in Actions.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
origin=local
case "${1:-}" in
  --hosted)
    [ "$#" -eq 1 ] || exit 2
    origin=hosted
    if [ -z "${CI_JUNIT_DIR:-}" ] || [ -z "${CI_COVERAGE_DIR:-}" ]; then
      echo "CI evidence: missing hosted output directory" >&2
      exit 2
    fi
    ;;
  "")
    [ "$#" -eq 0 ] || exit 2
    output="$(mktemp -d "${TMPDIR:-/tmp}/agent-os-ci.XXXXXX")"
    CI_JUNIT_DIR="$output/junit"
    CI_COVERAGE_DIR="$output/coverage"
    CI_JUNIT_HEAD_SHA="$(git rev-parse HEAD)"
    # Local PID/attempt label is not a GitHub run ID.
    CI_JUNIT_RUN_ID="$$"
    CI_JUNIT_RUN_ATTEMPT=1
    ;;
  *) printf '%s\n' 'usage: bash scripts/ci-local.sh [--hosted]' >&2; exit 2 ;;
esac
export CI_JUNIT_DIR CI_COVERAGE_DIR CI_JUNIT_HEAD_SHA CI_JUNIT_RUN_ID CI_JUNIT_RUN_ATTEMPT
export CI_COVERAGE_ORIGIN="$origin"

mkdir -p -- "$CI_JUNIT_DIR" "$CI_COVERAGE_DIR"
black_receipt="$CI_JUNIT_DIR/black-format-receipt.json"
rm -f -- "$black_receipt"
if [ "$origin" = hosted ] && ! {
  [[ "${CI_JUNIT_HEAD_SHA:-}" =~ ^[0-9a-f]{40}$ ]] &&
  [[ "${CI_JUNIT_RUN_ID:-}" =~ ^[1-9][0-9]*$ ]] &&
  [[ "${CI_JUNIT_RUN_ATTEMPT:-}" =~ ^[1-9][0-9]*$ ]] &&
  [ "$(git rev-parse HEAD)" = "$CI_JUNIT_HEAD_SHA" ];
}; then
  echo "CI evidence: invalid hosted head, run ID, or attempt" >&2
  exit 2
fi
find "$CI_COVERAGE_DIR" -maxdepth 1 \( -type f -o -type l \) -name '*.json' -delete
printf 'JUnit evidence: %s\nCoverage evidence: %s\n' "$CI_JUNIT_DIR" "$CI_COVERAGE_DIR"
validation_status=0

clean_checkout() {
  local status
  status="$(git status --porcelain=v1 --untracked-files=normal)" || return 1
  [ -z "$status" ]
}
if ! clean_checkout; then
  echo "CI evidence: checkout is not clean before validation" >&2
  validation_status=2
else
  bash ./scripts/validate-all.sh || validation_status=$?
  if ! clean_checkout; then
    echo "CI evidence: checkout changed during validation" >&2
    # Preserve an earlier failure rather than replacing it.
    if [ "$validation_status" -eq 0 ]; then validation_status=2; fi
  fi
fi

coverage_status=0
"${PYTHON_BIN:-python3}" scripts/agent_os_ci_branch_coverage.py "$CI_COVERAGE_DIR" \
  --validation-exit "$validation_status" || coverage_status=$?
# Black is separate from pytest and coverage: keep both receipts truthful.
black_status=0
if [ "$validation_status" -eq 0 ]; then
  "${PYTHON_BIN:-python3}" -I scripts/agent_os_ci_black.py "$black_receipt" || black_status=$?
  case "$black_status" in
    0|1|2) ;;
    *)
      echo "Black formatting: interrupted or invalid exit" >&2
      rm -f -- "$black_receipt"
      black_status=2
      ;;
  esac
  if [ ! -s "$black_receipt" ]; then
    echo "Black formatting: required receipt missing" >&2
    black_status=2
  elif [ "$black_status" -eq 0 ]; then
    "${PYTHON_BIN:-python3}" -I scripts/agent_os_ci_black.py --verify-clean "$black_receipt" || black_status=2
  fi
fi

final_status="$validation_status"
if [ "$final_status" -eq 0 ]; then final_status="$coverage_status"; fi
if [ "$final_status" -eq 0 ]; then final_status="$black_status"; fi
if [ "$origin" = "local" ]; then
  result=success
  if [ "$final_status" -ne 0 ]; then result=failure; fi
  # The local gate sees the combined validation, coverage, and Black result.
  VALIDATE_RESULT="$result" PLAN_RESULT="" FRONTEND_RESULT="" FRONTEND_REQUIRED=false \
    "${PYTHON_BIN:-python3}" scripts/agent_os_aggregate_gate.py || {
      gate_status=$?
      if [ "$final_status" -eq 0 ]; then final_status="$gate_status"; fi
    }
fi
exit "$final_status"
