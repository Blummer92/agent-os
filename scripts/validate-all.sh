#!/usr/bin/env bash
# Canonical local validation runner for Agent OS.
# Run from the repository root: ./scripts/validate-all.sh [--focused PATH ...] [--focused-maxfail N]

set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR" || exit 2

runner_error() {
  echo "Runner error: $1" >&2
  exit 2
}

VALIDATE_ALL_MAX_PARALLEL="${VALIDATE_ALL_MAX_PARALLEL:-3}"
case "$VALIDATE_ALL_MAX_PARALLEL" in
  *[!0-9]*|'') runner_error "VALIDATE_ALL_MAX_PARALLEL must be a positive integer." ;;
esac
if [ "$VALIDATE_ALL_MAX_PARALLEL" -lt 1 ] || [ "$VALIDATE_ALL_MAX_PARALLEL" -gt 8 ]; then
  runner_error "VALIDATE_ALL_MAX_PARALLEL must be between 1 and 8."
fi

focused_targets=()
focused_maxfail=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --focused)
      [ "$#" -ge 2 ] || runner_error "--focused requires a path."
      [ -n "$2" ] || runner_error "--focused path cannot be empty."
      focused_targets+=("$2")
      shift 2
      ;;
    --focused-maxfail)
      [ "$#" -ge 2 ] || runner_error "--focused-maxfail requires a positive integer."
      [ -z "$focused_maxfail" ] || runner_error "--focused-maxfail may be supplied only once."
      focused_maxfail="$2"
      shift 2
      ;;
    --*)
      runner_error "unsupported option: $1"
      ;;
    *)
      runner_error "unexpected positional argument: $1"
      ;;
  esac
done

if [ -n "$focused_maxfail" ]; then
  case "$focused_maxfail" in
    *[!0-9]*|'') runner_error "--focused-maxfail must be a positive integer." ;;
  esac
  if [ "${#focused_maxfail}" -gt 3 ]; then
    runner_error "--focused-maxfail must be between 1 and 100."
  fi
  if [ "$focused_maxfail" -lt 1 ] || [ "$focused_maxfail" -gt 100 ]; then
    runner_error "--focused-maxfail must be between 1 and 100."
  fi
  [ "${#focused_targets[@]}" -gt 0 ] || runner_error "--focused-maxfail requires at least one --focused target."
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  if command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
  else
    runner_error "python3 or python is required."
  fi
fi

if ! "$PYTHON_BIN" -m pytest --version >/dev/null 2>&1; then
  runner_error "pytest is required. Install development test dependencies before running validation."
fi

normalize_focused_target() {
  local candidate="$1"

  case "$candidate" in
    /*) return 10 ;;
    -*) return 11 ;;
    *[!A-Za-z0-9._/-]*) return 12 ;;
  esac

  case "/$candidate/" in
    */../*) return 13 ;;
  esac

  "$PYTHON_BIN" - "$ROOT_DIR" "$candidate" <<'PY'
from pathlib import Path
import os
import sys

root = Path(sys.argv[1]).resolve()
candidate = root / sys.argv[2]
try:
    resolved = candidate.resolve(strict=True)
except (FileNotFoundError, OSError):
    raise SystemExit(2)

try:
    relative = resolved.relative_to(root)
except ValueError:
    raise SystemExit(3)

if resolved.is_file():
    name = resolved.name
    if resolved.suffix != ".py" or not (name.startswith("test_") or name.endswith("_test.py")):
        raise SystemExit(4)
elif resolved.is_dir():
    if relative in (Path("."), Path("tests")):
        raise SystemExit(7)

    found_test = False
    for current, dirnames, filenames in os.walk(resolved, followlinks=False):
        current_path = Path(current)
        for name in (*dirnames, *filenames):
            entry = current_path / name
            if entry.is_symlink():
                raise SystemExit(8)
        for name in filenames:
            if not (name.startswith("test_") or name.endswith("_test.py")):
                continue
            path = current_path / name
            if path.suffix != ".py":
                continue
            try:
                path.resolve(strict=True).relative_to(root)
            except (FileNotFoundError, OSError, ValueError):
                raise SystemExit(8)
            found_test = True
    if not found_test:
        raise SystemExit(5)
else:
    raise SystemExit(6)

print(relative.as_posix())
PY
}

normalized_focused_targets=()
for target in "${focused_targets[@]}"; do
  normalized="$(normalize_focused_target "$target")"
  code=$?
  case "$code" in
    0) ;;
    2) runner_error "focused target does not exist: $target" ;;
    3) runner_error "focused target escapes the repository: $target" ;;
    4) runner_error "focused file is not a pytest test module: $target" ;;
    5) runner_error "focused directory contains no pytest test modules: $target" ;;
    7) runner_error "focused target cannot represent the complete root test suite: $target" ;;
    8) runner_error "focused directory contains a symlink or repository-escaping test path: $target" ;;
    10) runner_error "focused path must be repository-relative: $target" ;;
    11) runner_error "focused path cannot begin with '-': $target" ;;
    12) runner_error "focused path contains unsupported characters: $target" ;;
    13) runner_error "focused path cannot contain '..': $target" ;;
    *) runner_error "focused target is invalid: $target" ;;
  esac

  for existing in "${normalized_focused_targets[@]}"; do
    [ "$existing" != "$normalized" ] || runner_error "duplicate focused target: $normalized"
  done
  normalized_focused_targets+=("$normalized")
done

STRUCTURAL_SCRIPT="07_Agent_Tests/validate-repo-structure.sh"
if [ ! -f "$STRUCTURAL_SCRIPT" ]; then
  runner_error "missing structural validation script: $STRUCTURAL_SCRIPT"
fi

commands_executed=()
check_results=()
failed_packages=()
timing_results=()
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

timer_now_us() {
  if [ -n "${EPOCHREALTIME:-}" ]; then
    local seconds="${EPOCHREALTIME%.*}"
    local fraction="${EPOCHREALTIME#*.}000000"
    printf '%s%s\n' "$seconds" "${fraction:0:6}"
    return 0
  fi

  "$PYTHON_BIN" - <<'PY' 2>/dev/null
import time
print(time.monotonic_ns() // 1000)
PY
}

record_timing() {
  local name="$1"
  local started_us="$2"
  local ended_us="$3"

  if [[ "$started_us" =~ ^[0-9]+$ ]] && [[ "$ended_us" =~ ^[0-9]+$ ]] && [ "$ended_us" -ge "$started_us" ]; then
    timing_results+=("$name|$((ended_us - started_us))")
  else
    timing_results+=("$name|unavailable")
  fi
}

format_duration_us() {
  local duration_us="$1"
  if [ "$duration_us" = "unavailable" ]; then
    printf 'unavailable'
    return
  fi

  printf '%d.%03d s' "$((duration_us / 1000000))" "$(((duration_us % 1000000) / 1000))"
}

python_path_separator() {
  case "$(uname -s 2>/dev/null)" in
    MINGW*|MSYS*|CYGWIN*) printf ';' ;;
    *) printf ':' ;;
  esac
}

python_path_entry() {
  local path_entry="$1"
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -w "$path_entry"
  else
    printf '%s' "$path_entry"
  fi
}

python_path_with_src() {
  local src_dir="$1"
  local src_entry
  src_entry="$(python_path_entry "$src_dir")"
  if [ -n "${PYTHONPATH:-}" ]; then
    printf '%s%s%s' "$src_entry" "$(python_path_separator)" "$PYTHONPATH"
  else
    printf '%s' "$src_entry"
  fi
}

# CI_JUNIT_DIR is opt-in: unset locally, set by CI to collect real JUnit.
# When set, every pytest invocation gets a unique --junitxml path and a
# manifest.tsv is written at the end. Default local behaviour is unchanged.
junit_key() {
  local key="$1"
  key="${key//\//__}"
  printf '%s' "$key" | tr -c 'A-Za-z0-9._-' '_'
}

junit_path_for() {
  if [ -n "${CI_JUNIT_DIR:-}" ]; then
    mkdir -p "$CI_JUNIT_DIR" || runner_error "cannot prepare CI_JUNIT_DIR: $CI_JUNIT_DIR"
    printf '%s/%s.xml' "$CI_JUNIT_DIR" "$(junit_key "$1")"
  fi
}

run_check() {
  local name="$1"
  local workdir="$2"
  local command_text="$3"
  local started_us
  local ended_us
  shift 3

  commands_executed+=("$command_text")
  echo
  echo "==> $name"
  echo "    $command_text"

  started_us="$(timer_now_us || true)"
  (cd "$workdir" && "$@")
  local code=$?
  ended_us="$(timer_now_us || true)"
  record_timing "$name" "$started_us" "$ended_us"

  if [ "$code" -eq 0 ]; then
    check_results+=("PASS|$name|$command_text|$code")
  else
    check_results+=("FAIL|$name|$command_text|$code")
    record_failure "$name" "$command_text" "$code"
  fi
  return "$code"
}

run_focused_target() {
  local target="$1"
  local suite_dir="$ROOT_DIR"
  local relative_target="$target"
  local prefix=""

  case "$target" in
    tests|tests/*)
      ;;
    */tests)
      prefix="${target%/tests}"
      suite_dir="$ROOT_DIR/$prefix"
      relative_target="tests"
      ;;
    */tests/*)
      prefix="${target%%/tests/*}"
      suite_dir="$ROOT_DIR/$prefix"
      relative_target="${target#"$prefix/"}"
      ;;
  esac

  local command=("$PYTHON_BIN" -m pytest "$relative_target" -q)
  local display="cd ${suite_dir#"$ROOT_DIR"/} && $PYTHON_BIN -m pytest $relative_target -q"
  if [ "$suite_dir" = "$ROOT_DIR" ]; then
    display="$PYTHON_BIN -m pytest $relative_target -q"
  fi
  if [ -n "$focused_maxfail" ]; then
    command+=("--maxfail=$focused_maxfail")
    display+=" --maxfail=$focused_maxfail"
  fi
  if [ -n "${CI_JUNIT_DIR:-}" ]; then
    local focused_junit_path
    focused_junit_path="$(junit_path_for "focused__$target")"
    command+=("--junitxml=$focused_junit_path")
    display+=" --junitxml=$focused_junit_path"
  fi

  if [ -d "$suite_dir/src" ]; then
    local pythonpath_value
    pythonpath_value="$(python_path_with_src "$suite_dir/src")"
    local focused_display="$display"
    if [ "$suite_dir" = "$ROOT_DIR" ]; then
      focused_display="PYTHONPATH=src $display"
    else
      focused_display="cd ${suite_dir#"$ROOT_DIR"/} && PYTHONPATH=src $PYTHON_BIN -m pytest $relative_target -q"
      if [ -n "$focused_maxfail" ]; then
        focused_display+=" --maxfail=$focused_maxfail"
      fi
    fi
    run_check "focused: $target" "$suite_dir" "$focused_display" env PYTHONPATH="$pythonpath_value" "${command[@]}"
  else
    run_check "focused: $target" "$suite_dir" "$display" "${command[@]}"
  fi
}

is_python_pytest_suite() {
  local tests_dir="$1"
  find "$tests_dir" -type f \( -name 'test_*.py' -o -name '*_test.py' \) 2>/dev/null | grep -q .
}

coverage_target_for_suite() {
  # Bounded coverage: other suites keep their existing pytest command.
  case "$1" in
    "08_Tooling/workflow-scheduler") printf '%s' 'src/workflow_scheduler' ;;
    "08_Tooling/reusable-capability-registry") printf '%s' 'src/reusable_capability_registry' ;;
    "08_Tooling/visual-asset-intake") printf '%s' 'src/visual_asset_intake' ;;
  esac
}

coverage_report_for_suite() {
  if [ "$1" = "08_Tooling/workflow-scheduler" ]; then
    printf 'term'
  else
    printf 'term-missing'
  fi
}

# With these plugins disabled pytest itself rejects --setup-only/--setup-plan
# (exit 4, "unrecognized arguments") from any config source; both options write
# passing-looking JUnit without running test bodies.
PYTEST_EXECUTION_GUARD=(-p no:setuponly -p no:setupplan)

# Every suite writes JUnit so its executed tests can be reconciled against the
# reference collection: published under CI_JUNIT_DIR when set (and shown in the
# command text), otherwise a private runner temp file (not shown, not published).
suite_junit_path_for() {
  if [ -n "${CI_JUNIT_DIR:-}" ]; then
    junit_path_for "$1"
  else
    printf '%s/junit/%s.xml' "$parallel_tmp" "$(junit_key "$1")"
  fi
}

run_pytest_suite() {
  local suite_dir="$1"
  local suite_name="$2"
  local suite_junit_path
  suite_junit_path="$(suite_junit_path_for "$suite_name")"
  local guard_display="${PYTEST_EXECUTION_GUARD[*]}"

  if [ "$suite_name" = "08_Tooling/workflow-scheduler" ]; then
    : # Preserve scheduler suite identity for canonical aggregate admission.
  fi
  if [ -d "$suite_dir/src" ]; then
    local command=("$PYTHON_BIN" -m pytest tests)
    local display="cd $suite_dir && PYTHONPATH=src $PYTHON_BIN -m pytest tests"
    local coverage_target
    local coverage_report
    coverage_target="$(coverage_target_for_suite "$suite_name")"
    if [ "$suite_name" = "08_Tooling/workflow-scheduler" ]; then
      # Preserve the canonical scheduler coverage invocation (#2126).
      command+=("--cov=src/workflow_scheduler" "--cov-report=term")
      display+=" --cov=src/workflow_scheduler --cov-report=term"
    elif [ -n "$coverage_target" ]; then
      coverage_report="$(coverage_report_for_suite "$suite_name")"
      command+=("--cov=$coverage_target" "--cov-report=$coverage_report")
      display+=" --cov=$coverage_target --cov-report=$coverage_report"
    fi
    command+=("--junitxml=$suite_junit_path" "${PYTEST_EXECUTION_GUARD[@]}")
    [ -n "${CI_JUNIT_DIR:-}" ] && display+=" --junitxml=$suite_junit_path"
    display+=" $guard_display"
    local src_dir
    local pythonpath_value
    src_dir="$(cd "$suite_dir" && pwd)/src"
    pythonpath_value="$(python_path_with_src "$src_dir")"
    if [ -n "$coverage_target" ]; then
      # Isolated even across parallel suites; logs retain terminal reports.
      local coverage_file="$parallel_tmp/coverage/$suite_name/.coverage"
      mkdir -p "$(dirname "$coverage_file")" || runner_error "cannot prepare isolated coverage path for $suite_name"
      run_check "$suite_name" "$suite_dir" "$display" env PYTHONPATH="$pythonpath_value" COVERAGE_FILE="$coverage_file" "${command[@]}"
    else
      run_check "$suite_name" "$suite_dir" "$display" env PYTHONPATH="$pythonpath_value" "${command[@]}"
    fi
  else
    local plain_display="cd $suite_dir && $PYTHON_BIN -m pytest tests"
    local plain_command=("$PYTHON_BIN" -m pytest tests)
    plain_command+=("--junitxml=$suite_junit_path" "${PYTEST_EXECUTION_GUARD[@]}")
    [ -n "${CI_JUNIT_DIR:-}" ] && plain_display+=" --junitxml=$suite_junit_path"
    plain_display+=" $guard_display"
    run_check "$suite_name" "$suite_dir" "$plain_display" "${plain_command[@]}"
  fi
}

suite_command_text() {
  local suite_dir="$1"
  local suite_name="$2"
  if [ -d "$suite_dir/src" ]; then
    local display="cd $suite_dir && PYTHONPATH=src $PYTHON_BIN -m pytest tests"
    local coverage_target
    coverage_target="$(coverage_target_for_suite "$suite_name")"
    if [ -n "$coverage_target" ]; then
      local coverage_report
      coverage_report="$(coverage_report_for_suite "$suite_name")"
      display+=" --cov=$coverage_target --cov-report=$coverage_report"
    fi
    if [ -n "${CI_JUNIT_DIR:-}" ]; then
      display+=" --junitxml=$(junit_path_for "$suite_name")"
    fi
    printf '%s %s' "$display" "${PYTEST_EXECUTION_GUARD[*]}"
  else
    local plain="cd $suite_dir && $PYTHON_BIN -m pytest tests"
    if [ -n "${CI_JUNIT_DIR:-}" ]; then
      plain+=" --junitxml=$(junit_path_for "$suite_name")"
    fi
    printf '%s %s' "$plain" "${PYTEST_EXECUTION_GUARD[*]}"
  fi
}

run_captured_suite() {
  local suite_dir="$1"
  local suite_name="$2"
  local output_file="$3"
  local status_file="$4"
  local started_us
  local ended_us
  local code

  started_us="$(timer_now_us || true)"
  run_pytest_suite "$suite_dir" "$suite_name" >"$output_file" 2>&1
  code=$?
  ended_us="$(timer_now_us || true)"
  printf '%s|%s|%s\n' "$code" "$started_us" "$ended_us" >"$status_file"
  return 0
}

# Test-selection completeness (false-green repair, PR #3816). A suite that
# passed must also have executed every test of the runner-owned reference
# collection; the executed set is the suite's own JUnit, not a prediction.
# Runs after each passing suite. The receipt is cleared first so a prior
# attempt's receipt is never evidence for this one.
check_test_completeness() {
  local suite_name="$1"
  local suite_dir="$ROOT_DIR"
  [ "$suite_name" = "root" ] || suite_dir="$ROOT_DIR/$suite_name"
  local junit_path
  junit_path="$(suite_junit_path_for "$suite_name")"
  local name="test selection completeness: $suite_name"
  local args=("$PYTHON_BIN" scripts/agent_os_ci_test_completeness.py --suite-dir "$suite_dir" --suite-name "$suite_name" --python-bin "$PYTHON_BIN" --junit "$junit_path")
  local display="$PYTHON_BIN scripts/agent_os_ci_test_completeness.py --suite-dir $suite_dir --suite-name $suite_name --python-bin $PYTHON_BIN --junit $junit_path"
  local receipt=""
  if [ -n "${CI_JUNIT_DIR:-}" ]; then
    mkdir -p "$CI_JUNIT_DIR" || runner_error "cannot prepare CI_JUNIT_DIR: $CI_JUNIT_DIR"
    receipt="$CI_JUNIT_DIR/test-completeness-$(junit_key "$suite_name").json"
    rm -f "$receipt" || runner_error "cannot replace stale completeness receipt: $receipt"
    args+=(--receipt "$receipt")
    display+=" --receipt $receipt"
  fi
  local started_us ended_us code
  started_us="$(timer_now_us || true)"
  if [ -d "$suite_dir/src" ]; then
    env PYTHONPATH="$(python_path_with_src "$suite_dir/src")" "${args[@]}"
  else
    "${args[@]}"
  fi
  code=$?
  # A successful helper exit is not enough when its evidence is missing.
  if [ "$code" -eq 0 ] && [ -n "$receipt" ]; then
    if [ ! -f "$receipt" ] || ! grep -Eq '^[[:space:]]*"verdict"[[:space:]]*:[[:space:]]*"COMPLETE"' "$receipt"; then
      echo "completeness helper succeeded without a COMPLETE receipt: $suite_name" >&2
      code=2
    fi
  fi
  ended_us="$(timer_now_us || true)"
  record_timing "$name" "$started_us" "$ended_us"
  commands_executed+=("$display")
  if [ "$code" -eq 0 ]; then
    check_results+=("PASS|$name|$display|$code")
  else
    check_results+=("FAIL|$name|$display|$code")
    record_failure "$name" "$display" "$code"
  fi
}

consume_captured_suite() {
  local suite_name="$1"
  local command_text="$2"
  local output_file="$3"
  local status_file="$4"
  local code started_us ended_us

  cat "$output_file"
  IFS='|' read -r code started_us ended_us <"$status_file"
  commands_executed+=("$command_text")
  record_timing "$suite_name" "$started_us" "$ended_us"
  if [ "$code" -eq 0 ]; then
    check_results+=("PASS|$suite_name|$command_text|$code")
    check_test_completeness "$suite_name"
  else
    check_results+=("FAIL|$suite_name|$command_text|$code")
    record_failure "$suite_name" "$command_text" "$code"
  fi
}

aggregate_started_us="$(timer_now_us || true)"

# PYTEST_ADDOPTS would silently narrow every pytest invocation below --
# the completeness collections, the real suite runs, and the focused
# runs -- because it applies identically to all of them. The
# completeness check cannot detect it (both collections would narrow
# together), so an authoritative run must not have it set at all.
# Unset it loudly rather than failing: a local operator may have it
# set for an unrelated reason, and the run stays valid without it.
if [ -n "${PYTEST_ADDOPTS:-}" ]; then
  echo "PYTEST_ADDOPTS is set in this environment; unsetting it so the authoritative run is not silently narrowed." >&2
  unset PYTEST_ADDOPTS
fi

echo "AGGREGATE VALIDATION START"
echo "Repository: $ROOT_DIR"
echo "Python: $PYTHON_BIN"

for target in "${normalized_focused_targets[@]}"; do
  run_focused_target "$target"
done

run_check "Ruff lint" "$ROOT_DIR" "$PYTHON_BIN -m ruff check ." "$PYTHON_BIN" -m ruff check .

run_check "structural validation" "$ROOT_DIR" "PYTHON_BIN=$PYTHON_BIN bash $STRUCTURAL_SCRIPT" env PYTHON_BIN="$PYTHON_BIN" bash "$STRUCTURAL_SCRIPT"

mapfile -t test_dirs < <(
  find . -type d -name tests \
    -not -path './.git/*' \
    -not -path './.venv/*' \
    -not -path './venv/*' \
    -not -path './node_modules/*' \
    -not -path './.tmp/*' \
    -not -path './03_Templates/*' \
    | sort | while IFS= read -r test_dir; do
        if is_python_pytest_suite "$test_dir"; then
          printf '%s\n' "$test_dir"
        fi
      done
)

if [ "${#test_dirs[@]}" -eq 0 ]; then
  runner_error "no pytest test directories discovered."
fi

parallel_tmp="$(mktemp -d "${TMPDIR:-/tmp}/agent-os-validate.XXXXXX")" || runner_error "unable to create validation capture directory."
trap 'rm -rf "$parallel_tmp"' EXIT
mkdir -p "$parallel_tmp/junit" || runner_error "unable to create private JUnit directory."

pending_names=()
pending_commands=()
pending_outputs=()
pending_statuses=()
pending_pids=()

flush_parallel_batch() {
  local i
  for i in "${!pending_pids[@]}"; do
    wait "${pending_pids[$i]}" || true
  done
  for i in "${!pending_names[@]}"; do
    consume_captured_suite "${pending_names[$i]}" "${pending_commands[$i]}" "${pending_outputs[$i]}" "${pending_statuses[$i]}"
  done
  pending_names=()
  pending_commands=()
  pending_outputs=()
  pending_statuses=()
  pending_pids=()
}

for test_dir in "${test_dirs[@]}"; do
  suite_dir="$(dirname "$test_dir")"
  if [ "$suite_dir" = "." ]; then
    suite_name="root"
    suite_dir="$ROOT_DIR"
  else
    suite_name="${suite_dir#./}"
  fi

  if [ "$suite_name" = "08_Tooling/instructional-materials-coach" ]; then
    flush_parallel_batch
    if run_pytest_suite "$suite_dir" "$suite_name"; then
      check_test_completeness "$suite_name"
    fi
    continue
  fi

  index="${#pending_names[@]}"
  output_file="$parallel_tmp/output-$index"
  status_file="$parallel_tmp/status-$index"
  command_text="$(suite_command_text "$suite_dir" "$suite_name")"
  pending_names+=("$suite_name")
  pending_commands+=("$command_text")
  pending_outputs+=("$output_file")
  pending_statuses+=("$status_file")
  run_captured_suite "$suite_dir" "$suite_name" "$output_file" "$status_file" &
  pending_pids+=("$!")

  if [ "${#pending_pids[@]}" -ge "$VALIDATE_ALL_MAX_PARALLEL" ]; then
    flush_parallel_batch
  fi
done
flush_parallel_batch

if [ -n "${CI_JUNIT_DIR:-}" ]; then
  mkdir -p "$CI_JUNIT_DIR" || runner_error "cannot prepare CI_JUNIT_DIR: $CI_JUNIT_DIR"
  manifest_file="$CI_JUNIT_DIR/manifest.tsv"
  printf 'suite_name\tjunit_file\tjunit_exists\tstatus\texit_code\tclassification\n' > "$manifest_file"
  for result in "${check_results[@]}"; do
    IFS='|' read -r status name command_text code <<< "$result"
    case "$name" in
      "Ruff lint"|"structural validation") continue ;;
    esac
    case "$name" in
      "focused: "*)
        target_name="${name#focused: }"
        junit_file="$(junit_key "focused__$target_name").xml"
        ;;
      *)
        junit_file="$(junit_key "$name").xml"
        ;;
    esac
    if [[ "$name" == "test selection completeness: "* ]]; then
      # The completeness check has no JUnit file of its own; its evidence
      # is the test-completeness-<suite>.json receipt in CI_JUNIT_DIR, so
      # the row points at the receipt and records whether it exists.
      # Exit 1 proves an omission only with an INCOMPLETE receipt from
      # this attempt. Uncaught helper exceptions also exit 1 but have
      # no comparison evidence; they must be TEST_COLLECTION_ERROR.
      completeness_suite="${name#test selection completeness: }"
      junit_file="test-completeness-$(junit_key "$completeness_suite").json"
      if [ -f "$CI_JUNIT_DIR/$junit_file" ]; then junit_exists="yes"; else junit_exists="no"; fi
      if [ "$status" = "PASS" ] && [ "$code" = "0" ] && [ "$junit_exists" = "yes" ]; then
        classification="COMPLETE"
      elif [ "$code" = "1" ] && [ "$junit_exists" = "yes" ] && grep -Eq '^[[:space:]]*"verdict"[[:space:]]*:[[:space:]]*"OUTCOME_FAILED"' "$CI_JUNIT_DIR/$junit_file"; then
        # NC09: executed tests failed or errored. The suite passed on what it
        # ran only in the runner's exit code; the JUnit outcome is the verdict.
        classification="TEST_OUTCOME_FAILED"
      elif [ "$code" = "1" ] && [ "$junit_exists" = "yes" ] && grep -Eq '^[[:space:]]*"verdict"[[:space:]]*:[[:space:]]*"INCOMPLETE"' "$CI_JUNIT_DIR/$junit_file"; then
        classification="TEST_SELECTION_INCOMPLETE"
      else
        classification="TEST_COLLECTION_ERROR"
      fi
    elif [ "$code" = "5" ]; then
      # pytest exit 5 = no tests collected: never a pass, never a generic failure.
      if [ -f "$CI_JUNIT_DIR/$junit_file" ]; then junit_exists="yes"; else junit_exists="no"; fi
      classification="ZERO_COLLECTED"
    elif [ -f "$CI_JUNIT_DIR/$junit_file" ]; then
      junit_exists="yes"
      if [ "$status" = "PASS" ]; then classification="EXECUTED_PASS"; else classification="EXECUTED_FAIL"; fi
      # NC09: a suite whose JUnit contains failures/errors must never be
      # recorded EXECUTED_PASS, even when the runner reported exit 0 (a
      # swallowed exit cannot manufacture a clean report). The completeness
      # receipt for this suite is the independent outcome evidence; its
      # verdict reclassifies the suite row and fails it. The recorded exit
      # code is preserved as evidence of what the runner reported.
      outcome_receipt="$CI_JUNIT_DIR/test-completeness-$(junit_key "$name").json"
      if [ "$classification" = "EXECUTED_PASS" ] && [ -f "$outcome_receipt" ]; then
        if grep -Eq '^[[:space:]]*"verdict"[[:space:]]*:[[:space:]]*"OUTCOME_FAILED"' "$outcome_receipt"; then
          status="FAIL"
          classification="TEST_OUTCOME_FAILED"
        elif grep -Eq '^[[:space:]]*"verdict"[[:space:]]*:[[:space:]]*"ERROR"' "$outcome_receipt"; then
          # Invalid JUnit evidence cannot certify a passing suite.
          # Preserve the original runner exit code for diagnostics.
          status="FAIL"
          classification="TEST_COLLECTION_ERROR"
        fi
      fi
    else
      junit_exists="no"
      if [ "$status" = "FAIL" ]; then classification="NOT_EXECUTED_SETUP_FAILURE"; else classification="MISSING_UNEXPECTED"; fi
    fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$name" "$junit_file" "$junit_exists" "$status" "$code" "$classification" >> "$manifest_file"
  done
fi

aggregate_ended_us="$(timer_now_us || true)"
record_timing "aggregate total" "$aggregate_started_us" "$aggregate_ended_us"

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
echo "TIMING RESULTS"
for timing in "${timing_results[@]}"; do
  IFS='|' read -r name duration_us <<< "$timing"
  echo "- $name | $(format_duration_us "$duration_us")"
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
