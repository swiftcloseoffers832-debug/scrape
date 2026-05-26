#!/usr/bin/env bash
# Install BatchLeads scraper skills into ~/.claude/skills/
# Idempotent: re-running is safe. The shared session-memory.md is never overwritten;
# if the destination is newer or has diverged, the install prints a warning and skips it.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$REPO_DIR/skills"
DEST="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"

if [ ! -d "$SRC" ]; then
  echo "error: $SRC not found" >&2
  exit 1
fi

mkdir -p "$DEST"

installed=()
skipped=()

for dir in "$SRC"/*/; do
  name="$(basename "$dir")"
  target="$DEST/$name"

  # Special-case the memory folder: never clobber a diverged session-memory.md
  if [ "$name" = "memory" ]; then
    target_file="$target/session-memory.md"
    source_file="$dir/session-memory.md"
    mkdir -p "$target"
    if [ -f "$target_file" ] && ! cmp -s "$source_file" "$target_file"; then
      echo "warn: $target_file diverges from repo seed — leaving installed copy intact"
      skipped+=("$name")
      continue
    fi
    cp "$source_file" "$target_file"
    installed+=("$name")
    continue
  fi

  # All other skills: mirror the directory (overwrite SKILL.md, prune stale files)
  rm -rf "$target"
  cp -R "$dir" "$target"
  installed+=("$name")
done

# Also expose the shared helpers script so skills can reference it by absolute path
mkdir -p "$DEST/_shared"
cp "$REPO_DIR/scripts/helpers.js" "$DEST/_shared/helpers.js"

echo ""
echo "Installed into $DEST:"
for s in "${installed[@]}"; do
  echo "  + $s"
done
if [ "${#skipped[@]}" -gt 0 ]; then
  echo "Skipped (preserved existing):"
  for s in "${skipped[@]}"; do
    echo "  ~ $s"
  done
fi
echo ""
echo "Shared helpers: $DEST/_shared/helpers.js"
echo "Done."
