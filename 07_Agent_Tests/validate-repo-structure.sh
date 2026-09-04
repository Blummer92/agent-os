#!/usr/bin/env bash
# Structural regression tests for the Agent OS knowledge base.
# Run from anywhere: bash 07_Agent_Tests/validate-repo-structure.sh
set -uo pipefail
shopt -s nullglob

cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

pass=0
fail=0

check() {
  local name="$1"
  local result="$2"
  if [ "$result" -eq 0 ]; then
    echo "PASS - $name"
    pass=$((pass + 1))
  else
    echo "FAIL - $name"
    fail=$((fail + 1))
  fi
}

is_line_limit_exception() {
  local path="$1"
  local exceptions_file="00_Governance/markdown-line-limit-exceptions.md"
  [ -f "$exceptions_file" ] || return 1
  grep -Fxq "$path" "$exceptions_file"
}

# 1. Frequently loaded governance Markdown (except CLAUDE.md and documented
#    exceptions) normally targets roughly 100-200 lines. A file over 200
#    lines is surfaced as a non-blocking advisory maintainability note only
#    (#1309-O): line count alone never fails this check, authorizes
#    semantic deletion, or forces artificial modularity. Canonical deep
#    standards, dense registries/tables, generated references, schemas, and
#    history may exceed the target when splitting would reduce clarity or
#    duplicate semantics.
over_target=""
while IFS= read -r f; do
  rel="${f#./}"
  if is_line_limit_exception "$rel"; then
    continue
  fi
  lines=$(wc -l < "$f")
  if [ "$lines" -gt 200 ]; then
    over_target="${over_target}${f}: ${lines} lines
"
  fi
done < <(find . -name "*.md" -not -path "./.git/*" -not -name "CLAUDE.md" | sort)
if [ -n "$over_target" ]; then
  echo "ADVISORY - Markdown files over the ~200-line target (non-blocking; review for splitting or a documented exception):"
  printf "%b" "$over_target"
fi
check "Markdown line-count advisory reviewed (non-blocking; see 00_Governance/markdown-line-limit-exceptions.md)" 0

# 2. Every canonical executable overlay must reference _common-overlay-rules.md
# instead of repeating the shared blocks (regression guard for overlay dedup).
# Retired compatibility overlays are intentionally excluded from this executable
# coverage set; the registry is the source of truth for canonical agent overlays.
missing_ref=0
canonical_overlays=()
registry_file=04_Registry/agent-inheritance-registry.md
if [ ! -f "$registry_file" ]; then
  echo "Registry file missing: $registry_file"
  missing_ref=1
else
  mapfile -t canonical_overlays < <(
    sed '/^## Routed Combinations/,$d' "$registry_file" \
      | grep -oE '\| [a-z-]+ \|$' \
      | tr -d '| '
  )
  if [ "${#canonical_overlays[@]}" -eq 0 ]; then
    echo "No canonical agent rows found in: $registry_file"
    missing_ref=1
  fi
fi
for base in "${canonical_overlays[@]}"; do
  f="02_Agent_Overlays/${base}.md"
  [ -f "$f" ] || { echo "No overlay file for: $base"; missing_ref=1; continue; }
  grep -q "_common-overlay-rules.md" "$f" || { echo "Missing reference: $f"; missing_ref=1; }
done
check "Every canonical overlay references _common-overlay-rules.md" "$missing_ref"

# 3. No filename collisions between 00_Governance and 04_Registry, other
#    than each folder's own README.md (regression guard for the duplicate
#    agent-inheritance-registry.md issue).
collisions=$(comm -12 \
  <(ls 00_Governance | grep -v '^README.md$' | sort) \
  <(ls 04_Registry | grep -v '^README.md$' | sort))
if [ -n "$collisions" ]; then
  echo "Colliding filenames: $collisions"
fi
check "No filename collisions between 00_Governance and 04_Registry" "$([ -z "$collisions" ] && echo 0 || echo 1)"

# 4. Every agent listed in the inheritance registry has a matching overlay file.
registry_missing=0
if [ ! -f "$registry_file" ]; then
  echo "Registry file missing: $registry_file"
  registry_missing=1
else
  if [ "${#canonical_overlays[@]}" -eq 0 ]; then
    echo "No agent rows found in: $registry_file"
    registry_missing=1
  fi
  for overlay_ref in "${canonical_overlays[@]}"; do
    [ -f "02_Agent_Overlays/${overlay_ref}.md" ] || { echo "No overlay file for: $overlay_ref"; registry_missing=1; }
  done
fi
check "Every registered agent has a matching overlay file" "$registry_missing"

# 5. Every canonical registered agent has a matching .tests.md file.
test_orphans=0
for base in "${canonical_overlays[@]}"; do
  [ -f "07_Agent_Tests/${base}.tests.md" ] || { echo "Registered agent has no test file: $base"; test_orphans=1; }
done
check "Every registered agent has a matching test file" "$test_orphans"

# 6. Every canonical registered overlay has a matching test file (coverage check).
overlay_untested=0
for base in "${canonical_overlays[@]}"; do
  [ -f "02_Agent_Overlays/${base}.md" ] || { echo "Registered overlay missing: $base"; overlay_untested=1; continue; }
  [ -f "07_Agent_Tests/${base}.tests.md" ] || { echo "Overlay has no test file: 02_Agent_Overlays/${base}.md"; overlay_untested=1; }
done
check "Every canonical overlay has a matching test file" "$overlay_untested"

# 7. Every repository path listed in the Documentation Dependency Map metadata exists
map_meta="00_Governance/documentation-dependency-map/metadata.yaml"
map_refs_missing=0
if [ -f "$map_meta" ]; then
  while IFS= read -r p; do
    [ -z "$p" ] && continue
    [ -e "$p" ] || { echo "Documentation map metadata references missing path: $p"; map_refs_missing=1; }
  done < <(awk '
    /^validate_paths:/ { inblock=1; next }
    inblock && /^[A-Za-z0-9_]+:/ { inblock=0 }
    inblock && /^[[:space:]]*-[[:space:]]/ {
      line=$0
      sub(/^[[:space:]]*-[[:space:]]*/, "", line)
      gsub(/"/, "", line)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", line)
      if (line != "") print line
    }
  ' "$map_meta")
fi
check "All Documentation Dependency Map metadata paths exist" "$map_refs_missing"

# 8. Every Markdown file path listed in the Navigation Alias Registry exists.
alias_registry="04_Registry/navigation-alias-registry.md"
alias_refs_missing=0
if [ ! -f "$alias_registry" ]; then
  echo "Navigation Alias Registry missing: $alias_registry"
  alias_refs_missing=1
else
  while IFS= read -r p; do
    [ -z "$p" ] && continue
    [ -f "$p" ] || { echo "Navigation alias references missing path: $p"; alias_refs_missing=1; }
  done < <(grep -oE '`[A-Za-z0-9_./-]+\.md`' "$alias_registry" | tr -d '`' | sort -u)
fi
check "All Navigation Alias Registry Markdown paths exist" "$alias_refs_missing"

# 9. The lean governance excluded-surface baseline stays referenced by its dependents.
baseline_file="01_Shared_Standards/github/excluded-surface-baseline.md"
baseline_refs_missing=0
baseline_dependents=(
  "00_Governance/write-authorization-policy.md"
  "01_Shared_Standards/github/safe-implementation-lane.md"
  "02_Agent_Overlays/github-service-agent.md"
  "03_Templates/prompts/tier0-tier1-issue.md"
  "04_Registry/navigation-alias-registry.md"
)
if [ ! -f "$baseline_file" ]; then
  echo "Excluded-surface baseline missing: $baseline_file"
  baseline_refs_missing=1
else
  for f in "${baseline_dependents[@]}"; do
    [ -f "$f" ] || { echo "Baseline dependent missing: $f"; baseline_refs_missing=1; continue; }
    grep -Fq -- "$baseline_file" "$f" || { echo "Baseline dependent missing reference: $f"; baseline_refs_missing=1; }
  done
fi
check "Lean governance baseline references are aligned" "$baseline_refs_missing"

echo
echo "Results: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
