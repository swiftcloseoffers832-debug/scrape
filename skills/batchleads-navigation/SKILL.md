---
name: batchleads-navigation
description: Navigate BatchLeads property pages and access the Comparables tab. Use when scraping comparables, processing the BatchLeads property list, or moving between properties with the Next Property button.
---

# BatchLeads Navigation

Your only job is to drive the browser through BatchLeads property pages and surface the Comparables tab for capture. Capture, CSV building, and memory are separate skills.

## Prereqs

Inject `scripts/helpers.js` once per session before running this skill via `mcp__playwright__browser_evaluate`. All actions here rely on the `window.__*` helpers it defines.

For Claude Code on the web, prefer the `/scrape` slash command — it orchestrates this skill (plus capture, CSV, memory) end-to-end without manual driving.

## Rules

1. You start on a BatchLeads property page. Do not log in, do not search — that's the user's setup.
2. Click the Comparables tab via `window.__clickComparablesTab()`. The function waits 2.5s after clicking for the table to render.
3. Wait for the comp table to appear before doing anything else. `window.__findCompTable()` returns the element by content match (it contains both "Price/SqFt" and "Property Address") — the table index in the DOM shifts, so never hard-code it.
4. If the table does not appear within ~10s, refresh the page and try once more.
5. Walk every page of comps using `window.__captureCurrentProperty()`. That helper handles pagination internally: up to 10 pages, 10 comps per page, 1.8s between page clicks. It stops automatically when the Next pagination link is disabled or the next page is empty.
6. There are two `.pagination` elements on the page. The comp pagination is the one containing `»`. `window.__getCompPagination()` picks the right one — do not select by index.
7. Advance to the next property with `window.__clickNextProperty()`. The Next Property button is `button.active-navigation` with `getBoundingClientRect().left > 500` (it has no aria-label and no inline text — the tooltip appears on hover only).
8. If a property has no comparables, skip it immediately and continue. `__processBatch` records `{err: 'no comp tab'}` for that property and moves on.
9. Do not stop, summarize, analyze, or pause between properties unless a checkpoint is triggered by `batchleads-session`.
10. Never scroll. Never screenshot. The DOM is fully readable via `mcp__playwright__browser_evaluate` even when off-screen.

## Minimum reliable timings (do not shorten)

- 2.5–3.5s after `__clickNextProperty()` before clicking Comparables
- 2.5s after `__clickComparablesTab()` (built into the helper)
- 1.8s between comp pagination clicks (built into `__captureCurrentProperty`)

## What this skill does NOT do

- Does not extract or transform data → see `batchleads-capture`
- Does not build the CSV → see `batchleads-csv`
- Does not drive the batch loop → see `batchleads-session`
