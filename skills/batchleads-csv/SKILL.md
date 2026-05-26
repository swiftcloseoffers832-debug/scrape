---
name: batchleads-csv
description: Build and download the final comparables CSV from in-memory comp data. Use when the user asks to save, download, export, or compile the comp CSV. Never use the BatchLeads built-in export.
---

# BatchLeads CSV

Your only job is to take everything captured into `window.__compCSV` during the session and emit a single clean CSV file the user can download. Navigation, capture, and memory are separate skills.

## Prereqs

Inject `scripts/helpers.js` once per session. `window.__compCSV` must be populated by the navigation/capture skills.

## Column order (fixed)

```
Address, Zip, Sale Price, Price Per Square Foot, Square Footage, Bedrooms, Bathrooms, Year Built, Lot Size, Days on Market, Date Sold, Subdivision, Property Type, MLS Status
```

`window.__buildCSV()` emits exactly these columns in this order.

## Rules

1. One row per comp. Never group rows by subject property. Never insert subject-property rows.
2. Do not merge cells, add totals, add averages, or insert any calculated fields.
3. Do not add extra columns beyond the list above.
4. Blank cells stay empty — no `N/A`, no placeholders.
5. Continuous build: the navigation skill appends to `window.__compCSV` row-by-row, so the CSV is always current. You do not have to "compile at the end" — just call `__buildCSV()` whenever the user wants a snapshot.
6. **Filter and dedupe before download.** Drop rows with empty `address`. Dedupe on `address + date + price + sqft`. `__buildCSV()` does both — do not pre-filter `window.__compCSV` yourself or you will mutate state mid-session.
7. **Never export through the BatchLeads UI.** That costs credits and does not match the schema.

## Download

Call `window.__downloadFinalCSV()`. It:

1. Filters empty-address rows out of `window.__compCSV` (this one is destructive — only run when you actually want the final file).
2. Builds the CSV via `__buildCSV()`.
3. Creates a Blob and triggers a browser download named `comparables_data.csv`.

For mid-session snapshots without mutating state, use `__buildCSV()` directly and inspect the string.

## Emergency download

If a crash is imminent or the watchdog fires, `window.__emergencyBackup(reason)` writes JSON to `localStorage` AND immediately downloads a timestamped CSV (`comparables_emergency_<ISO>.csv`). Safe to call repeatedly.

## Recovery

If the session crashed and `window.__compCSV` is empty in a fresh page, restore from localStorage:

```js
window.__compCSV = JSON.parse(localStorage.getItem('__compCSV_backup') || '[]');
window.__propertyAddresses = JSON.parse(localStorage.getItem('__propAddrs_backup') || '[]');
```

Then build/download as normal.
