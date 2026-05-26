---
name: batchleads-session
description: Drive the BatchLeads comp-scraping session end-to-end — batch loop, checkpoints, credit-aware stopping, final save. Use when starting a scrape session, resuming after a checkpoint, or wrapping up a session.
---

# BatchLeads Session

Your only job is to run the main scraping loop efficiently, checkpoint progress so nothing is lost, and stop cleanly when credits run low. Navigation, capture, CSV, and memory are separate skills that this skill orchestrates.

## Session start (run once)

1. Read `skills/memory/session-memory.md`. Apply the `Current Best Method` from the most recent entry. Note any new `Known Pitfalls`.
2. Inject `scripts/helpers.js` into the page via `javascript_tool`. This defines every `window.__*` function and resets per-session state if absent.
3. Land on the first BatchLeads property page (the user usually has this open already).
4. Start the watchdog: `window.__startCrashWatchdog()` — auto-emergency-saves if no new comps arrive for 2 minutes.
5. Click the Comparables tab on the first property and capture it:

   ```js
   await window.__clickComparablesTab();
   await window.__captureCurrentProperty();
   ```

## Main loop

For each batch (20 properties is the sweet spot — 15–25 acceptable):

1. **Launch the in-page async loop** (do not await — it runs detached so the agent can wait via `browser_batch`):

   ```js
   window.__processBatch(20).then(r => { window.__lastBatch = r; }); 'started';
   ```

2. **Chain `browser_batch` waits** — 8–12 sequential `{action:"wait", duration:10}` entries. Round-tripping per-click through the agent is far slower than letting the in-page setTimeout loop run.

3. **Poll for completion**:

   ```js
   ({ done: window.__lastBatch !== null, comps: window.__compCSV.length, props: window.__propertyCount })
   ```

   If `done` is still `false`, add more 10s waits.

4. **Checkpoint** — `__processBatch` already writes to `localStorage` after every property. After each batch also note the running totals.

5. Reset `window.__lastBatch = null;` and start the next batch.

## Minimum reliable timings (do not shorten)

- 2.5–3.5s between property navigation
- 2.5s after clicking the Comparables tab
- 1.8s between comp pagination clicks

These are built into the helper functions. Do not duplicate them outside the helpers.

## Checkpoint cadence

- Continuous: `localStorage.__compCSV_backup` is updated after every property inside `__processBatch`.
- Every 250 comp rows: pause briefly, note total comps + total properties, then continue without waiting for instruction.
- The CSV in `window.__compCSV` is always live — you do not need a separate "save" step until session end.

## Credit-aware stopping

1. Estimate per-property cost from the running session (`comps captured / credits used`).
2. If remaining credits cannot complete the next property cleanly, **do not start it.** Skip straight to session end.
3. Common BatchLeads density: ~15 comps/property average, but some have 1 and some have 100. Budget conservatively.

## Session end

1. Stop the watchdog: `clearInterval(window.__watchdogTimer)`.
2. Run `window.__downloadFinalCSV()`. Confirm row count > 0.
3. Verify 100% ZIP coverage: `window.__compCSV.filter(r => !r.zip).length` should be `0`.
4. Hand the downloaded `comparables_data.csv` to the user.
5. Trigger the `batchleads-memory` skill to append a Session Log entry.
6. **Never** export through the BatchLeads UI — that costs credits and breaks the schema.

## Resume from crash

If the page crashed or a session restart is needed:

1. Re-inject `scripts/helpers.js`.
2. Restore state:

   ```js
   window.__compCSV = JSON.parse(localStorage.getItem('__compCSV_backup') || '[]');
   window.__propertyAddresses = JSON.parse(localStorage.getItem('__propAddrs_backup') || '[]');
   window.__propertyCount = window.__propertyAddresses.length;
   ```

3. Resume the loop from the next property.

## What this skill does NOT do

- Does not click individual tabs → see `batchleads-navigation`
- Does not parse DOM cells → see `batchleads-capture`
- Does not build the CSV file → see `batchleads-csv`
- Does not append to the memory log → see `batchleads-memory`
