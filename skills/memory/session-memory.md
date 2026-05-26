# comp scraper memory

Last Updated: 2026-05-26

## Current Best Method

- Inject all helper functions once into `window` namespace via `scripts/helpers.js`.
- Use `window.__processBatch(20)` for batches, then `browser_batch` with 10 sequential `{action:"wait", duration:10}` entries to let the async loop run.
- Poll `window.__lastBatch` and `window.__compCSV.length` to detect completion.
- Save checkpoints to `localStorage` every batch (continuous backup also runs after each property inside `__processBatch`).
- Filter empty-address rows and dedupe on `address+date+price+sqft` before final CSV build.
- Final CSV via `Blob + a.click()` download — never use BatchLeads export.
- ZIP and Status come from dedicated table columns, NOT parsed from the address string.
- The comp table has separate columns: `Property Address`, `City`, `State`, `Zip`, and `MLS Status`.
- Build full address as: `street + ", " + city + ", " + state + " " + zip`.
- Status maps from the `MLS Status` column (e.g. "Off Market", "Failed", etc.).
- Imminent-crash backup: `window.__emergencyBackup(reason)` writes a JSON snapshot to localStorage AND forces an immediate CSV download with timestamp in filename.
- A watchdog timer (`window.__startCrashWatchdog`) monitors progress and auto-triggers the backup if no new comps arrive for 2 min while a batch is running.

## Session Log

- **2026-05-25**, ~30 batches of waits across 13 property batches: 261 properties, 3,750 comps captured. Method: in-page async loop with `browser_batch` 10s waits. Very efficient. No major errors. ~6 properties had no Comparables tab and were skipped automatically.
- **2026-05-25 (manual close-out)**, ~4 batches of 20-25 each: 94 properties processed, 2,068 comp rows captured (after empty-address filter). Method: in-page async `__processBatch` with `browser_batch` 10s wait chains; checkpoint to localStorage between batches. No errors. Session ended manually mid-batch-5; final state recovered cleanly from `window.__compCSV` and downloaded via Blob/a.click(). Confirms list-end sparseness: properties 45-61 had mostly 1 comp each.
- **2026-05-26**, 13 batches of 20 properties each: 261 properties processed, 3,377 unique comp rows (after dedupe; 4,300 raw before dedupe). 100% ZIP and 100% MLS Status coverage. Method: in-page async `__processBatch` with `browser_batch` 10s wait chains. One transient renderer freeze mid-batch-13 (~45s CDP timeout); recovered cleanly after waits, no data lost. Added imminent-crash backup (`__emergencyBackup`) and a watchdog timer that auto-triggers on 2-min progress stall. Continuous per-property localStorage checkpointing added inside `__processBatch` loop.

## Known Pitfalls

- Comp table index shifts — always find by content (`Price/SqFt` + `Property Address`).
- Two `.pagination` elements exist — pick the one with `»`.
- NEXT PROPERTY button has no aria-label/text — identify by `button.active-navigation` with `rect.left > 500`.
- Many late properties in the list have only 1 comp — likely list-end sparseness, not a bug.
- Mid-batch manual cancellation is safe — `window.__compCSV` is updated row-by-row as the async loop runs, so partial-batch data is preserved.
- DO NOT parse ZIP from the address string — the `Property Address` cell only contains street ("721 Baca St"), not the full address. The Zip column is column index 5 in the comp table. The previous fix that used `addr.match(/\b\d{5}\b/g)` returned empty strings or false matches (e.g. "10430" street number). Always read the dedicated Zip + City + State columns.
- Status header is `MLS Status`, not `Status` — watch for column naming when adding new fields.
- Renderer can transiently freeze (~30-60s CDP timeout) during long batches — just wait it out, data is preserved via per-property localStorage checkpointing.
- Same comp can appear under multiple subject properties — dedupe on `address+date+price+sqft` before final CSV build to avoid inflating the row count (raw 4,300 → dedupe 3,377 in 2026-05-26 session).
- **ZIP CODES ARE MANDATORY** — the whole file is useless without them. The 2026-05-26 fix ensures 100% ZIP coverage by reading the dedicated Zip column rather than parsing the address.
