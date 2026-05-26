---
description: Run a full BatchLeads comp scraping session end-to-end via Playwright MCP. Logs in, batches through properties, delivers final CSV + memory update.
---

# /scrape — Full BatchLeads scraping session

You are about to run a complete BatchLeads comparables scraping session **autonomously** using the Playwright MCP browser inside this container. The user has invoked this command and expects you to drive the entire flow with minimal interruption.

## Tools you will use

- `mcp__playwright__browser_navigate` — go to URLs
- `mcp__playwright__browser_evaluate` — run the `window.__*` helpers
- `mcp__playwright__browser_type` — type into login fields if needed
- `mcp__playwright__browser_click` — click login submit
- `mcp__playwright__browser_wait_for` — wait for selectors / text
- `mcp__playwright__browser_take_screenshot` — only for login troubleshooting
- `Write` — save the final CSV to the container filesystem
- `SendUserFile` — deliver the CSV to the user in chat
- `Bash` — git commit + push the updated memory file

## Step 1 — Gather inputs

Ask the user with `AskUserQuestion` for:

1. The exact BatchLeads URL to start from (the property list page or a specific property page they want scraping to begin on).
2. How many properties to process this session (default: 20; max recommended: 250 per session given credit limits).

Also check whether `BATCHLEADS_EMAIL` and `BATCHLEADS_PASSWORD` are present in the environment. If they are, use them. If they are NOT, ask the user via `AskUserQuestion` whether they want to (a) paste credentials into chat for this session only, or (b) abort so they can add them as Claude Code on the web environment secrets first.

## Step 2 — Log in

1. `browser_navigate` to `https://app.batchleads.io/login` (or the canonical BatchLeads login URL — try the user's starting URL first; if it redirects to login, you're on the right page).
2. `browser_type` the email into the email field, then the password into the password field.
3. `browser_click` the sign-in button.
4. `browser_wait_for` text indicating successful login (e.g. dashboard, property list, the user's name).
5. If 2FA prompt appears, `AskUserQuestion` the user for the code and type it in.

## Step 3 — Navigate to the starting page

1. `browser_navigate` to the URL the user provided in Step 1.
2. `browser_wait_for` until the property page loads (look for the Comparables tab or property address).

## Step 4 — Inject helpers

Read `scripts/helpers.js` from the repo and inject it via `browser_evaluate`. The functions land on `window.__*` and persist for the rest of the session.

```js
// browser_evaluate body — paste the full contents of scripts/helpers.js, then:
'helpers injected; __compCSV length: ' + window.__compCSV.length;
```

Start the watchdog: `browser_evaluate` with `window.__startCrashWatchdog();`.

## Step 5 — Capture the first property

```js
await window.__clickComparablesTab();
await window.__captureCurrentProperty();
```

`browser_evaluate` returns the result. Verify the comp table loaded; if not, `browser_wait_for` and retry once.

## Step 6 — Main batch loop

Apply the **Current Best Method** from `session-memory.md` (already in your context from the SessionStart hook). For each batch (batch size 20, or remaining count if less):

1. **Launch async batch** (detached, don't await):

   ```js
   window.__lastBatch = null;
   window.__processBatch(20).then(r => { window.__lastBatch = r; });
   'batch started';
   ```

2. **Wait in chunks.** Call `browser_wait_for` with `time: 30` (30 seconds) repeatedly until `window.__lastBatch !== null`. Between waits, poll progress:

   ```js
   ({ done: window.__lastBatch !== null, comps: window.__compCSV.length, props: window.__propertyCount });
   ```

3. **Checkpoint.** After each batch completes:
   - Note running totals in your scratchpad (you can keep this in your reply text — do not write a separate file).
   - Continue immediately to the next batch — no pause, no summary, no commentary.

4. **Stop conditions:**
   - User-requested property count reached.
   - You estimate remaining credits cannot finish another property cleanly.
   - Three consecutive batches return errors.

## Step 7 — Build & deliver the CSV

1. `browser_evaluate`:

   ```js
   window.__getCSV();
   ```

   Returns `{ csv: "...", rows: N, properties: M, zipCoverage: 0.0–1.0 }`.

2. **Verify ZIP coverage.** If `zipCoverage < 1.0`, stop and report — this is a critical pitfall. Do NOT deliver a file with missing ZIPs without flagging it explicitly.

3. Write the CSV to `/home/user/scrape/outputs/comparables_<ISO-timestamp>.csv` using the `Write` tool. (Create `outputs/` if missing; it is in `.gitignore` and won't be committed.)

4. Deliver to the user via `SendUserFile` with `status: "proactive"` and a caption like `"BatchLeads comps: N rows across M properties, 100% ZIP coverage"`.

## Step 8 — Memory update

1. Draft a Session Log entry following the format in `skills/memory/session-memory.md`. Required fields: date, approximate length, total properties, total comps (with dedupe delta if material), method used, credit usage rough sense, any errors / slow points, ZIP coverage.
2. Print the draft entry **in the chat** as a fenced markdown block so the user can copy it.
3. Append the entry to `skills/memory/session-memory.md` via `Edit`. Refresh `Last Updated`. Only edit `Current Best Method` / `Known Pitfalls` if you genuinely improved something or hit a new pitfall.
4. Commit the memory update and push:

   ```bash
   git add skills/memory/session-memory.md
   git commit -m "memory: <YYYY-MM-DD> session — <N> properties / <M> comps"
   git push -u origin <current-branch>
   ```

## Step 9 — Final reply

Single short summary: properties processed, comps captured, ZIP coverage, file delivered ✓, memory committed ✓. Nothing else.

## Hard rules (apply throughout)

- **NEVER export through the BatchLeads UI.** That costs credits and breaks the schema.
- **ZIP CODES ARE MANDATORY.** If `zipCoverage < 1.0`, stop and report rather than silently delivering an incomplete file.
- **Never scroll, never screenshot during the main loop.** DOM reads via `browser_evaluate` are sufficient and faster.
- **Don't pause between properties** unless a checkpoint (every 250 comps) or a stop condition is hit.
- **Watchdog stays armed** until Step 7 completes. If it fires, `__emergencyBackup` writes the partial CSV — recover it from the container filesystem and deliver it anyway with a clear "partial / emergency" caption.

## On crash / interruption recovery

If you receive control mid-session and `window.__compCSV` is empty but `localStorage.__compCSV_backup` exists:

```js
window.__compCSV = JSON.parse(localStorage.getItem('__compCSV_backup') || '[]');
window.__propertyAddresses = JSON.parse(localStorage.getItem('__propAddrs_backup') || '[]');
window.__propertyCount = window.__propertyAddresses.length;
```

Then continue from Step 6 onward.
