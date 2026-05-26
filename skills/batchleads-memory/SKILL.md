---
name: batchleads-memory
description: Read and append to the persistent BatchLeads scraper memory log so every session starts smarter than the last. Use at session start (read) and session end (append). Never modify during a run.
---

# BatchLeads Memory

Your only job is to maintain `skills/memory/session-memory.md` — a process-and-efficiency log that grows monotonically across sessions. Comp data NEVER goes here.

## File location

Canonical source: `skills/memory/session-memory.md` in the `scrape` repo.
After `install.sh` runs it is also available at `~/.claude/skills/batchleads-memory/memory/session-memory.md`.

If the file does not exist for any reason, create it with these four section headers:

```
# comp scraper memory

Last Updated: <date>

## Current Best Method

## Session Log

## Known Pitfalls
```

## Session start — READ

Before scraping begins:

1. Read the file in full.
2. Apply the `Current Best Method` from the most recent entry to this session.
3. Scan `Known Pitfalls` and treat each one as a hard constraint for the run.

## Session end — APPEND

Only update the file **AFTER** the final CSV has been saved AND uploaded. Memory work must never delay or interfere with data capture.

Append a new dated entry to `Session Log` containing:

1. Date and approximate session length
2. Total properties processed
3. Total comps captured (and dedupe delta if material)
4. The exact method and navigation pattern used
5. Roughly how many credits were consumed relative to comps captured
6. Any errors, slow points, or wasted steps

If a faster method was discovered: **rewrite** `Current Best Method` to reflect it.

If a new pitfall was hit: append it to `Known Pitfalls` along with the fix.

Update `Last Updated` to today's date.

## Strict rules

1. **Never overwrite the entire file.** Append to `Session Log` only. Edit `Current Best Method`, `Known Pitfalls`, and `Last Updated` in place.
2. **Never delete past Session Log entries.** The log is the history.
3. **Never put comp data in the file.** No addresses, no prices, no row counts beyond the aggregate "X comps captured" summary.
4. Keep entries concise and factual.
5. If the user is running on Claude Code on the web (ephemeral container), commit and push the updated file to the repo before the session ends — otherwise the update is lost when the container is reclaimed.

## Carrying the ZIP rule forward

The single most important pitfall in this scraper is **mandatory ZIP coverage**. Every session-end entry should state ZIP coverage explicitly (e.g. `100% ZIP coverage` or the count of empty zips). If coverage drops below 100% in any session, that is a regression and the fix goes straight into `Known Pitfalls`.
