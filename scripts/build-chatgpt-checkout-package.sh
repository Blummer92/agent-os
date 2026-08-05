#!/usr/bin/env bash
# Agent OS exact-head ChatGPT checkout package builder (operator surface).
#
# Builds one reproducible ZIP of an explicitly supplied branch, tag, or exact
# 40-character commit SHA, for offline ChatGPT code-execution validation. It
# invents no checkout, fetch, worktree, or repository-state system of its own:
# resolution and isolation are delegated entirely to
# scripts/prepare-issue-worktree.sh (issue #807), which itself reuses the
# canonical fetch-retry contract from scripts/verify-repo-state-contract.md
# (issue #621).
#
# It never commits, pushes, opens/edits a PR, merges, closes issues, modifies
# labels, invokes providers, or performs any other GitHub-lifecycle or
# external-system write. Every authority field in its evidence is false.
#
# Documentation: scripts/build-chatgpt-checkout-package.md

set -uo pipefail

readonly EXIT_OK=0
readonly EXIT_USAGE=2
readonly EXIT_DIRTY=3
readonly EXIT_FETCH=4
readonly EXIT_REF_MISSING=5
readonly EXIT_WORKTREE=6
readonly EXIT_CONFLICT=7
readonly EXIT_BASE=8
readonly EXIT_EVIDENCE=9
readonly EXIT_OUTPUT=10

readonly SCHEMA="agent-os.chatgpt-checkout-package.v1"
readonly SCHEMA_VERSION="1"
readonly COMMAND_VERSION="build-chatgpt-checkout-package.v1"
readonly PACKAGE_FORMAT="zip"
readonly MAX_REASON_CHARS=200

# Tracked files matching these patterns are excluded even though Git tracked
# them, as defense in depth against credentials or transient artifacts that
# slipped past .gitignore. This is a static, reviewable list -- nothing here
# infers safety from file content.
readonly EXCLUDE_PATTERNS=(
  '.env' '.env.*' '*.pem' '*.key' 'id_rsa' 'id_rsa.*' 'id_ed25519' 'id_ed25519.*'
  '*credentials*' '*secret*' '.DS_Store' '*.pyc' '__pycache__/*' '.pytest_cache/*'
  '.venv/*' 'venv/*' 'node_modules/*' 'dist/*' 'build/*' '*.zip'
)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
readonly PREPARE_SCRIPT="$SCRIPT_DIR/prepare-issue-worktree.sh"

log() { printf 'build-chatgpt-checkout-package: %s\n' "$*" >&2; }

sanitize() {
  printf '%s' "$1" | tr -d '[:cntrl:]"\\' | cut -c "1-$MAX_REASON_CHARS"
}

json_array() {
  local first=1 item
  printf '['
  for item in "$@"; do
    [ "$first" -eq 1 ] || printf ', '
    printf '"%s"' "$item"
    first=0
  done
  printf ']'
}

# --- Evidence state ----------------------------------------------------------

REPOSITORY=""
ISSUE=""
REQUESTED_REF=""
OUTPUT=""
WORKTREE_ROOT=""
BASE_REF="main"
WORKTREE_ROOT_PROVIDED=0

RESOLVED_REF=""
RESOLVED_SHA=""
BASE_SHA=""
CHECKOUT_MODE=""
WORKING_TREE_CLEAN="false"
INCLUDED_GIT_METADATA="false"
FILE_COUNT=0
ARCHIVE_SHA256=""
SIDE_EFFECTS=()
WORKTREE_PATH=""

record_side_effect() { SIDE_EFFECTS+=("$1"); }

cleanup_worktree() {
  [ "$WORKTREE_ROOT_PROVIDED" -eq 0 ] || return 0
  [ -n "$WORKTREE_PATH" ] && git worktree remove --force "$WORKTREE_PATH" >/dev/null 2>&1
  [ -n "$WORKTREE_ROOT" ] && rmdir "$WORKTREE_ROOT" >/dev/null 2>&1
  true
}
trap cleanup_worktree EXIT

finish() {
  local code="$1" status="$2" reason
  reason="$(sanitize "$3")"

  local issue_json="null"
  case "$ISSUE" in
    ''|*[!0-9]*) : ;;
    *) issue_json="$ISSUE" ;;
  esac

  printf '{\n'
  printf '  "schema_name": "%s",\n' "$SCHEMA"
  printf '  "schema_version": "%s",\n' "$SCHEMA_VERSION"
  printf '  "status": "%s",\n' "$status"
  printf '  "repository": "%s",\n' "$REPOSITORY"
  printf '  "issue_number": %s,\n' "$issue_json"
  printf '  "requested_ref": "%s",\n' "$REQUESTED_REF"
  printf '  "resolved_ref": "%s",\n' "$RESOLVED_REF"
  printf '  "resolved_sha": "%s",\n' "$RESOLVED_SHA"
  printf '  "base_ref": "%s",\n' "$BASE_REF"
  printf '  "base_sha": "%s",\n' "$BASE_SHA"
  printf '  "checkout_mode": "%s",\n' "$CHECKOUT_MODE"
  printf '  "working_tree_clean": %s,\n' "$WORKING_TREE_CLEAN"
  printf '  "package_format": "%s",\n' "$PACKAGE_FORMAT"
  printf '  "included_git_metadata": %s,\n' "$INCLUDED_GIT_METADATA"
  printf '  "file_count": %s,\n' "$FILE_COUNT"
  printf '  "archive_sha256": "%s",\n' "$ARCHIVE_SHA256"
  printf '  "created_by_command_version": "%s",\n' "$COMMAND_VERSION"
  printf '  "side_effects_performed": %s,\n' "$(json_array "${SIDE_EFFECTS[@]:-}")"
  printf '  "implementation_authorized": false,\n'
  printf '  "execution_authorized": false,\n'
  printf '  "github_writes_authorized": false,\n'
  printf '  "merge_authorized": false,\n'
  printf '  "output_path": "%s",\n' "$OUTPUT"
  printf '  "reason": "%s"\n' "$reason"
  printf '}\n'

  log "STATUS=$status ref=${REQUESTED_REF:-none} sha=${RESOLVED_SHA:-none} output=${OUTPUT:-none}"
  log "reason: $reason"
  exit "$code"
}

usage() {
  cat >&2 <<'USAGE'
Usage: scripts/build-chatgpt-checkout-package.sh \
         --repository <owner/name> --issue <n> --ref <branch|tag|sha40> \
         --output <absolute .zip path> \
         [--worktree-root <absolute path>] [--base-ref <branch>]

Builds one deterministic exact-head ZIP package for ChatGPT code-execution
validation, reusing scripts/prepare-issue-worktree.sh (#807) for all checkout,
fetch, and worktree-isolation behavior. Never commits, pushes, or performs any
GitHub-lifecycle or external-system write.

Options:
  --repository <owner/name> Expected repository identity of origin. Required.
  --issue <n>               Agent OS issue number. Required.
  --ref <ref>               Branch, tag, or exact 40-char commit SHA. Required.
  --output <path>           Absolute output .zip path. Must not already exist.
  --worktree-root <path>    Reuse an existing prepared worktree root instead of
                            a disposable one. Advanced/testing use.
  --base-ref <branch>       Base branch for base_ref/base_sha evidence.
                            Default: main.
  -h, --help                Show this help.

Statuses: built | blocked | unavailable | manual-review
Exit codes: 0 built, 2 usage, 3 dirty, 4 fetch, 5 ref missing,
6 worktree, 7 conflict, 8 base ref, 9 evidence, 10 output collision.
USAGE
}

require_value() {
  [ "$2" -ge 2 ] || { usage; finish "$EXIT_USAGE" blocked "$1 requires a value"; }
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --repository) require_value "$1" "$#"; REPOSITORY="$2"; shift 2 ;;
    --issue) require_value "$1" "$#"; ISSUE="$2"; shift 2 ;;
    --ref) require_value "$1" "$#"; REQUESTED_REF="$2"; shift 2 ;;
    --output) require_value "$1" "$#"; OUTPUT="$2"; shift 2 ;;
    --worktree-root) require_value "$1" "$#"; WORKTREE_ROOT="$2"; WORKTREE_ROOT_PROVIDED=1; shift 2 ;;
    --base-ref) require_value "$1" "$#"; BASE_REF="$2"; shift 2 ;;
    -h|--help) usage; exit "$EXIT_OK" ;;
    *) usage; finish "$EXIT_USAGE" blocked "unexpected argument: $1" ;;
  esac
done

[ -n "$REPOSITORY" ] || { usage; finish "$EXIT_USAGE" blocked "--repository is required"; }
[ -n "$ISSUE" ] || { usage; finish "$EXIT_USAGE" blocked "--issue is required"; }
case "$ISSUE" in
  ''|*[!0-9]*|0*) finish "$EXIT_USAGE" blocked "--issue must be a positive integer: $ISSUE" ;;
esac
[ -n "$REQUESTED_REF" ] || { usage; finish "$EXIT_USAGE" blocked "--ref is required"; }
[ -n "$OUTPUT" ] || { usage; finish "$EXIT_USAGE" blocked "--output is required"; }

case "$OUTPUT" in
  /*) : ;;
  *) finish "$EXIT_USAGE" blocked "--output must be an absolute path: $OUTPUT" ;;
esac
case "$OUTPUT" in
  *.zip) : ;;
  *) finish "$EXIT_USAGE" blocked "--output must end in .zip: $OUTPUT" ;;
esac
[ ! -e "$OUTPUT" ] ||
  finish "$EXIT_OUTPUT" blocked \
    "--output already exists; no replacement mode is authorized: $OUTPUT"

output_dir="$(dirname "$OUTPUT")"
[ -d "$output_dir" ] || finish "$EXIT_USAGE" blocked "--output parent directory does not exist: $output_dir"

[ -x "$PREPARE_SCRIPT" ] || [ -f "$PREPARE_SCRIPT" ] ||
  finish "$EXIT_EVIDENCE" unavailable "reused checkout-preparation script is missing: $PREPARE_SCRIPT"

if [ -z "$WORKTREE_ROOT" ]; then
  WORKTREE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/agent-os-chatgpt-package.XXXXXX")" ||
    finish "$EXIT_WORKTREE" unavailable "unable to create a disposable worktree root"
fi

# --- Delegate all checkout/fetch/worktree/exact-SHA-verification behavior --
# to the canonical #807 preparation command. This command adds no second
# fetch-retry, dirty-tree, or ref-resolution implementation.

log "delegating checkout preparation to $PREPARE_SCRIPT"
prepare_json="$(bash "$PREPARE_SCRIPT" \
  --issue "$ISSUE" --repository "$REPOSITORY" --ref "$REQUESTED_REF" \
  --worktree-root "$WORKTREE_ROOT" 2>&2)"
prepare_exit=$?

prepare_field() {
  printf '%s' "$prepare_json" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(1)
print(data.get(sys.argv[1], ""))
' "$1" 2>/dev/null
}

prepare_status="$(prepare_field status)"
CHECKOUT_MODE="$(prepare_field checkout_mode)"
RESOLVED_REF="$(prepare_field resolved_ref)"
RESOLVED_SHA="$(prepare_field resolved_sha)"
WORKTREE_PATH="$(prepare_field worktree_path)"
prepare_reason="$(prepare_field reason)"

if [ "$prepare_exit" -ne 0 ] || { [ "$prepare_status" != "prepared" ] && [ "$prepare_status" != "already-prepared" ]; }; then
  case "$prepare_exit" in
    "$EXIT_DIRTY") finish "$EXIT_DIRTY" blocked "checkout preparation reported dirty tracked state: $prepare_reason" ;;
    "$EXIT_FETCH") finish "$EXIT_FETCH" unavailable "checkout preparation could not fetch: $prepare_reason" ;;
    "$EXIT_REF_MISSING") finish "$EXIT_REF_MISSING" blocked "checkout preparation could not resolve --ref: $prepare_reason" ;;
    "$EXIT_CONFLICT") finish "$EXIT_CONFLICT" manual-review "checkout preparation found a conflict: $prepare_reason" ;;
    *) finish "$EXIT_WORKTREE" unavailable "checkout preparation failed (exit $prepare_exit): $prepare_reason" ;;
  esac
fi
record_side_effect "worktree-prepared"

# --- Re-verify the resolved SHA immediately before packaging ---------------
# Preparation evidence is trusted for resolution, never for the state of the
# tree at packaging time: re-read HEAD and dirty state directly.

[ -d "$WORKTREE_PATH" ] || finish "$EXIT_WORKTREE" unavailable "prepared worktree path is missing: $WORKTREE_PATH"

actual_head="$(git -C "$WORKTREE_PATH" rev-parse HEAD 2>/dev/null)" ||
  finish "$EXIT_EVIDENCE" unavailable "unable to read HEAD of prepared worktree"
[ "$actual_head" = "$RESOLVED_SHA" ] ||
  finish "$EXIT_EVIDENCE" manual-review \
    "worktree HEAD $actual_head no longer matches resolved commit $RESOLVED_SHA; refusing to package a different head"

pre_pack_dirty="$(git -C "$WORKTREE_PATH" status --porcelain --untracked-files=no 2>/dev/null)" ||
  finish "$EXIT_EVIDENCE" unavailable "unable to read status of prepared worktree"
if [ -n "$pre_pack_dirty" ]; then
  finish "$EXIT_DIRTY" blocked "prepared worktree became dirty before packaging; refusing to package"
fi
WORKING_TREE_CLEAN="true"

base_remote_ref="refs/remotes/origin/$BASE_REF"
BASE_SHA="$(git -C "$WORKTREE_PATH" rev-parse --verify --quiet "$base_remote_ref")" ||
  finish "$EXIT_BASE" blocked "base ref origin/$BASE_REF does not exist in the prepared worktree"

# --- Build the manifest and archive (Python: JSON, zipfile, hashing) -------
# Kept inline (no separate module file) so the allowlisted .sh file is the
# single source of packaging logic; no second packaging implementation exists.

BUILD_OUTPUT="$(python3 - "$WORKTREE_PATH" "$OUTPUT" "$SCHEMA" "$SCHEMA_VERSION" \
    "$REPOSITORY" "$ISSUE" "$REQUESTED_REF" "$RESOLVED_REF" "$RESOLVED_SHA" \
    "$BASE_REF" "$BASE_SHA" "$CHECKOUT_MODE" "$WORKING_TREE_CLEAN" \
    "$PACKAGE_FORMAT" "$INCLUDED_GIT_METADATA" "$COMMAND_VERSION" \
    "${EXCLUDE_PATTERNS[@]}" <<'PYEOF'
import fnmatch
import hashlib
import json
import subprocess
import sys
import zipfile

(worktree, output, schema, schema_version, repository, issue, requested_ref,
 resolved_ref, resolved_sha, base_ref, base_sha, checkout_mode,
 working_tree_clean, package_format, included_git_metadata,
 command_version, *exclude_patterns) = sys.argv[1:]

# Tracked files only: this is exactly what Git considers "in the repository"
# at this commit, so untracked local caches, editor state, and ignored
# credentials are excluded by construction rather than re-derived here.
tracked = subprocess.run(
    ["git", "-C", worktree, "ls-files", "-z"],
    check=True, capture_output=True,
).stdout.decode("utf-8").split("\0")
tracked = [p for p in tracked if p]

def is_excluded(path):
    return any(fnmatch.fnmatch(path, pat) for pat in exclude_patterns)

included = sorted(p for p in tracked if not is_excluded(p))
excluded = sorted(p for p in tracked if is_excluded(p))
for path in excluded:
    print(f"build-chatgpt-checkout-package: excluding tracked path {path}", file=sys.stderr)

# Deterministic semantic digest over canonical entry paths and content,
# independent of ZIP compression/timestamp/host details (determinism
# boundary: see scripts/build-chatgpt-checkout-package.md). manifest.json is
# excluded from its own digest to avoid a circular self-reference.
digest = hashlib.sha256()
entries = []
for path in included:
    with open(f"{worktree}/{path}", "rb") as fh:
        data = fh.read()
    file_sha = hashlib.sha256(data).hexdigest()
    entries.append((path, len(data), file_sha))
    digest.update(path.encode("utf-8"))
    digest.update(b"\0")
    digest.update(file_sha.encode("utf-8"))
    digest.update(b"\n")
archive_sha256 = digest.hexdigest()

manifest = {
    "schema_name": schema,
    "schema_version": schema_version,
    "repository": repository,
    "issue_number": int(issue),
    "requested_ref": requested_ref,
    "resolved_ref": resolved_ref,
    "resolved_sha": resolved_sha,
    "base_ref": base_ref,
    "base_sha": base_sha,
    "checkout_mode": checkout_mode,
    "working_tree_clean": working_tree_clean == "true",
    "package_format": package_format,
    "included_git_metadata": included_git_metadata == "true",
    "file_count": len(included),
    "archive_sha256": archive_sha256,
    "created_by_command_version": command_version,
    "side_effects_performed": ["worktree-prepared", "archive-written"],
    "implementation_authorized": False,
    "execution_authorized": False,
    "github_writes_authorized": False,
    "merge_authorized": False,
}
manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8") + b"\n"

FIXED_DATE_TIME = (1980, 1, 1, 0, 0, 0)

def write_entry(zf, path, data):
    info = zipfile.ZipInfo(path, date_time=FIXED_DATE_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (0o644 << 16)
    zf.writestr(info, data)

with zipfile.ZipFile(output, "w", allowZip64=True) as zf:
    for path in included:
        with open(f"{worktree}/{path}", "rb") as fh:
            write_entry(zf, path, fh.read())
    write_entry(zf, "agent-os-chatgpt-package-manifest.json", manifest_bytes)

# Verify the completed archive before reporting success: reopen it, and
# confirm entry count and recomputed semantic digest match the manifest.
with zipfile.ZipFile(output) as zf:
    bad = zf.testzip()
    if bad is not None:
        print(f"corrupt entry in archive: {bad}", file=sys.stderr)
        sys.exit(1)
    names = set(zf.namelist())
    expected = set(included) | {"agent-os-chatgpt-package-manifest.json"}
    if names != expected:
        print("archive contents do not match the intended file set", file=sys.stderr)
        sys.exit(1)
    with zf.open("agent-os-chatgpt-package-manifest.json") as fh:
        stored_manifest = json.load(fh)
    if stored_manifest != manifest:
        print("stored manifest does not match computed manifest", file=sys.stderr)
        sys.exit(1)
    verify_digest = hashlib.sha256()
    for path in included:
        with zf.open(path) as fh:
            data = fh.read()
        file_sha = hashlib.sha256(data).hexdigest()
        verify_digest.update(path.encode("utf-8"))
        verify_digest.update(b"\0")
        verify_digest.update(file_sha.encode("utf-8"))
        verify_digest.update(b"\n")
    if verify_digest.hexdigest() != archive_sha256:
        print("post-write archive digest does not match recorded archive_sha256", file=sys.stderr)
        sys.exit(1)

print(json.dumps({"file_count": len(included), "archive_sha256": archive_sha256}))
PYEOF
)"
build_exit=$?

if [ "$build_exit" -ne 0 ]; then
  finish "$EXIT_EVIDENCE" unavailable "packaging or archive verification failed: see stderr above"
fi

FILE_COUNT="$(printf '%s' "$BUILD_OUTPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin)["file_count"])')"
ARCHIVE_SHA256="$(printf '%s' "$BUILD_OUTPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin)["archive_sha256"])')"
record_side_effect "archive-written"

finish "$EXIT_OK" built \
  "exact-head package built and verified at $RESOLVED_SHA; no commit, push, PR, issue, or external write occurred"
