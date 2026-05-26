# scrape

BatchLeads comparables scraper. Two ways to run it:

- **Claude for Chrome extension** (drives your real browser, downloads to your PC) → see [`chrome-extension/PROMPT.md`](chrome-extension/PROMPT.md). One prompt to paste.
- **Claude Code on the web / CLI** (`/scrape` slash command, Playwright in a container) → see the Claude Code section below.

The two share a single source of truth: `scripts/helpers.js` (the in-page JS) and `skills/memory/session-memory.md` (the self-improvement log).

## Claude for Chrome — fastest setup

1. Open BatchLeads, log in, navigate to the property you want to start from.
2. Open the Claude for Chrome extension.
3. Paste the prompt from [`chrome-extension/PROMPT.md`](chrome-extension/PROMPT.md). Done.

Claude fetches [`chrome-extension/PLAYBOOK.md`](chrome-extension/PLAYBOOK.md) from this repo (which inlines the latest helpers + memory), runs the scrape, and downloads `comparables_data.csv` to your PC. At the end it prints a Session Log entry — open Claude Code on the web and say "append this to memory and push" to update the repo, or paste it on GitHub by hand.

## Claude Code (slash command)

`/scrape` runs the entire flow in a Playwright container.

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
