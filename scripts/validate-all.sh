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

run_pytest_suite() {
  local suite_dir="$1"
  local suite_name="$2"

  if [ -d "$suite_dir/src" ]; then
    local display="cd $suite_dir && PYTHONPATH=src $PYTHON_BIN -m pytest tests"
    local src_dir
    local pythonpath_value
    src_dir="$(cd "$suite_dir" && pwd)/src"
    pythonpath_value="$(python_path_with_src "$src_dir")"
    run_check "$suite_name" "$suite_dir" "$display" env PYTHONPATH="$pythonpath_value" "$PYTHON_BIN" -m pytest tests
  else
    run_check "$suite_name" "$suite_dir" "cd $suite_dir && $PYTHON_BIN -m pytest tests" "$PYTHON_BIN" -m pytest tests
  fi
}

aggregate_started_us="$(timer_now_us || true)"

echo "AGGREGATE VALIDATION START"
echo "Repository: $ROOT_DIR"
echo "Python: $PYTHON_BIN"

for target in "${normalized_focused_targets[@]}"; do
  run_focused_target "$target"
done

run_check "structural validation" "$ROOT_DIR" "bash $STRUCTURAL_SCRIPT" bash "$STRUCTURAL_SCRIPT"

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
  runner_error "no pytest test directories discovered."
fi

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
