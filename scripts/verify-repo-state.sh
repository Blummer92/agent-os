#!/usr/bin/env bash
# Agent OS reusable repository-state verifier.
#
# Replaces the Git preflight block that was previously pasted into prompts.
# Read-only with respect to remotes: it fetches, switches, and fast-forwards
# locally, and never pushes, resets, stashes, cleans, or force-updates.
#
# Documentation: scripts/verify-repo-state.md
# Policy by reference: 01_Shared_Standards/github/protected-branch-governance.md

set -euo pipefail

readonly EXIT_OK=0
readonly EXIT_USAGE=2
readonly EXIT_DIRTY=3
readonly EXIT_FETCH=4
readonly EXIT_BRANCH_MISSING=5
readonly EXIT_SWITCH=6
readonly EXIT_FAST_FORWARD=7
readonly EXIT_BASE=8
readonly EXIT_EVIDENCE=9

readonly REMOTE="origin"
readonly DEFAULT_BASE="main"

# Retry schedule for the one genuinely transient operation (fetch).
# The list itself is the configuration: attempts == items + 1, so there is no
# unreachable cap constant. Tests inject "0 0" to avoid real sleeping.
readonly DEFAULT_RETRY_DELAYS="2 4"

log() { printf 'verify-repo-state: %s\n' "$*" >&2; }
die() { log "ERROR: $2"; exit "$1"; }

usage() {
  cat >&2 <<'USAGE'
Usage: scripts/verify-repo-state.sh [--create-from-base] <branch> [base]

Verifies that the repository is on <branch>, fast-forwarded to
origin/<branch>, with no uncommitted tracked changes, then prints
repository-state evidence to stdout.

Arguments:
  <branch>              Target branch (short name, no refs/ prefix).
  [base]                Base branch for changed-file evidence. Default: main.

Options:
  --create-from-base    Permit creating <branch> from origin/<base> when it
                        does not exist locally or on origin. Local only:
                        nothing is pushed.
  -h, --help            Show this help.

Exit codes:
  0 success                     2 invalid arguments
  3 uncommitted tracked changes 4 fetch failed after retries
  5 branch missing              6 branch switch failed
  7 fast-forward failed         8 base ref unusable
  9 evidence generation failed
USAGE
}

# --- Argument validation (runs before any repository state changes) ---------

BRANCH=""
BASE=""
CREATE_FROM_BASE=0
branch_set=0
base_set=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --create-from-base) CREATE_FROM_BASE=1 ;;
    -h|--help) usage; exit "$EXIT_OK" ;;
    --) shift; break ;;
    -*) usage; die "$EXIT_USAGE" "unknown option: $1" ;;
    *)
      if [ "$branch_set" -eq 0 ]; then
        BRANCH="$1"; branch_set=1
      elif [ "$base_set" -eq 0 ]; then
        BASE="$1"; base_set=1
      else
        usage; die "$EXIT_USAGE" "unexpected extra argument: $1"
      fi
      ;;
  esac
  shift
done

# Any operands after `--` are still positional.
while [ "$#" -gt 0 ]; do
  if [ "$branch_set" -eq 0 ]; then
    BRANCH="$1"; branch_set=1
  elif [ "$base_set" -eq 0 ]; then
    BASE="$1"; base_set=1
  else
    usage; die "$EXIT_USAGE" "unexpected extra argument: $1"
  fi
  shift
done

[ "$branch_set" -eq 1 ] || { usage; die "$EXIT_USAGE" "a target branch is required"; }
[ "$base_set" -eq 1 ] || BASE="$DEFAULT_BASE"

validate_branch_name() {
  local name="$1" label="$2"
  [ -n "$name" ] || die "$EXIT_USAGE" "$label must not be empty"
  case "$name" in
    -*) die "$EXIT_USAGE" "$label must not begin with '-': $name" ;;
    refs/*) die "$EXIT_USAGE" "$label must be a short name, not a refs/ path: $name" ;;
  esac
  # Full ref form avoids the @{-1} style expansion that --branch performs.
  git check-ref-format "refs/heads/$name" >/dev/null 2>&1 ||
    die "$EXIT_USAGE" "$label is not a valid Git branch name: $name"
}

validate_branch_name "$BRANCH" "target branch"
validate_branch_name "$BASE" "base branch"

RETRY_DELAYS="${VERIFY_REPO_STATE_RETRY_DELAYS-$DEFAULT_RETRY_DELAYS}"
for delay in $RETRY_DELAYS; do
  case "$delay" in
    ''|*[!0-9.]*) die "$EXIT_USAGE" "invalid retry delay: $delay" ;;
  esac
done

git rev-parse --is-inside-work-tree >/dev/null 2>&1 ||
  die "$EXIT_USAGE" "not inside a Git work tree"
git remote get-url "$REMOTE" >/dev/null 2>&1 ||
  die "$EXIT_USAGE" "remote '$REMOTE' is not configured"

# --- Dirty-tree gate --------------------------------------------------------
# Blocks uncommitted tracked changes only. Untracked files are reported but not
# blocking; ignored files are permitted and never inspected. Gate and diagnostic
# use identical --untracked-files=no semantics. Never discards user work.

tracked_changes="$(git status --porcelain --untracked-files=no)"
if [ -n "$tracked_changes" ]; then
  log "uncommitted tracked changes present; refusing to modify repository state"
  git status --short --untracked-files=no >&2
  exit "$EXIT_DIRTY"
fi

untracked="$(git status --porcelain --untracked-files=normal | grep '^??' || true)"
if [ -n "$untracked" ]; then
  log "NOTE: untracked files present (not blocking, not modified):"
  printf '%s\n' "$untracked" >&2
fi

# --- Fetch (the only retried operation) ------------------------------------

fetch_with_retry() {
  local attempt=1 delay
  if GIT_TERMINAL_PROMPT=0 git fetch --prune "$REMOTE" >&2; then
    return 0
  fi
  for delay in $RETRY_DELAYS; do
    attempt=$((attempt + 1))
    log "WARN: fetch attempt $((attempt - 1)) failed; retrying in ${delay}s"
    sleep "$delay"
    if GIT_TERMINAL_PROMPT=0 git fetch --prune "$REMOTE" >&2; then
      return 0
    fi
  done
  log "fetch failed after $attempt attempt(s)"
  return 1
}

log "fetching $REMOTE (prune)"
fetch_with_retry || die "$EXIT_FETCH" "unable to fetch $REMOTE; remote may be unreachable"

# --- Ref resolution from local refs only (no second network operation) -----

local_ref="refs/heads/$BRANCH"
remote_ref="refs/remotes/$REMOTE/$BRANCH"
base_remote_ref="refs/remotes/$REMOTE/$BASE"

has_ref() { git show-ref --verify --quiet "$1"; }

# A restricted (single-branch) fetch refspec means remote-tracking refs are
# incomplete. Absence of a ref then reflects local configuration, not remote
# reality, and must not be reported as "branch does not exist".
refspec_is_complete() {
  git config --get-all "remote.$REMOTE.fetch" 2>/dev/null |
    grep -qx "+\?refs/heads/\*:refs/remotes/$REMOTE/\*"
}

require_complete_refspec() {
  refspec_is_complete && return 0
  log "remote-tracking refs are incomplete: remote.$REMOTE.fetch is restricted to"
  git config --get-all "remote.$REMOTE.fetch" 2>/dev/null | sed 's/^/  /' >&2
  log "re-clone without --single-branch, or widen the refspec, before verifying"
  return 1
}

has_local=0; has_remote=0
if has_ref "$local_ref"; then has_local=1; fi
if has_ref "$remote_ref"; then has_remote=1; fi

if [ "$has_local" -eq 0 ] && [ "$has_remote" -eq 0 ]; then
  require_complete_refspec || exit "$EXIT_BRANCH_MISSING"
  if [ "$CREATE_FROM_BASE" -eq 0 ]; then
    die "$EXIT_BRANCH_MISSING" \
      "branch '$BRANCH' does not exist locally or on $REMOTE; pass --create-from-base to create it from $REMOTE/$BASE"
  fi
  has_ref "$base_remote_ref" ||
    die "$EXIT_BASE" "cannot create '$BRANCH': base ref $REMOTE/$BASE does not exist"
  log "creating '$BRANCH' from $REMOTE/$BASE ($(git rev-parse --short "$base_remote_ref")); nothing is pushed"
  git switch --no-track --create "$BRANCH" "$base_remote_ref" >&2 ||
    die "$EXIT_SWITCH" "failed to create branch '$BRANCH' from $REMOTE/$BASE"
elif [ "$has_local" -eq 1 ]; then
  log "switching to existing local branch '$BRANCH'"
  git switch "$BRANCH" >&2 || die "$EXIT_SWITCH" "failed to switch to '$BRANCH'"
else
  # Remote-only: create a tracking branch explicitly rather than relying on
  # DWIM, which fails when more than one remote carries the branch name.
  log "creating local tracking branch for $REMOTE/$BRANCH"
  git switch --track --create "$BRANCH" "$remote_ref" >&2 ||
    die "$EXIT_SWITCH" "failed to create tracking branch for $REMOTE/$BRANCH"
fi

current="$(git rev-parse --abbrev-ref HEAD)"
[ "$current" = "$BRANCH" ] ||
  die "$EXIT_SWITCH" "expected to be on '$BRANCH' but HEAD is '$current'"

# --- Local fast-forward (no second network operation) ----------------------

if has_ref "$remote_ref"; then
  if git merge-base --is-ancestor HEAD "$remote_ref" 2>/dev/null; then
    git merge --ff-only "$remote_ref" >&2 ||
      die "$EXIT_FAST_FORWARD" "fast-forward to $REMOTE/$BRANCH failed"
  elif git merge-base --is-ancestor "$remote_ref" HEAD 2>/dev/null; then
    log "NOTE: local '$BRANCH' is ahead of $REMOTE/$BRANCH; nothing to fast-forward"
  else
    die "$EXIT_FAST_FORWARD" \
      "local '$BRANCH' and $REMOTE/$BRANCH have diverged; resolve manually (no reset or rebase performed)"
  fi
else
  log "NOTE: '$BRANCH' is local-only; no remote fast-forward will occur"
fi

# --- Base reference validation ---------------------------------------------

if ! has_ref "$base_remote_ref"; then
  require_complete_refspec || exit "$EXIT_BASE"
  die "$EXIT_BASE" "base ref $REMOTE/$BASE does not exist"
fi

if ! git merge-base "$base_remote_ref" HEAD >/dev/null 2>&1; then
  if [ "$(git rev-parse --is-shallow-repository)" = "true" ]; then
    die "$EXIT_BASE" \
      "no merge base between $REMOTE/$BASE and HEAD in a shallow clone; fetch more history (git fetch --unshallow)"
  fi
  die "$EXIT_BASE" "no merge base between $REMOTE/$BASE and HEAD; unrelated histories"
fi

# --- Evidence (stdout only) -------------------------------------------------

head_sha="$(git rev-parse HEAD)" || die "$EXIT_EVIDENCE" "unable to resolve HEAD"
base_sha="$(git rev-parse "$base_remote_ref")" ||
  die "$EXIT_EVIDENCE" "unable to resolve $REMOTE/$BASE"
changed="$(git -c core.quotePath=false diff --name-only "$base_remote_ref...HEAD")" ||
  die "$EXIT_EVIDENCE" "unable to compute changed files"

printf 'HEAD_REF=%s\n' "$BRANCH"
printf 'HEAD_SHA=%s\n' "$head_sha"
printf 'BASE_REF=%s/%s\n' "$REMOTE" "$BASE"
printf 'BASE_SHA=%s\n' "$base_sha"
printf 'CHANGED_FILES_BEGIN\n'
if [ -n "$changed" ]; then printf '%s\n' "$changed"; fi
printf 'CHANGED_FILES_END\n'

log "verified '$BRANCH' at $head_sha against $REMOTE/$BASE"
exit "$EXIT_OK"
