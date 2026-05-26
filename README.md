# scrape

BatchLeads comparables scraper for **Claude Code on the web**, packaged as modular skills with a one-command `/scrape` workflow.

## What it does

Open this repo in Claude Code on the web. Type `/scrape`. Claude logs into BatchLeads in a containerized browser, walks every property in the list, captures every comp on every page (with ZIPs), delivers the final CSV to you in chat, prints a memory diff for you to copy, and commits the updated memory log to git. Watchdog auto-saves on stalls; localStorage checkpoints survive crashes.

## One-time setup

1. **Open this repo in Claude Code on the web.** The `SessionStart` hook will install the skills into `~/.claude/skills/` automatically.
2. **Approve Playwright MCP.** The first session prompts you to allow `@playwright/mcp` — accept it. This gives Claude a browser inside the container.
3. **(Optional) Add BatchLeads credentials as environment secrets.** In Claude Code on the web settings, add:
   - `BATCHLEADS_EMAIL`
   - `BATCHLEADS_PASSWORD`

   If you skip this, `/scrape` will pause and ask you to paste them into chat for that session only.

## How to run a session

```
/scrape
```

Claude will ask you for:
- Starting URL (the BatchLeads property-list page or property page you want scraping to begin on)
- How many properties to process (default 20, max ~250 per session)

Then it runs autonomously. You'll see brief progress updates between batches. At the end you get:

1. A **CSV file delivered in chat** — click to download to your PC.
2. A **memory-update markdown block** in chat — copy if you want to paste it elsewhere.
3. A **git commit pushed** to `skills/memory/session-memory.md` so the next session inherits the improvements.

No other downloads happen during the run *except*:
- **Emergency backup** — if the watchdog detects a 2-minute stall, a timestamped JSON snapshot is dumped to localStorage and a partial CSV is written to `outputs/`.
- **Per-property checkpoint** — `window.__compCSV` is mirrored to `localStorage.__compCSV_backup` after every property, so a mid-session crash never loses more than the property in progress.

## Layout

```
scrape/
├── .mcp.json                            # Auto-installs Playwright MCP
├── .claude/
│   ├── settings.json                    # SessionStart hook config
│   ├── hooks/session-start.sh           # Installs skills + injects memory into context
│   └── commands/scrape.md               # The /scrape slash command
├── install.sh                           # Idempotent skill installer
├── scripts/
│   └── helpers.js                       # window.__* helpers (browser-side)
└── skills/
    ├── batchleads-navigation/SKILL.md
    ├── batchleads-capture/SKILL.md      # ZIP from dedicated column — never parsed
    ├── batchleads-csv/SKILL.md
    ├── batchleads-session/SKILL.md
    ├── batchleads-memory/SKILL.md
    └── memory/session-memory.md         # Grows every session
```

## Automatic priming

Every session in this repo auto-runs `.claude/hooks/session-start.sh`. It installs the skills into `~/.claude/skills/` and injects `session-memory.md` into Claude's context, so every session begins with the latest `Current Best Method` and `Known Pitfalls` already loaded.

## Critical invariant

ZIP codes are mandatory. The whole CSV is useless without them. ZIP comes from the dedicated `Zip` column in the comp table — never parsed from the address string. `/scrape` will refuse to deliver a CSV with `zipCoverage < 1.0` and instead surface the problem.
