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
# Packaged paths, modes, and bytes are read from the selected commit object,
# never from the mutable worktree, so the manifest SHA and the archive contents
# always describe the same commit.
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
readonly EXIT_SYMLINK=11

readonly SCHEMA="agent-os.chatgpt-checkout-package.v1"
readonly SCHEMA_VERSION="1"
readonly COMMAND_VERSION="build-chatgpt-checkout-package.v1"
readonly PACKAGE_FORMAT="zip"
readonly MAX_REASON_CHARS=200
readonly MANIFEST_ENTRY_NAME="agent-os-chatgpt-package-manifest.json"

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

# Cleanup policy:
#   - An operator-supplied --worktree-root is never removed: it is not this
#     command's to delete, clean or dirty.
#   - A disposable worktree this command created is removed only when
#     ownership is established (its path lives under the disposable root
#     this run created) and it is verifiably clean, including untracked
#     files. Anything else -- tracked changes, untracked data, an unreadable
#     status, or a refused removal -- preserves the worktree and reports it
#     on stderr rather than discarding data this command did not create.
cleanup_worktree() {
  if [ "$WORKTREE_ROOT_PROVIDED" -eq 1 ]; then
    log "cleanup: preserved operator-supplied worktree root (not this command's to remove): $WORKTREE_ROOT"
    return 0
  fi
  if [ -z "$WORKTREE_PATH" ] || [ -z "$WORKTREE_ROOT" ]; then
    return 0
  fi
  case "$WORKTREE_PATH" in
    "$WORKTREE_ROOT"/*) : ;;
    *)
      log "cleanup: worktree path is not under the disposable root this run created; preserved without removal: $WORKTREE_PATH"
      return 0
      ;;
  esac
  if [ ! -d "$WORKTREE_PATH" ]; then
    rmdir "$WORKTREE_ROOT" >/dev/null 2>&1
    return 0
  fi
  local dirty status
  dirty="$(git -C "$WORKTREE_PATH" status --porcelain 2>/dev/null)"
  status=$?
  if [ "$status" -ne 0 ]; then
    log "cleanup: unable to verify disposable worktree cleanliness; preserved without removal: $WORKTREE_PATH"
    return 0
  fi
  if [ -n "$dirty" ]; then
    log "cleanup: disposable worktree has uncommitted or untracked changes; preserved without removal: $WORKTREE_PATH"
    return 0
  fi
  # No --force: Git re-checks for modified or untracked files and refuses,
  # so anything appearing after the status check above still survives.
  if git worktree remove "$WORKTREE_PATH" >/dev/null 2>&1; then
    rmdir "$WORKTREE_ROOT" >/dev/null 2>&1
    log "cleanup: disposable worktree removed: $WORKTREE_PATH"
  else
    log "cleanup: disposable worktree removal failed; preserved: $WORKTREE_PATH"
  fi
}
trap cleanup_worktree EXIT

# Test-only hook: sourcing this file (rather than executing it) with
# BUILD_CHATGPT_PACKAGE_TEST_ONLY=1 stops here, before any argument parsing
# or side effects, so tests can exercise cleanup_worktree() directly against
# controlled WORKTREE_PATH/WORKTREE_ROOT/WORKTREE_ROOT_PROVIDED values.
if [ "${BUILD_CHATGPT_PACKAGE_TEST_ONLY:-0}" = "1" ]; then
  return 0 2>/dev/null || exit 0
fi

# Every controlled outcome, success or failure, leaves exactly one complete
# JSON object on stdout and nothing else. Values reach the serializer through
# argv -- never through string interpolation into JSON syntax -- so a
# repository, ref, SHA, output path, worktree path, base ref, status, or
# reason containing quotes, backslashes, newlines, or shell metacharacters is
# escaped by json.dumps instead of corrupting the document.
finish() {
  local code="$1" status="$2" reason="$3"

  python3 - "$SCHEMA" "$SCHEMA_VERSION" "$status" "$REPOSITORY" "$ISSUE" \
    "$REQUESTED_REF" "$RESOLVED_REF" "$RESOLVED_SHA" "$BASE_REF" "$BASE_SHA" \
    "$CHECKOUT_MODE" "$WORKING_TREE_CLEAN" "$PACKAGE_FORMAT" \
    "$INCLUDED_GIT_METADATA" "$FILE_COUNT" "$ARCHIVE_SHA256" "$COMMAND_VERSION" \
    "$OUTPUT" "$reason" "$MAX_REASON_CHARS" \
    ${SIDE_EFFECTS[@]+"${SIDE_EFFECTS[@]}"} <<'PYEOF'
import json
import sys

(schema, schema_version, status, repository, issue, requested_ref, resolved_ref,
 resolved_sha, base_ref, base_sha, checkout_mode, working_tree_clean,
 package_format, included_git_metadata, file_count, archive_sha256,
 command_version, output_path, reason, max_reason_chars,
 *side_effects) = sys.argv[1:]


def bounded(text, limit):
    """Drop control characters and cap length. Quotes and backslashes are kept
    verbatim: escaping them is the serializer's job, not a lossy pre-pass's."""
    return "".join(ch for ch in text if ch >= " " and ch != "\x7f")[:limit]


evidence = {
    "schema_name": schema,
    "schema_version": schema_version,
    "status": status,
    "repository": repository,
    "issue_number": int(issue) if issue.isdigit() else None,
    "requested_ref": requested_ref,
    "resolved_ref": resolved_ref,
    "resolved_sha": resolved_sha,
    "base_ref": base_ref,
    "base_sha": base_sha,
    "checkout_mode": checkout_mode,
    "working_tree_clean": working_tree_clean == "true",
    "package_format": package_format,
    "included_git_metadata": included_git_metadata == "true",
    "file_count": int(file_count) if file_count.isdigit() else 0,
    "archive_sha256": archive_sha256,
    "created_by_command_version": command_version,
    "side_effects_performed": side_effects,
    "implementation_authorized": False,
    "execution_authorized": False,
    "github_writes_authorized": False,
    "merge_authorized": False,
    "output_path": output_path,
    "reason": bounded(reason, int(max_reason_chars)),
}
sys.stdout.write(json.dumps(evidence, indent=2) + "\n")
PYEOF

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
  --output <path>           Absolute output .zip path. Published atomically and
                            never replaced: any existing destination fails.
  --worktree-root <path>    Reuse an existing prepared worktree root instead of
                            a disposable one. Advanced/testing use.
  --base-ref <branch>       Base branch for base_ref/base_sha evidence.
                            Default: main.
  -h, --help                Show this help.

Statuses: built | blocked | unavailable | manual-review
Exit codes: 0 built, 2 usage, 3 dirty, 4 fetch, 5 ref missing,
6 worktree, 7 conflict, 8 base ref, 9 evidence, 10 output collision,
11 unsupported tracked Git mode (symlink, gitlink, or unknown).
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

# No destination-existence pre-check is consulted here: it would be a race
# against the later write, and it reads a dangling symlink as "absent".
# Collision is decided by the exclusive, no-replace publication below.
output_dir="$(dirname "$OUTPUT")"
[ -d "$output_dir" ] || finish "$EXIT_USAGE" blocked "--output parent directory does not exist: $output_dir"

# Bounded test-only integrity controls. Both are inert unless this explicit
# guard is set, and only the two predefined action names below are accepted --
# no command, path, or argument is ever taken from the environment. They exist
# so the drift and archive-verification regression tests execute the real
# production branches instead of standing in for them.
TEST_ACTION=""
if [ "${BUILD_CHATGPT_PACKAGE_TEST_HOOKS:-0}" = "1" ]; then
  case "${BUILD_CHATGPT_PACKAGE_TEST_ACTION:-}" in
    '') : ;;
    drift-head|tamper-archive) TEST_ACTION="$BUILD_CHATGPT_PACKAGE_TEST_ACTION" ;;
    *) finish "$EXIT_USAGE" blocked "unsupported test-only action requested" ;;
  esac
fi
readonly TEST_ACTION

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

if [ "$TEST_ACTION" = "drift-head" ]; then
  # Only a disposable worktree this run created may be written to. An
  # operator-supplied root is preserved by cleanup, so a moved HEAD would
  # outlive the run -- exactly the unbounded side effect this command forbids.
  [ "$WORKTREE_ROOT_PROVIDED" -eq 0 ] ||
    finish "$EXIT_USAGE" blocked "test-only control refuses to move an operator-supplied worktree HEAD"
  log "test-only control: moving prepared worktree HEAD back one commit before exact-head verification"
  git -C "$WORKTREE_PATH" checkout --quiet --detach HEAD~1 >/dev/null 2>&1 ||
    finish "$EXIT_EVIDENCE" unavailable "test-only control could not move the prepared worktree HEAD"
fi

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
    "$TEST_ACTION" "${EXCLUDE_PATTERNS[@]}" <<'PYEOF'
import fnmatch
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile

(worktree, output, schema, schema_version, repository, issue, requested_ref,
 resolved_ref, resolved_sha, base_ref, base_sha, checkout_mode,
 working_tree_clean, package_format, included_git_metadata,
 command_version, test_action, *exclude_patterns) = sys.argv[1:]

MANIFEST_ENTRY = "agent-os-chatgpt-package-manifest.json"

# Internal exit codes. The caller maps each back onto the command's documented
# exit codes; no new command-level exit code is introduced.
FAILED = 1
MODE_REJECTED = 3
OUTPUT_COLLISION = 4
RESERVED_PATH = 5

# Only these two Git modes describe a regular file that can be packaged.
# Everything else -- symlinks, gitlinks/submodules, and any mode Git may report
# in future -- is rejected before any read, so a symlink is never dereferenced
# and a gitlink directory is never opened as a file.
MODE_CATEGORY = {"100644": "file", "100755": "executable"}
MODE_KIND = {"120000": "symlink", "160000": "gitlink"}
UNIX_MODE = {"file": 0o644, "executable": 0o755}
FIXED_DATE_TIME = (1980, 1, 1, 0, 0, 0)


def fail(message, code=FAILED):
    print(f"build-chatgpt-checkout-package: {message}", file=sys.stderr)
    sys.exit(code)


def git(*args):
    return subprocess.run(["git", "-C", worktree, *args], capture_output=True)


def write_entry(zf, path, category, data):
    info = zipfile.ZipInfo(path, date_time=FIXED_DATE_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = UNIX_MODE[category] << 16
    zf.writestr(info, data)


def digest_entry(digest, path, category, data):
    """One [canonical_path, mode_category, byte_size, sha256(content)] tuple."""
    digest.update(path.encode("utf-8"))
    digest.update(b"\0")
    digest.update(category.encode("utf-8"))
    digest.update(b"\0")
    digest.update(str(len(data)).encode("utf-8"))
    digest.update(b"\0")
    digest.update(hashlib.sha256(data).hexdigest().encode("utf-8"))
    digest.update(b"\n")


# --- The selected commit object, not the worktree, is authoritative --------
# Re-verify that RESOLVED_SHA still names a commit, then take every packaged
# path, mode, and byte from that object. Nothing below reads a worktree file,
# so a tracked file edited after the clean-state check above can neither reach
# the archive nor change the digest the manifest records.
head = git("rev-parse", "--verify", "--quiet", f"{resolved_sha}^{{commit}}")
if head.returncode != 0 or head.stdout.decode("ascii", "replace").strip() != resolved_sha:
    fail(f"resolved commit is not present as a commit object: {resolved_sha}")

# `ls-tree` walks the commit's own tree. `ls-files` would report the index of a
# mutable worktree instead, and no mode here is resolved through a symlink.
listing = git("ls-tree", "-r", "-z", "--full-tree", resolved_sha)
if listing.returncode != 0:
    fail(f"unable to enumerate the tree of {resolved_sha}")

tracked = []
for record in listing.stdout.split(b"\0"):
    if not record:
        continue
    meta, path_bytes = record.split(b"\t", 1)
    mode, _obj_type, oid = meta.decode("ascii").split()
    tracked.append((path_bytes.decode("utf-8"), mode, oid))

# Mode inspection precedes exclusion filtering, so an unsupported entry is
# rejected even when its path matches an exclusion pattern -- a tracked symlink
# is never silently dropped where the contract says it must be refused.
rejected = [
    {"path": path, "mode": mode, "kind": MODE_KIND.get(mode, "unsupported-mode")}
    for path, mode, _oid in tracked
    if mode not in MODE_CATEGORY
]
if rejected:
    print(json.dumps({"error": "tracked_mode_rejected", "entries": rejected}))
    sys.exit(MODE_REJECTED)


def is_excluded(path):
    return any(fnmatch.fnmatch(path, pat) for pat in exclude_patterns)


included = sorted(
    (path, MODE_CATEGORY[mode], oid)
    for path, mode, oid in tracked
    if not is_excluded(path)
)
for path in sorted(p for p, _m, _o in tracked if is_excluded(p)):
    print(f"build-chatgpt-checkout-package: excluding tracked path {path}", file=sys.stderr)

# The generated manifest owns this archive pathname. A commit tracking it would
# produce two ZIP entries with the same name -- which ZIP permits and consumers
# resolve inconsistently.
if any(path == MANIFEST_ENTRY for path, _c, _o in included):
    fail(f"selected commit tracks the reserved manifest pathname: {MANIFEST_ENTRY}", RESERVED_PATH)

included_paths = [path for path, _c, _o in included]
category_by_path = {path: category for path, category, _o in included}

# One `cat-file --batch` process serves every blob read. Requests and responses
# are interleaved one object at a time, so neither pipe can fill while the other
# side waits, regardless of how many files the commit tracks.
batch = subprocess.Popen(
    ["git", "-C", worktree, "cat-file", "--batch"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
)


def read_blob(oid):
    batch.stdin.write(oid.encode("ascii") + b"\n")
    batch.stdin.flush()
    header = batch.stdout.readline().split()
    if len(header) != 3 or header[1] != b"blob":
        fail(f"object {oid} is not a readable blob in {resolved_sha}")
    size = int(header[2])
    data = batch.stdout.read(size)
    batch.stdout.read(1)
    if len(data) != size:
        fail(f"short read for blob {oid} in {resolved_sha}")
    return data


def tamper_temporary_archive(path):
    """Test-only control: rewrite the temporary archive with one payload entry's
    bytes changed, keeping every CRC valid so zipfile's own integrity check
    still passes. What must catch this is the production reopen-and-recompute
    verification below."""
    with zipfile.ZipFile(path) as zf:
        entries = [(info, zf.read(info.filename)) for info in zf.infolist()]
    changed = False
    with zipfile.ZipFile(path, "w", allowZip64=True) as zf:
        for info, data in entries:
            if not changed and info.filename != MANIFEST_ENTRY:
                data += b"tampered-by-test-control\n"
                changed = True
            zf.writestr(info, data)
    print("build-chatgpt-checkout-package: test-only control tampered with the "
          "temporary archive", file=sys.stderr)


def verify_archive(path, manifest, archive_sha256):
    """Reopen the finished archive and re-derive everything its manifest claims."""
    with zipfile.ZipFile(path) as zf:
        bad = zf.testzip()
        if bad is not None:
            fail(f"corrupt entry in archive: {bad}")
        names = zf.namelist()
        if len(names) != len(set(names)):
            fail("archive contains duplicate entry names")
        if set(names) != set(included_paths) | {MANIFEST_ENTRY}:
            fail("archive contents do not match the intended file set")
        with zf.open(MANIFEST_ENTRY) as fh:
            stored_manifest = json.load(fh)
        if stored_manifest != manifest:
            fail("stored manifest does not match computed manifest")
        verify_digest = hashlib.sha256()
        for entry_path in sorted(included_paths):
            digest_entry(
                verify_digest, entry_path, category_by_path[entry_path], zf.read(entry_path)
            )
        if verify_digest.hexdigest() != archive_sha256:
            fail("post-write archive digest does not match recorded archive_sha256")


# --- Write privately, verify, then publish with no chance of replacement ---
# The archive is built under a private 0600 temporary name in the destination
# directory and only then linked into place. os.link() never follows or
# overwrites its destination, so an existing file, directory, symlink, or
# dangling symlink fails with EEXIST and a symlink's target is left untouched.
tmp_fd, tmp_path = tempfile.mkstemp(
    dir=os.path.dirname(output) or ".",
    prefix=".agent-os-chatgpt-package.",
    suffix=".zip.tmp",
)
os.close(tmp_fd)

try:
    os.chmod(tmp_path, 0o600)

    # Each blob is read exactly once and feeds both the digest and the archive
    # entry, so the manifest SHA and the packaged bytes cannot describe
    # different content.
    digest = hashlib.sha256()
    with zipfile.ZipFile(tmp_path, "w", allowZip64=True) as zf:
        for path, category, oid in included:
            data = read_blob(oid)
            digest_entry(digest, path, category, data)
            write_entry(zf, path, category, data)
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
        write_entry(zf, MANIFEST_ENTRY, "file", manifest_bytes)

    batch.stdin.close()
    batch.wait()

    if test_action == "tamper-archive":
        tamper_temporary_archive(tmp_path)

    verify_archive(tmp_path, manifest, archive_sha256)

    try:
        os.link(tmp_path, output)
    except FileExistsError:
        print(json.dumps({"error": "output_exists", "path": output}))
        sys.exit(OUTPUT_COLLISION)
    except OSError as exc:
        fail(f"unable to publish the archive to {output}: {exc.strerror}")
finally:
    # Drops the temporary name after a successful link, and leaves nothing
    # behind on any controlled failure.
    if os.path.lexists(tmp_path):
        os.unlink(tmp_path)

print(json.dumps({"file_count": len(included), "archive_sha256": archive_sha256}))
PYEOF
)"
build_exit=$?

case "$build_exit" in
  0) : ;;
  3)
    mode_summary="$(printf '%s' "$BUILD_OUTPUT" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    data = {}
print(", ".join(
    "{path} ({kind}, mode {mode})".format(**entry) for entry in data.get("entries", [])
))
' 2>/dev/null)"
    finish "$EXIT_SYMLINK" blocked \
      "tracked entries rejected without dereferencing: $mode_summary"
    ;;
  4)
    finish "$EXIT_OUTPUT" blocked \
      "--output already exists; no replacement mode is authorized: $OUTPUT"
    ;;
  5)
    finish "$EXIT_EVIDENCE" blocked \
      "selected commit tracks the reserved manifest pathname $MANIFEST_ENTRY_NAME"
    ;;
  *)
    finish "$EXIT_EVIDENCE" unavailable "packaging or archive verification failed: see stderr above"
    ;;
esac

FILE_COUNT="$(printf '%s' "$BUILD_OUTPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin)["file_count"])')"
ARCHIVE_SHA256="$(printf '%s' "$BUILD_OUTPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin)["archive_sha256"])')"
record_side_effect "archive-written"

finish "$EXIT_OK" built \
  "exact-head package built and verified at $RESOLVED_SHA; no commit, push, PR, issue, or external write occurred"
