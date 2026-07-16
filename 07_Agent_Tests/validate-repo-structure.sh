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

trim() {
  local value="$1"
  value="${value#${value%%[![:space:]]*}}"
  value="${value%${value##*[![:space:]]}}"
  printf '%s' "$value"
}

registry_file="04_Registry/agent-inheritance-registry.md"
responsibility_file="04_Registry/responsibility-matrix.md"

registered_agents() {
  sed '/^## Routed Combinations/,$d' "$registry_file" | awk -F'|' '
    function trim(s) { gsub(/^[ \t]+|[ \t]+$/, "", s); return s }
    NR > 2 && NF >= 4 {
      agent=trim($2)
      if (agent != "" && agent != "Agent" && agent !~ /^---$/) print agent
    }
  '
}

registered_overlays() {
  sed '/^## Routed Combinations/,$d' "$registry_file" | awk -F'|' '
    function trim(s) { gsub(/^[ \t]+|[ \t]+$/, "", s); return s }
    NR > 2 && NF >= 4 {
      overlay=trim($4)
      if (overlay != "" && overlay != "Overlay" && overlay !~ /^---$/) print overlay
    }
  '
}

is_registered_agent() {
  local candidate="$1"
  registered_agents | grep -Fxq "$candidate"
}

is_registered_overlay() {
  local candidate="$1"
  registered_overlays | grep -Fxq "$candidate"
}

is_allowed_support_surface() {
  case "$1" in
    "Apps Script Sync Test Overlay"|\
    "Dashboard Builder Overlay"|\
    "GitHub Change Request"|\
    "Instructional Design Standards"|\
    "Navigation Registry Standard"|\
    "Python Development Overlay"|\
    "Workspace Implementation Overlay"|\
    "selected registered owner")
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

# 1. Every Markdown file except CLAUDE.md and documented exceptions must stay
#    under 100 lines.
over_limit=""
while IFS= read -r f; do
  rel="${f#./}"
  if is_line_limit_exception "$rel"; then
    continue
  fi
  lines=$(wc -l < "$f")
  if [ "$lines" -ge 100 ]; then
    over_limit="${over_limit}${f}: ${lines} lines
"
  fi
done < <(find . -name "*.md" -not -path "./.git/*" -not -name "CLAUDE.md" | sort)
if [ -n "$over_limit" ]; then
  printf "%b" "$over_limit"
fi
check "All non-exempt Markdown files (except CLAUDE.md) are under 100 lines" "$([ -z "$over_limit" ] && echo 0 || echo 1)"

# 2. Every overlay must reference _common-overlay-rules.md instead of
#    repeating the shared blocks (regression guard for overlay dedup).
missing_ref=0
overlay_files=(02_Agent_Overlays/*.md)
if [ "${#overlay_files[@]}" -eq 0 ]; then
  echo "No overlay files found in 02_Agent_Overlays/"
  missing_ref=1
fi
for f in "${overlay_files[@]}"; do
  base=$(basename "$f")
  [ "$base" = "_common-overlay-rules.md" ] && continue
  [ "$base" = "README.md" ] && continue
  grep -q "_common-overlay-rules.md" "$f" || { echo "Overlay missing _common-overlay-rules.md reference: $f"; missing_ref=1; }
done
check "Every overlay references _common-overlay-rules.md" "$missing_ref"

# 3. No filename collisions between 00_Governance and 04_Registry, other
#    than each folder's own README.md (regression guard for the duplicate
#    agent-inheritance-registry.md issue).
collisions=$(comm -12 \
  <(ls 00_Governance | grep -v '^README.md$' | sort) \
  <(ls 04_Registry | grep -v '^README.md$' | sort))
if [ -n "$collisions" ]; then
  echo "Governance/Registry filename collision: $collisions"
fi
check "No filename collisions between 00_Governance and 04_Registry" "$([ -z "$collisions" ] && echo 0 || echo 1)"

# 4. Every agent listed in the inheritance registry has a matching overlay file.
registry_missing=0
if [ ! -f "$registry_file" ]; then
  echo "Registry file missing: $registry_file"
  registry_missing=1
else
  overlay_refs=$(registered_overlays)
  if [ -z "$overlay_refs" ]; then
    echo "No agent rows found in: $registry_file"
    registry_missing=1
  fi
  while IFS= read -r overlay_ref; do
    [ -z "$overlay_ref" ] && continue
    [ -f "02_Agent_Overlays/${overlay_ref}.md" ] || { echo "Registered agent has no matching overlay: 02_Agent_Overlays/${overlay_ref}.md"; registry_missing=1; }
  done <<< "$overlay_refs"
fi
check "Every registered agent has a matching overlay file" "$registry_missing"

# 5. Every registered agent has a matching test file.
registry_tests_missing=0
if [ ! -f "$registry_file" ]; then
  registry_tests_missing=1
else
  while IFS= read -r overlay_ref; do
    [ -z "$overlay_ref" ] && continue
    [ -f "07_Agent_Tests/${overlay_ref}.tests.md" ] || { echo "Registered agent has no matching agent test file: 07_Agent_Tests/${overlay_ref}.tests.md"; registry_tests_missing=1; }
  done <<< "$(registered_overlays)"
fi
check "Every registered agent has a matching test file" "$registry_tests_missing"

# 6. Every .tests.md file in 07_Agent_Tests has a matching overlay file.
test_orphans=0
test_files=(07_Agent_Tests/*.tests.md)
if [ "${#test_files[@]}" -eq 0 ]; then
  echo "No test files found in 07_Agent_Tests/"
  test_orphans=1
fi
for f in "${test_files[@]}"; do
  base=$(basename "$f" .tests.md)
  [ -f "02_Agent_Overlays/${base}.md" ] || { echo "Test file has no matching overlay: $f"; test_orphans=1; }
done
check "Every agent test file has a matching overlay" "$test_orphans"

# 7. Every overlay file has a matching test file (coverage check).
overlay_untested=0
if [ "${#overlay_files[@]}" -eq 0 ]; then
  echo "No overlay files found in 02_Agent_Overlays/"
  overlay_untested=1
fi
for f in "${overlay_files[@]}"; do
  base=$(basename "$f" .md)
  [ "$base" = "_common-overlay-rules" ] && continue
  [ "$base" = "README" ] && continue
  [ -f "07_Agent_Tests/${base}.tests.md" ] || { echo "Overlay has no test file: $f"; overlay_untested=1; }
done
check "Every overlay has a matching test file" "$overlay_untested"

# 8. Every overlay file is registered or explicitly exempted as a helper file.
overlay_unregistered=0
for f in "${overlay_files[@]}"; do
  base=$(basename "$f" .md)
  [ "$base" = "_common-overlay-rules" ] && continue
  [ "$base" = "README" ] && continue
  is_registered_overlay "$base" || { echo "Overlay is not registered and is not an allowed helper/exemption: $f"; overlay_unregistered=1; }
done
check "Every overlay is registered or explicitly exempted" "$overlay_unregistered"

# 9. Backticked inherited standard/governance/registry paths in overlays must exist.
missing_inherited_paths=0
for f in "${overlay_files[@]}"; do
  while IFS= read -r p; do
    [ -z "$p" ] && continue
    [ -e "$p" ] || { echo "Overlay references missing inherited standard path: $f -> $p"; missing_inherited_paths=1; }
  done < <(grep -oE '`(00_Governance|01_Shared_Standards|04_Registry)/[^`]+`' "$f" | tr -d '`' | sort -u)
done
check "Overlay inherited standard paths exist" "$missing_inherited_paths"

# 10. Responsibility Matrix primary agents must resolve to registered agents.
unknown_primary=0
if [ ! -f "$responsibility_file" ]; then
  echo "Responsibility Matrix file missing: $responsibility_file"
  unknown_primary=1
else
  while IFS=$'\t' read -r responsibility primary; do
    [ -z "$responsibility" ] && continue
    while IFS= read -r candidate; do
      candidate=$(trim "$candidate")
      [ -z "$candidate" ] && continue
      is_registered_agent "$candidate" || { echo "Responsibility Matrix primary agent is not registered: $responsibility -> $candidate"; unknown_primary=1; }
    done < <(printf '%s\n' "$primary" | sed 's/ -> /\n/g; s/;/\n/g')
  done < <(awk -F'|' '
    function trim(s) { gsub(/^[ \t]+|[ \t]+$/, "", s); return s }
    NR > 2 && NF >= 4 { responsibility=trim($2); primary=trim($3); if (responsibility != "" && responsibility !~ /^---$/) print responsibility "\t" primary }
  ' "$responsibility_file")
fi
check "Responsibility Matrix primary agents are registered" "$unknown_primary"

# 11. Responsibility Matrix support values must resolve to registered agents or documented support surfaces.
unknown_support=0
if [ ! -f "$responsibility_file" ]; then
  unknown_support=1
else
  while IFS=$'\t' read -r responsibility support; do
    [ -z "$responsibility" ] && continue
    while IFS= read -r candidate; do
      candidate=$(trim "$candidate")
      [ -z "$candidate" ] && continue
      is_registered_agent "$candidate" || is_allowed_support_surface "$candidate" || { echo "Responsibility Matrix support value is not registered or documented: $responsibility -> $candidate"; unknown_support=1; }
    done < <(printf '%s\n' "$support" | sed 's/;/\n/g')
  done < <(awk -F'|' '
    function trim(s) { gsub(/^[ \t]+|[ \t]+$/, "", s); return s }
    NR > 2 && NF >= 4 { responsibility=trim($2); support=trim($4); if (responsibility != "" && responsibility !~ /^---$/) print responsibility "\t" support }
  ' "$responsibility_file")
fi
check "Responsibility Matrix support values resolve" "$unknown_support"

# 12. Every registered agent must appear in the Responsibility Matrix or support list.
agent_unassigned=0
while IFS= read -r agent; do
  [ -z "$agent" ] && continue
  grep -Fq "| $agent |" "$responsibility_file" || grep -Fq "$agent" "$responsibility_file" || { echo "Registered agent has no Responsibility Matrix entry: $agent"; agent_unassigned=1; }
done <<< "$(registered_agents)"
check "Every registered agent appears in the Responsibility Matrix" "$agent_unassigned"

# 13. Navigation Registry ownership and write-boundary assertions must not drift.
nav_drift=0
grep -Fq "Navigation Registry governance and lookup routing | Integration Manager" "$registry_file" || { echo "Navigation Registry routed owner drift: expected Integration Manager in agent-inheritance-registry.md"; nav_drift=1; }
grep -Fq "Navigation Registry governance and cross-system lookup routing | Integration Manager" "$responsibility_file" || { echo "Navigation Registry responsibility drift: expected Integration Manager as primary in responsibility-matrix.md"; nav_drift=1; }
grep -Fq "01_Shared_Standards/navigation/navigation-registry-standard.md" "02_Agent_Overlays/integration-manager.md" || { echo "Integration Manager missing Navigation Registry Standard inheritance"; nav_drift=1; }
grep -Fq "Sole GitHub write owner" "02_Agent_Overlays/github-service-agent.md" || { echo "GitHub Service Agent write-owner rule missing or changed"; nav_drift=1; }
grep -Fq "lookup aid only" "01_Shared_Standards/navigation/navigation-registry-standard.md" || { echo "Navigation Registry non-authoritative rule missing or changed"; nav_drift=1; }
grep -Fq "may not treat a" "01_Shared_Standards/navigation/navigation-registry-standard.md" || { echo "Navigation Registry write-boundary rule missing or changed"; nav_drift=1; }
check "Navigation Registry ownership and write boundary remain consistent" "$nav_drift"

# 14. Every repository path listed in the Documentation Dependency Map metadata exists
#    (operationalizes the "broken reference count" metric). Dependency-free: parses only
#    the flat `validate_paths:` block with awk. Skips cleanly if the metadata is absent.
#    Only repository paths are listed there; Notion/Drive targets are excluded by design.
map_meta="00_Governance/documentation-dependency-map/metadata.yaml"
map_refs_missing=0
if [ -f "$map_meta" ]; then
  while IFS= read -r p; do
    [ -z "$p" ] && continue
    [ -e "$p" ] || { echo "Referenced repository path does not exist: $p"; map_refs_missing=1; }
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

echo
echo "Results: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
