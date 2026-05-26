# scrape

BatchLeads comparables scraper, packaged as modular Claude Code skills.

## Layout

```
scrape/
├── install.sh                          # Installs skills into ~/.claude/skills/
├── scripts/
│   └── helpers.js                      # Shared window.__* helpers — single source of truth
└── skills/
    ├── batchleads-navigation/SKILL.md  # Click Comparables tab, paginate, advance properties
    ├── batchleads-capture/SKILL.md     # Extract comp rows (ZIP from dedicated column!)
    ├── batchleads-csv/SKILL.md         # Dedupe + Blob-download the final CSV
    ├── batchleads-session/SKILL.md     # Drive the batch loop, checkpoint, stop cleanly
    ├── batchleads-memory/SKILL.md      # Read + append session-memory.md
    └── memory/
        └── session-memory.md           # Persistent process log (commit after each session)
```

## Install

```bash
bash install.sh
```

Copies every `skills/<name>/` into `~/.claude/skills/<name>/` and places `helpers.js` at `~/.claude/skills/_shared/helpers.js`. Safe to re-run — a diverged `session-memory.md` in the destination is preserved.

## Run a session

1. Land on a BatchLeads property page.
2. Inject the helpers into the page (via `javascript_tool` or your browser tool):

   ```js
   // contents of scripts/helpers.js
   ```

3. Trigger `batchleads-session` — it reads `session-memory.md`, starts the watchdog, and drives the batch loop end-to-end.
4. At session end, the final `comparables_data.csv` downloads automatically. Then `batchleads-memory` appends a Session Log entry — commit and push so the next session benefits.

## Automatic priming

When you start a Claude Code session in this repo, `.claude/hooks/session-start.sh` runs automatically. It installs the skills into `~/.claude/skills/` and injects `session-memory.md` into the assistant's context, so every session begins with the latest `Current Best Method` and `Known Pitfalls` already loaded — no manual step required.

At session end, ask Claude to append a Session Log entry, then commit and push so the next session inherits the improvement.

## Critical invariant

ZIP codes are mandatory. The whole CSV is useless without them. ZIP comes from the dedicated `Zip` column in the comp table — never parsed from the address string. See `Known Pitfalls` in `skills/memory/session-memory.md`.
