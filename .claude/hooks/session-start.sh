#!/usr/bin/env bash
# SessionStart hook for the BatchLeads comparables scraper.
# Injects the persistent memory log into Claude's context so every new session
# starts with the Current Best Method and Known Pitfalls already loaded.
# No dependencies to install — this repo is a skills package, not an app.

set -euo pipefail

MEMORY_FILE="$CLAUDE_PROJECT_DIR/skills/memory/session-memory.md"

# Mirror the latest skills into ~/.claude/skills/ so they're invocable this session.
# install.sh is idempotent and preserves any diverged session-memory.md on the destination side.
if [ -x "$CLAUDE_PROJECT_DIR/install.sh" ]; then
  bash "$CLAUDE_PROJECT_DIR/install.sh" >/dev/null 2>&1 || true
fi

cat <<EOF
=== BatchLeads scraper — session priming ===

The repository at $CLAUDE_PROJECT_DIR is the BatchLeads comparables scraper packaged as modular Claude Code skills. The skills (batchleads-navigation, batchleads-capture, batchleads-csv, batchleads-session, batchleads-memory) have just been installed into ~/.claude/skills/ via install.sh.

Below is the persistent memory log. APPLY the Current Best Method to this session, and treat each Known Pitfall as a hard constraint. At session end, after the final CSV is saved, append a new Session Log entry to this file, commit it, and push to the remote so future sessions inherit any improvements.

EOF

if [ -f "$MEMORY_FILE" ]; then
  cat "$MEMORY_FILE"
else
  echo "(no session-memory.md found at $MEMORY_FILE — start fresh and create one at session end)"
fi

echo ""
echo "=== end memory ==="
