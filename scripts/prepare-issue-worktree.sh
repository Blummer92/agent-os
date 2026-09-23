#!/usr/bin/env bash
# Agent OS issue-to-worktree checkout preparation (operator surface).
#
# Prepares or reuses one isolated Git worktree for an explicitly supplied issue
# number and an explicitly supplied branch, tag, or exact 40-character commit
# SHA, then stops. It never implements, validates, executes, publishes, or
# authorizes anything: every authority field in its evidence stays false.
#
# It owns no lifecycle that Workflow Scheduler already owns. Locks, leases,
# quarantine, cleanup, and worktree removal remain Scheduler-owned: this command
# detects them and fails closed rather than taking them over.
#
# Documentation: scripts/prepare-issue-worktree.md
# Output/exit contract: scripts/prepare-issue-worktree-contract.md
# Policy by reference: 01_Shared_Standards/github/protected-branch-governance.md

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

readonly REMOTE="origin"
readonly SCHEMA="agent-os.issue-worktree-preparation.v1"
readonly MARKER_NAME="agent-os-issue-identity"

# Bounded fetch retry is inherited from the canonical repository-state contract
# (scripts/verify-repo-state-contract.md), not reinvented here: same variable,
# same default schedule. Tests inject "0 0" to avoid real sleeping.
readonly DEFAULT_RETRY_DELAYS="2 4"

readonly MAX_REASON_CHARS=200

log() { printf 'prepare-issue-worktree: %s\n' "$*" >&2; }

# --- Evidence state ---------------------------------------------------------

ISSUE=""
REPOSITORY=""
REQUESTED_REF=""
WORKTREE_ROOT=""
BASE_REF=""
ALLOW_BRANCH_CREATION=0
ATTACH_BRANCH=0

RESOLVED_REF=""
RESOLVED_SHA=""
CHECKOUT_MODE=""
HEAD_STATE=""
WORKTREE_PATH=""
WORKTREE_REUSED="false"
WORKING_TREE_CLEAN="false"
REMOTE_FETCH_PERFORMED="false"
BRANCH_CREATED="false"
SIDE_EFFECTS=""

# Intent flag, kept separate from the BRANCH_CREATED evidence field so no
# intermediate value can ever reach the JSON contract.
CREATE_BRANCH=0

record_side_effect() { SIDE_EFFECTS="${SIDE_EFFECTS:+$SIDE_EFFECTS }$1"; }

sanitize() {
  printf '%s' "$1" | tr -d '[:cntrl:]"\\' | cut -c "1-$MAX_REASON_CHARS"
}

json_array() {
  local first=1 item
  printf '['
  for item in $1; do
    [ "$first" -eq 1 ] || printf ', '
    printf '"%s"' "$item"
    first=0
  done
  printf ']'
}

# Single terminal exit for every path: emit bounded JSON evidence on stdout, a
# concise human summary on stderr, and exit with the mapped code.
finish() {
  local code="$1" status="$2" reason
  reason="$(sanitize "$3")"

  # Only a validated numeric issue reaches the JSON number position; a rejected
  # value is reported as null rather than corrupting the evidence contract.
  local issue_json="null"
  case "$ISSUE" in
    ''|*[!0-9]*) : ;;
    *) issue_json="$ISSUE" ;;
  esac

  printf '{\n'
  printf '  "schema": "%s",\n' "$SCHEMA"
  printf '  "status": "%s",\n' "$status"
  printf '  "issue_number": %s,\n' "$issue_json"
  printf '  "repository": "%s",\n' "$REPOSITORY"
  printf '  "requested_ref": "%s",\n' "$REQUESTED_REF"
  printf '  "resolved_ref": "%s",\n' "$RESOLVED_REF"
  printf '  "resolved_sha": "%s",\n' "$RESOLVED_SHA"
  printf '  "checkout_mode": "%s",\n' "$CHECKOUT_MODE"
  printf '  "head_state": "%s",\n' "$HEAD_STATE"
  printf '  "worktree_path": "%s",\n' "$WORKTREE_PATH"
  printf '  "worktree_reused": %s,\n' "$WORKTREE_REUSED"
  printf '  "working_tree_clean": %s,\n' "$WORKING_TREE_CLEAN"
  printf '  "remote_fetch_performed": %s,\n' "$REMOTE_FETCH_PERFORMED"
  printf '  "branch_created": %s,\n' "$BRANCH_CREATED"
  printf '  "side_effects_performed": %s,\n' "$(json_array "$SIDE_EFFECTS")"
  printf '  "repository_implementation_authorized": false,\n'
  printf '  "execution_authorized": false,\n'
  printf '  "github_writes_authorized": false,\n'
  printf '  "merge_authorized": false,\n'
  printf '  "reason": "%s"\n' "$reason"
  printf '}\n'

  log "STATUS=$status issue=${ISSUE:-none} mode=${CHECKOUT_MODE:-none} sha=${RESOLVED_SHA:-none} path=${WORKTREE_PATH:-none}"
  log "reason: $reason"
  exit "$code"
}

usage() {
  cat >&2 <<'USAGE'
Usage: scripts/prepare-issue-worktree.sh --issue <n> --repository <owner/name>
         --ref <branch|tag|sha40> --worktree-root <absolute path>
         [--attach-branch] [--allow-branch-creation --base-ref <branch>]

Prepares or reuses one isolated worktree at <worktree-root>/issue-<n> for the
exact supplied ref. Checkout-only by default: HEAD is detached at the resolved
commit so validation evidence is reproducible.

Options:
  --issue <n>               Agent OS issue number. Required.
  --repository <owner/name> Expected repository identity of origin. Required.
  --ref <ref>               Existing branch, tag, or exact lowercase
                            40-character commit SHA. Never inferred. Required.
  --worktree-root <path>    Absolute worktree root, e.g. ~/agent-os-worktrees.
  --attach-branch           Check the existing local branch out attached
                            instead of detaching at its exact commit.
  --allow-branch-creation   Permit creating <ref> from origin/<base-ref> when it
                            exists neither locally nor on origin. Local only.
  --base-ref <branch>       Base for --allow-branch-creation. Not valid alone.
  -h, --help                Show this help.

Statuses: prepared | already-prepared | manual-review | blocked | unavailable
Exit codes: 0 prepared/already-prepared, 2 usage, 3 dirty, 4 fetch,
5 ref missing, 6 worktree operation, 7 conflict, 8 base ref, 9 evidence.

Preparation success never implies implementation, execution, validation,
review, merge, or issue-completion authority.
USAGE
}

# --- Argument parsing (before any repository or filesystem mutation) --------

require_value() {
  [ "$2" -ge 2 ] || { usage; finish "$EXIT_USAGE" blocked "$1 requires a value"; }
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --issue) require_value "$1" "$#"; ISSUE="$2"; shift 2 ;;
    --repository) require_value "$1" "$#"; REPOSITORY="$2"; shift 2 ;;
    --ref) require_value "$1" "$#"; REQUESTED_REF="$2"; shift 2 ;;
    --worktree-root) require_value "$1" "$#"; WORKTREE_ROOT="$2"; shift 2 ;;
    --base-ref) require_value "$1" "$#"; BASE_REF="$2"; shift 2 ;;
    --allow-branch-creation) ALLOW_BRANCH_CREATION=1; shift ;;
    --attach-branch) ATTACH_BRANCH=1; shift ;;
    -h|--help) usage; exit "$EXIT_OK" ;;
    *) usage; finish "$EXIT_USAGE" blocked "unexpected argument: $1" ;;
  esac
done

[ -n "$ISSUE" ] || { usage; finish "$EXIT_USAGE" blocked "--issue is required"; }
case "$ISSUE" in
  ''|*[!0-9]*|0*) finish "$EXIT_USAGE" blocked "--issue must be a positive integer: $ISSUE" ;;
esac
[ "${#ISSUE}" -le 9 ] || finish "$EXIT_USAGE" blocked "--issue is out of range: $ISSUE"

[ -n "$REPOSITORY" ] || { usage; finish "$EXIT_USAGE" blocked "--repository is required"; }
case "$REPOSITORY" in
  */*/*|/*|*/) finish "$EXIT_USAGE" blocked "--repository must be owner/name: $REPOSITORY" ;;
  */*) : ;;
  *) finish "$EXIT_USAGE" blocked "--repository must be owner/name: $REPOSITORY" ;;
esac
case "$REPOSITORY" in
  *[!A-Za-z0-9._/-]*) finish "$EXIT_USAGE" blocked "--repository contains unsupported characters: $REPOSITORY" ;;
esac

[ -n "$REQUESTED_REF" ] || { usage; finish "$EXIT_USAGE" blocked "--ref is required"; }
case "$REQUESTED_REF" in
  -*) finish "$EXIT_USAGE" blocked "--ref must not begin with '-': $REQUESTED_REF" ;;
  refs/*) finish "$EXIT_USAGE" blocked "--ref must be a short name, not a refs/ path: $REQUESTED_REF" ;;
esac

is_exact_sha=0
case "$REQUESTED_REF" in
  *[!0-9a-f]*) : ;;
  *) [ "${#REQUESTED_REF}" -eq 40 ] && is_exact_sha=1 ;;
esac
if [ "$is_exact_sha" -eq 0 ]; then
  # Abbreviated or uppercase hex is rejected as a SHA rather than silently
  # retried as a ref name: exact-SHA preparation must be unambiguous.
  case "$REQUESTED_REF" in
    *[!0-9A-Fa-f]*) : ;;
    *)
      if [ "${#REQUESTED_REF}" -ge 7 ]; then
        finish "$EXIT_USAGE" blocked \
          "--ref looks like a commit SHA but is not exactly 40 lowercase hex characters: $REQUESTED_REF"
      fi
      ;;
  esac
  git check-ref-format "refs/heads/$REQUESTED_REF" >/dev/null 2>&1 ||
    finish "$EXIT_USAGE" blocked "--ref is not a valid Git ref name: $REQUESTED_REF"
fi

[ -n "$WORKTREE_ROOT" ] || { usage; finish "$EXIT_USAGE" blocked "--worktree-root is required"; }
case "$WORKTREE_ROOT" in
  /*) : ;;
  *) finish "$EXIT_USAGE" blocked "--worktree-root must be an absolute path: $WORKTREE_ROOT" ;;
esac
case "$WORKTREE_ROOT" in
  *[!A-Za-z0-9._/+=@:-]*) finish "$EXIT_USAGE" blocked "--worktree-root contains unsupported characters: $WORKTREE_ROOT" ;;
esac
case "/$WORKTREE_ROOT/" in
  */../*) finish "$EXIT_USAGE" blocked "--worktree-root must not contain '..': $WORKTREE_ROOT" ;;
esac
WORKTREE_ROOT="${WORKTREE_ROOT%/}"
[ -n "$WORKTREE_ROOT" ] || finish "$EXIT_USAGE" blocked "--worktree-root must not be the filesystem root"

if [ "$ALLOW_BRANCH_CREATION" -eq 1 ]; then
  [ -n "$BASE_REF" ] ||
    finish "$EXIT_USAGE" blocked "--allow-branch-creation requires --base-ref"
  [ "$is_exact_sha" -eq 0 ] ||
    finish "$EXIT_USAGE" blocked "--allow-branch-creation is not valid for an exact SHA"
  git check-ref-format "refs/heads/$BASE_REF" >/dev/null 2>&1 ||
    finish "$EXIT_USAGE" blocked "--base-ref is not a valid Git branch name: $BASE_REF"
  ATTACH_BRANCH=1
elif [ -n "$BASE_REF" ]; then
  finish "$EXIT_USAGE" blocked "--base-ref is only valid with --allow-branch-creation"
fi

if [ "$ATTACH_BRANCH" -eq 1 ] && [ "$is_exact_sha" -eq 1 ]; then
  finish "$EXIT_USAGE" blocked "--attach-branch is not valid for an exact SHA"
fi

RETRY_DELAYS="${VERIFY_REPO_STATE_RETRY_DELAYS-$DEFAULT_RETRY_DELAYS}"
for delay in $RETRY_DELAYS; do
  case "$delay" in
    ''|*[!0-9.]*) finish "$EXIT_USAGE" blocked "invalid retry delay: $delay" ;;
  esac
done

# --- Repository preconditions ----------------------------------------------
# This command never clones and never discovers a repository: it must already be
# run from inside the intended Agent OS checkout.

git rev-parse --is-inside-work-tree >/dev/null 2>&1 ||
  finish "$EXIT_USAGE" blocked "not inside a Git work tree; this command never clones or discovers a repository"

origin_url="$(git remote get-url "$REMOTE" 2>/dev/null)" ||
  finish "$EXIT_USAGE" blocked "remote '$REMOTE' is not configured"

derive_repository_identity() {
  local url="${1%/}" name rest owner
  url="${url%.git}"
  name="${url##*/}"
  rest="${url%/*}"
  case "$rest" in *:*) rest="${rest##*:}" ;; esac
  owner="${rest##*/}"
  printf '%s/%s' "$owner" "$name"
}

actual_repository="$(derive_repository_identity "$origin_url")"
[ "$actual_repository" = "$REPOSITORY" ] ||
  finish "$EXIT_CONFLICT" manual-review \
    "repository identity drift: origin resolves to '$actual_repository', not '$REPOSITORY'"

primary_root="$(git rev-parse --show-toplevel 2>/dev/null)" ||
  finish "$EXIT_USAGE" blocked "unable to resolve the primary work tree"

# --- Target path validation (no filesystem mutation yet) -------------------

WORKTREE_PATH="$WORKTREE_ROOT/issue-$ISSUE"

[ ! -L "$WORKTREE_ROOT" ] ||
  finish "$EXIT_CONFLICT" manual-review "--worktree-root is a symlink: $WORKTREE_ROOT"
[ ! -L "$WORKTREE_PATH" ] ||
  finish "$EXIT_CONFLICT" manual-review "target worktree path is a symlink: $WORKTREE_PATH"

if [ -e "$WORKTREE_ROOT" ]; then
  [ -d "$WORKTREE_ROOT" ] ||
    finish "$EXIT_CONFLICT" manual-review "--worktree-root exists and is not a directory: $WORKTREE_ROOT"
  physical_root="$(cd "$WORKTREE_ROOT" 2>/dev/null && pwd -P)" ||
    finish "$EXIT_CONFLICT" manual-review "--worktree-root is not readable: $WORKTREE_ROOT"
  [ "$physical_root" = "$WORKTREE_ROOT" ] ||
    finish "$EXIT_CONFLICT" manual-review \
      "--worktree-root resolves through a symlink to $physical_root"
fi

case "$primary_root/" in
  "$WORKTREE_PATH"/*) finish "$EXIT_CONFLICT" manual-review \
    "target path contains the primary checkout; the shared checkout is never switched or reused" ;;
esac
[ "$primary_root" != "$WORKTREE_PATH" ] ||
  finish "$EXIT_CONFLICT" manual-review \
    "target path is the primary checkout; the shared checkout is never switched or reused"

# --- Existing worktree inspection (read-only) ------------------------------

wt_list="$(git worktree list --porcelain 2>/dev/null)" ||
  finish "$EXIT_WORKTREE" unavailable "unable to list existing worktrees"

worktree_block() {
  printf '%s\n' "$wt_list" | awk -v target="$1" '
    /^worktree / { inblock = (substr($0, 10) == target) }
    inblock { print }
  '
}

worktree_claiming_branch() {
  printf '%s\n' "$wt_list" | awk -v want="$1" '
    /^worktree / { current = substr($0, 10) }
    $0 == ("branch " want) { print current; exit }
  '
}

block_value() {
  printf '%s\n' "$1" | awk -v key="$2" '$1 == key { $1 = ""; sub(/^ /, ""); print; exit }'
}

target_block="$(worktree_block "$WORKTREE_PATH")"
registered=0
[ -n "$target_block" ] && registered=1

if [ "$registered" -eq 1 ]; then
  locked_line="$(printf '%s\n' "$target_block" | grep -E '^locked( |$)' || true)"
  [ -z "$locked_line" ] ||
    finish "$EXIT_CONFLICT" manual-review \
      "existing worktree is locked and locks are never taken over: ${locked_line#locked }"

  prunable_line="$(printf '%s\n' "$target_block" | grep -E '^prunable( |$)' || true)"
  [ -z "$prunable_line" ] ||
    finish "$EXIT_CONFLICT" manual-review \
      "existing worktree metadata is stale/prunable; hand off to Workflow Scheduler cleanup: ${prunable_line#prunable }"

  [ -d "$WORKTREE_PATH" ] ||
    finish "$EXIT_CONFLICT" manual-review \
      "worktree is registered but its path is missing; hand off to Workflow Scheduler cleanup: $WORKTREE_PATH"

  dirty="$(git -C "$WORKTREE_PATH" status --porcelain --untracked-files=no 2>/dev/null)" ||
    finish "$EXIT_WORKTREE" unavailable "unable to read status of $WORKTREE_PATH"
  if [ -n "$dirty" ]; then
    log "uncommitted tracked changes in $WORKTREE_PATH; refusing to reuse or modify it"
    printf '%s\n' "$dirty" >&2
    finish "$EXIT_DIRTY" blocked "existing worktree has uncommitted tracked changes; no work is discarded"
  fi
  WORKING_TREE_CLEAN="true"

  untracked="$(git -C "$WORKTREE_PATH" status --porcelain --untracked-files=normal 2>/dev/null | grep '^??' || true)"
  if [ -n "$untracked" ]; then
    log "NOTE: untracked files present in $WORKTREE_PATH (not blocking, not modified)"
  fi
elif [ -e "$WORKTREE_PATH" ]; then
  finish "$EXIT_CONFLICT" manual-review \
    "target path already exists but is not a registered worktree of this repository: $WORKTREE_PATH"
fi

# --- Fetch: the one bounded, explicit network operation --------------------

fetch_with_retry() {
  local attempt=1 delay
  if GIT_TERMINAL_PROMPT=0 git fetch --prune --tags "$REMOTE" >&2; then
    return 0
  fi
  for delay in $RETRY_DELAYS; do
    attempt=$((attempt + 1))
    log "WARN: fetch attempt $((attempt - 1)) failed; retrying in ${delay}s"
    sleep "$delay"
    if GIT_TERMINAL_PROMPT=0 git fetch --prune --tags "$REMOTE" >&2; then
      return 0
    fi
  done
  log "fetch failed after $attempt attempt(s)"
  return 1
}

log "fetching $REMOTE (prune, tags)"
if fetch_with_retry; then
  REMOTE_FETCH_PERFORMED="true"
else
  finish "$EXIT_FETCH" unavailable \
    "unable to fetch $REMOTE after bounded retries; this is remote unavailability, not a missing ref"
fi

# --- Ref resolution from local refs only (no second network operation) -----

has_ref() { git show-ref --verify --quiet "$1"; }

refspec_is_complete() {
  git config --get-all "remote.$REMOTE.fetch" 2>/dev/null |
    grep -qx "+\?refs/heads/\*:refs/remotes/$REMOTE/\*"
}

local_ref="refs/heads/$REQUESTED_REF"
remote_ref="refs/remotes/$REMOTE/$REQUESTED_REF"
tag_ref="refs/tags/$REQUESTED_REF"

if [ "$is_exact_sha" -eq 1 ]; then
  git cat-file -e "$REQUESTED_REF^{commit}" 2>/dev/null ||
    finish "$EXIT_REF_MISSING" blocked "exact SHA is not a commit in this repository: $REQUESTED_REF"
  CHECKOUT_MODE="detached-sha"
  RESOLVED_REF="$REQUESTED_REF"
  RESOLVED_SHA="$REQUESTED_REF"
else
  has_local=0; has_remote=0; has_tag=0
  has_ref "$local_ref" && has_local=1
  has_ref "$remote_ref" && has_remote=1
  has_ref "$tag_ref" && has_tag=1

  if [ "$has_tag" -eq 1 ] && { [ "$has_local" -eq 1 ] || [ "$has_remote" -eq 1 ]; }; then
    finish "$EXIT_CONFLICT" manual-review \
      "ambiguous target: '$REQUESTED_REF' exists as both a branch and a tag"
  fi

  if [ "$has_tag" -eq 1 ]; then
    CHECKOUT_MODE="tag"
    RESOLVED_REF="$tag_ref"
    RESOLVED_SHA="$(git rev-parse --verify --quiet "$tag_ref^{commit}")" ||
      finish "$EXIT_REF_MISSING" blocked "tag does not resolve to a commit: $REQUESTED_REF"
    [ "$ATTACH_BRANCH" -eq 0 ] ||
      finish "$EXIT_USAGE" blocked "--attach-branch is not valid for a tag: $REQUESTED_REF"
  elif [ "$has_local" -eq 1 ] || [ "$has_remote" -eq 1 ]; then
    CHECKOUT_MODE="branch"
    if [ "$has_local" -eq 1 ] && [ "$has_remote" -eq 1 ]; then
      local_sha="$(git rev-parse --verify --quiet "$local_ref")"
      remote_sha="$(git rev-parse --verify --quiet "$remote_ref")"
      [ "$local_sha" = "$remote_sha" ] ||
        finish "$EXIT_CONFLICT" manual-review \
          "local and $REMOTE copies of '$REQUESTED_REF' disagree; reconcile with scripts/verify-repo-state.sh first"
      RESOLVED_REF="$local_ref"
      RESOLVED_SHA="$local_sha"
    elif [ "$has_local" -eq 1 ]; then
      RESOLVED_REF="$local_ref"
      RESOLVED_SHA="$(git rev-parse --verify --quiet "$local_ref")"
    else
      [ "$ATTACH_BRANCH" -eq 0 ] ||
        finish "$EXIT_REF_MISSING" blocked \
          "'$REQUESTED_REF' exists only on $REMOTE; attaching it would create a local branch. Use the default detached mode."
      RESOLVED_REF="$remote_ref"
      RESOLVED_SHA="$(git rev-parse --verify --quiet "$remote_ref")"
    fi
  else
    if ! refspec_is_complete; then
      finish "$EXIT_REF_MISSING" blocked \
        "remote-tracking refs are incomplete (restricted remote.$REMOTE.fetch); absence of '$REQUESTED_REF' is not proof it is missing"
    fi
    if [ "$ALLOW_BRANCH_CREATION" -eq 0 ]; then
      finish "$EXIT_REF_MISSING" blocked \
        "'$REQUESTED_REF' does not exist as a local branch, $REMOTE branch, or tag; refs are never inferred"
    fi
    base_remote_ref="refs/remotes/$REMOTE/$BASE_REF"
    has_ref "$base_remote_ref" ||
      finish "$EXIT_BASE" blocked "cannot create '$REQUESTED_REF': base ref $REMOTE/$BASE_REF does not exist"
    CHECKOUT_MODE="branch"
    RESOLVED_REF="$local_ref"
    RESOLVED_SHA="$(git rev-parse --verify --quiet "$base_remote_ref")"
    CREATE_BRANCH=1
  fi
fi

[ -n "$RESOLVED_SHA" ] ||
  finish "$EXIT_EVIDENCE" unavailable "unable to resolve an exact commit for '$REQUESTED_REF'"

if [ "$ATTACH_BRANCH" -eq 1 ]; then
  HEAD_STATE="attached"
else
  HEAD_STATE="detached"
fi

# --- Idempotent reuse, or fail closed on any identity conflict -------------

marker_path=""
if [ "$registered" -eq 1 ]; then
  admin_dir="$(git -C "$WORKTREE_PATH" rev-parse --absolute-git-dir 2>/dev/null)" ||
    finish "$EXIT_WORKTREE" unavailable "unable to resolve worktree metadata for $WORKTREE_PATH"
  marker_path="$admin_dir/$MARKER_NAME"

  [ -f "$marker_path" ] ||
    finish "$EXIT_CONFLICT" manual-review \
      "existing worktree carries no Agent OS identity record; reuse requires exact identity proof"

  marker_field() {
    awk -F= -v key="$1" '$1 == key { sub(/^[^=]*=/, ""); print; exit }' "$marker_path"
  }
  prior_issue="$(marker_field issue_number)"
  prior_repository="$(marker_field repository)"
  prior_requested_ref="$(marker_field requested_ref)"
  prior_resolved_ref="$(marker_field resolved_ref)"
  prior_resolved_sha="$(marker_field resolved_sha)"
  prior_mode="$(marker_field checkout_mode)"
  prior_head_state="$(marker_field head_state)"

  [ "$prior_issue" = "$ISSUE" ] ||
    finish "$EXIT_CONFLICT" manual-review \
      "worktree path is owned by issue #$prior_issue, not #$ISSUE"
  [ "$prior_repository" = "$REPOSITORY" ] ||
    finish "$EXIT_CONFLICT" manual-review \
      "worktree was prepared for repository '$prior_repository', not '$REPOSITORY'"

  actual_head="$(git -C "$WORKTREE_PATH" rev-parse HEAD 2>/dev/null)" ||
    finish "$EXIT_WORKTREE" unavailable "unable to read HEAD of $WORKTREE_PATH"
  [ "$actual_head" = "$prior_resolved_sha" ] ||
    finish "$EXIT_CONFLICT" manual-review \
      "worktree HEAD $actual_head no longer matches its recorded identity $prior_resolved_sha"

  actual_head_state="detached"
  git -C "$WORKTREE_PATH" symbolic-ref --quiet HEAD >/dev/null 2>&1 && actual_head_state="attached"
  [ "$actual_head_state" = "$prior_head_state" ] ||
    finish "$EXIT_CONFLICT" manual-review \
      "worktree HEAD state '$actual_head_state' no longer matches its recorded state '$prior_head_state'"

  if [ "$prior_requested_ref" = "$REQUESTED_REF" ] &&
     [ "$prior_resolved_ref" = "$RESOLVED_REF" ] &&
     [ "$prior_resolved_sha" = "$RESOLVED_SHA" ] &&
     [ "$prior_mode" = "$CHECKOUT_MODE" ] &&
     [ "$prior_head_state" = "$HEAD_STATE" ]; then
    WORKTREE_REUSED="true"
    finish "$EXIT_OK" already-prepared \
      "worktree already prepared at the exact requested identity; nothing was modified"
  fi

  finish "$EXIT_CONFLICT" manual-review \
    "issue #$ISSUE is already prepared at ${prior_requested_ref}@${prior_resolved_sha}; the new request conflicts"
fi

# --- Branch claim checks (before any mutation) -----------------------------

if [ "$ATTACH_BRANCH" -eq 1 ]; then
  claiming="$(worktree_claiming_branch "$local_ref")"
  [ -z "$claiming" ] ||
    finish "$EXIT_CONFLICT" manual-review \
      "branch '$REQUESTED_REF' is already checked out at $claiming; one branch is never claimed by two worktrees"
fi

if [ "$CREATE_BRANCH" -eq 1 ]; then
  # Creation is only reachable when the branch exists neither locally nor on
  # origin; re-prove it here so a race cannot turn creation into a claim.
  has_ref "$local_ref" &&
    finish "$EXIT_CONFLICT" manual-review "branch '$REQUESTED_REF' appeared locally; creation is not applicable"
  has_ref "$remote_ref" &&
    finish "$EXIT_CONFLICT" manual-review "branch '$REQUESTED_REF' appeared on $REMOTE; creation is not applicable"
fi

# --- Worktree creation ------------------------------------------------------

if [ ! -d "$WORKTREE_ROOT" ]; then
  mkdir -p "$WORKTREE_ROOT" ||
    finish "$EXIT_WORKTREE" unavailable "unable to create worktree root: $WORKTREE_ROOT"
  record_side_effect "worktree-root-created"
fi

if [ "$CREATE_BRANCH" -eq 1 ]; then
  log "creating branch '$REQUESTED_REF' from $REMOTE/$BASE_REF in a new worktree; nothing is pushed"
  git worktree add --no-track -b "$REQUESTED_REF" "$WORKTREE_PATH" "refs/remotes/$REMOTE/$BASE_REF" >&2 ||
    finish "$EXIT_WORKTREE" blocked "failed to create worktree with new branch '$REQUESTED_REF'"
  BRANCH_CREATED="true"
  record_side_effect "branch-created"
elif [ "$ATTACH_BRANCH" -eq 1 ]; then
  log "preparing attached worktree for branch '$REQUESTED_REF' at $RESOLVED_SHA"
  git worktree add "$WORKTREE_PATH" "$REQUESTED_REF" >&2 ||
    finish "$EXIT_WORKTREE" blocked "failed to prepare attached worktree for '$REQUESTED_REF'"
else
  log "preparing detached worktree at exact commit $RESOLVED_SHA"
  git worktree add --detach "$WORKTREE_PATH" "$RESOLVED_SHA" >&2 ||
    finish "$EXIT_WORKTREE" blocked "failed to prepare detached worktree at $RESOLVED_SHA"
fi
record_side_effect "worktree-created"

# --- Post-creation verification and identity record ------------------------

head_sha="$(git -C "$WORKTREE_PATH" rev-parse HEAD 2>/dev/null)" ||
  finish "$EXIT_EVIDENCE" unavailable "unable to read HEAD of the prepared worktree"
[ "$head_sha" = "$RESOLVED_SHA" ] ||
  finish "$EXIT_EVIDENCE" manual-review \
    "prepared worktree HEAD $head_sha does not match the resolved commit $RESOLVED_SHA"

actual_head_state="detached"
git -C "$WORKTREE_PATH" symbolic-ref --quiet HEAD >/dev/null 2>&1 && actual_head_state="attached"
[ "$actual_head_state" = "$HEAD_STATE" ] ||
  finish "$EXIT_EVIDENCE" manual-review \
    "prepared worktree HEAD state '$actual_head_state' does not match the requested state '$HEAD_STATE'"

post_dirty="$(git -C "$WORKTREE_PATH" status --porcelain --untracked-files=no 2>/dev/null)" ||
  finish "$EXIT_EVIDENCE" unavailable "unable to read status of the prepared worktree"
if [ -z "$post_dirty" ]; then
  WORKING_TREE_CLEAN="true"
else
  WORKING_TREE_CLEAN="false"
fi

admin_dir="$(git -C "$WORKTREE_PATH" rev-parse --absolute-git-dir 2>/dev/null)" ||
  finish "$EXIT_EVIDENCE" unavailable "unable to resolve metadata of the prepared worktree"
marker_path="$admin_dir/$MARKER_NAME"
{
  printf 'issue_number=%s\n' "$ISSUE"
  printf 'repository=%s\n' "$REPOSITORY"
  printf 'requested_ref=%s\n' "$REQUESTED_REF"
  printf 'resolved_ref=%s\n' "$RESOLVED_REF"
  printf 'resolved_sha=%s\n' "$RESOLVED_SHA"
  printf 'checkout_mode=%s\n' "$CHECKOUT_MODE"
  printf 'head_state=%s\n' "$HEAD_STATE"
} > "$marker_path" ||
  finish "$EXIT_EVIDENCE" manual-review \
    "worktree was created but its identity record could not be written; nothing was removed"
record_side_effect "identity-marker-written"

finish "$EXIT_OK" prepared "worktree prepared at $RESOLVED_SHA; no implementation, execution, or GitHub authority is granted"
