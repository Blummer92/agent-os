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
  grep -q "_common-overlay-rules.md" "$f" || { echo "Missing reference: $f"; missing_ref=1; }
done
check "Every overlay references _common-overlay-rules.md" "$missing_ref"

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
# Only reads the "Agent | Inherits | Overlay" table above the
# "## Routed Combinations" heading, so a lowercase-hyphenated value added to
# the routing table later can't be mistaken for an overlay slug.
registry_missing=0
registry_file=04_Registry/agent-inheritance-registry.md
if [ ! -f "$registry_file" ]; then
  echo "Registry file missing: $registry_file"
  registry_missing=1
else
  overlay_refs=$(sed '/^## Routed Combinations/,$d' "$registry_file" | grep -oE '\| [a-z-]+ \|$' | tr -d '| ')
  if [ -z "$overlay_refs" ]; then
    echo "No agent rows found in: $registry_file"
    registry_missing=1
  fi
  while IFS= read -r overlay_ref; do
    [ -z "$overlay_ref" ] && continue
    [ -f "02_Agent_Overlays/${overlay_ref}.md" ] || { echo "No overlay file for: $overlay_ref"; registry_missing=1; }
  done <<< "$overlay_refs"
fi
check "Every registered agent has a matching overlay file" "$registry_missing"

# 5. Every .tests.md file in 07_Agent_Tests has a matching overlay file.
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

# 6. Every overlay file has a matching test file (coverage check).
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

# 7. Every repository path listed in the Documentation Dependency Map metadata exists
#    (operationalizes the "broken reference count" metric). Dependency-free: parses only
#    the flat `validate_paths:` block with awk. Skips cleanly if the metadata is absent.
#    Only repository paths are listed there; Notion/Drive targets are excluded by design.
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

echo
echo "Results: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
