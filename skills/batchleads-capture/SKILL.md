---
name: batchleads-capture
description: Extract comp data points from the BatchLeads Comparables tab exactly as displayed. Use when capturing comps, reading the comp table, or extracting comp rows from a property page.
---

# BatchLeads Capture

Your only job is to read every comp row on the visible Comparables tab and store it on `window.__compCSV`. Navigation, pagination, CSV building, and memory are separate skills.

## Prereqs

Inject `scripts/helpers.js` once per session. The comp table must already be rendered on screen (`batchleads-navigation` opens the tab).

## Required fields — capture for EVERY comp

- Address (full: street + city + state + zip)
- **ZIP CODE** — mandatory; the entire output is useless without it
- Sale Price
- Price Per Square Foot
- Square Footage
- Bedrooms
- Bathrooms
- Year Built
- Lot Size
- Days on Market
- Date Sold
- Subdivision
- Property Type
- MLS Status

## Critical rule: ZIP comes from the dedicated column

Do **NOT** parse ZIP from the address string. The "Property Address" cell contains only the street (e.g. `"721 Baca St"`) — there is no ZIP in it. Regex like `addr.match(/\b\d{5}\b/g)` will either return empty or grab a 5-digit street number (`"10430"`).

The comp table has separate columns:
- `Property Address` → street only
- `City`
- `State`
- `Zip`
- `MLS Status`

Build the full address as: `street + ", " + city + ", " + state + " " + zip`.

`window.__extractCompsFromPage()` already does this correctly — call it, do not reinvent it.

## Rules

1. Call `window.__extractCompsFromPage()` for each page. It returns an array of row objects with the schema above.
2. `__captureCurrentProperty()` (in `batchleads-navigation`) already calls this for every page and concatenates onto `window.__compCSV`. You normally never call `__extractCompsFromPage` directly — the navigation skill handles it.
3. If a cell is blank or shows `"-"`, leave it as `""`. Do not fill, guess, or substitute placeholders.
4. Do not interpret, calculate, or transform values (no parsing prices to numbers, no normalizing dates, no inferring bath counts).
5. Do not filter comps by price, size, distance, or any other criteria. Capture every row.
6. Do not add subject-property data to the comp rows. The subject row uses different markup and is naturally excluded by reading only `tbody tr`. If you ever see duplication, filter rows whose address matches the subject.
7. Do not sort or reorder. Preserve the order rows appear in the DOM.
8. Header is "MLS Status", not "Status". `__extractCompsFromPage` already handles this — if you add new fields, match the header text exactly.

## Verifying ZIP coverage during a run

After every batch:

```js
window.__compCSV.filter(r => !r.zip).length
```

Expected: `0`. If non-zero, stop and investigate column indices before continuing — `Known Pitfalls` in `session-memory.md` documents the 2026-05-26 fix that achieved 100% ZIP coverage.
