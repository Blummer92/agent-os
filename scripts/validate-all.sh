#!/usr/bin/env bash
# Aggregate local validation runner for Agent OS.
# Run from the repository root: ./scripts/validate-all.sh

set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR" || exit 2

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  if command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
  else
    echo "Runner error: python3 or python is required." >&2
    exit 2
  fi
fi

if ! "$PYTHON_BIN" -m pytest --version >/dev/null 2>&1; then
  echo "Runner error: pytest is required. Install development test dependencies before running validation." >&2
  exit 2
fi

STRUCTURAL_SCRIPT="07_Agent_Tests/validate-repo-structure.sh"
if [ ! -f "$STRUCTURAL_SCRIPT" ]; then
  echo "Runner error: missing structural validation script: $STRUCTURAL_SCRIPT" >&2
  exit 2
fi

commands_executed=()
check_results=()
failed_packages=()
overall_status="PASS"
exit_code=0

record_failure() {
  local name="$1"
  local command_text="$2"
  local code="$3"
  failed_packages+=("$name|$command_text|$code")
  overall_status="FAIL"
  exit_code=1
}

run_check() {
  local name="$1"
  local workdir="$2"
  local command_text="$3"
  shift 3

  commands_executed+=("$command_text")

  echo
  echo "==> $name"
  echo "    $command_text"

  (cd "$workdir" && "$@")
  local code=$?

  if [ "$code" -eq 0 ]; then
    check_results+=("PASS|$name|$command_text|$code")
  else
    check_results+=("FAIL|$name|$command_text|$code")
    record_failure "$name" "$command_text" "$code"
  fi
}

is_python_pytest_suite() {
  local tests_dir="$1"
  find "$tests_dir" -type f \( -name 'test_*.py' -o -name '*_test.py' \) 2>/dev/null | grep -q .
}

run_pytest_suite() {
  local suite_dir="$1"
  local suite_name="$2"

  if [ -d "$suite_dir/src" ]; then
    local display="cd $suite_dir && PYTHONPATH=src $PYTHON_BIN -m pytest tests"
    commands_executed+=("$display")

    echo
    echo "==> $suite_name"
    echo "    $display"

    (cd "$suite_dir" && PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON_BIN" -m pytest tests)
    local code=$?

    if [ "$code" -eq 0 ]; then
      check_results+=("PASS|$suite_name|$display|$code")
    else
      check_results+=("FAIL|$suite_name|$display|$code")
      record_failure "$suite_name" "$display" "$code"
    fi
  else
    run_check "$suite_name" "$suite_dir" "cd $suite_dir && $PYTHON_BIN -m pytest tests" "$PYTHON_BIN" -m pytest tests
  fi
}

mapfile -t test_dirs < <(
  find . -type d -name tests \
    -not -path './.git/*' \
    -not -path './.venv/*' \
    -not -path './venv/*' \
    -not -path './node_modules/*' \
    -not -path './03_Templates/*' \
    | sort | while IFS= read -r test_dir; do
        if is_python_pytest_suite "$test_dir"; then
          printf '%s\n' "$test_dir"
        fi
      done
)

if [ "${#test_dirs[@]}" -eq 0 ]; then
  echo "Runner error: no pytest test directories discovered." >&2
  exit 2
fi

echo "AGGREGATE VALIDATION START"
echo "Repository: $ROOT_DIR"
echo "Python: $PYTHON_BIN"

run_check "structural validation" "$ROOT_DIR" "bash $STRUCTURAL_SCRIPT" bash "$STRUCTURAL_SCRIPT"

for test_dir in "${test_dirs[@]}"; do
  suite_dir="$(dirname "$test_dir")"
  if [ "$suite_dir" = "." ]; then
    suite_name="root"
    suite_dir="$ROOT_DIR"
  else
    suite_name="${suite_dir#./}"
  fi

  run_pytest_suite "$suite_dir" "$suite_name"
done

echo
echo "COMMANDS EXECUTED"
for command_text in "${commands_executed[@]}"; do
  echo "- $command_text"
done

echo
echo "CHECK RESULTS"
for result in "${check_results[@]}"; do
  IFS='|' read -r status name command_text code <<< "$result"
  echo "- $status | $name | exit $code | $command_text"
done

echo
echo "FAILED PACKAGES"
if [ "${#failed_packages[@]}" -eq 0 ]; then
  echo "- none"
else
  for failure in "${failed_packages[@]}"; do
    IFS='|' read -r name command_text code <<< "$failure"
    echo "- $name | exit $code | $command_text"
  done
fi

echo
echo "OVERALL STATUS"
echo "$overall_status"

echo
echo "EXIT CODE"
echo "$exit_code"

exit "$exit_code"
