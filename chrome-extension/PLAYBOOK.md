# BatchLeads Scraper — Claude for Chrome Playbook

This is a self-contained playbook for running the BatchLeads comp scraper inside the **Claude for Chrome extension**. Claude reads this file, injects the helper JavaScript into the current BatchLeads tab, and drives the entire scraping session end-to-end. The user only needs to paste one short prompt at the start.

---

## You are Claude. Read every section below in order, then begin.

## 0. What you're doing

The user is on a BatchLeads property page in their Chrome browser, already logged in. They want you to:

1. Inject the JavaScript helpers in Section 1 into the page via `javascript_tool`.
2. Open the Comparables tab on the current property and capture every comp on every page.
3. Click "Next Property" and repeat until the user-specified count of properties is processed (or the user says stop).
4. Trigger a CSV download to their PC's Downloads folder.
5. Print a Session Log entry as a markdown block in chat — the user will copy it back into the repo manually, OR they can ask Claude Code on the web to commit it later.

## 1. Inject these helpers (run ONCE per session, before anything else)

Use `javascript_tool` to execute the following in the current page. The functions land on `window.__*` and persist across subsequent calls.

```javascript
// ---- BEGIN HELPERS — paste this entire block into javascript_tool ----
window.__compCSV = window.__compCSV || [];
window.__propertyAddresses = window.__propertyAddresses || [];
window.__propertyCount = window.__propertyCount || 0;
window.__lastBatch = window.__lastBatch || null;

window.__findCompTable = function () {
  const tables = document.querySelectorAll('table');
  for (let i = 0; i < tables.length; i++) {
    const txt = tables[i].innerText;
    if (txt.includes('Price/SqFt') && txt.includes('Property Address')) return tables[i];
  }
  return null;
};

window.__extractCompsFromPage = function () {
  const table = window.__findCompTable();
  if (!table) return [];
  const headerRow = Array.from(table.querySelectorAll('tr'))[0];
  const headers = Array.from(headerRow.querySelectorAll('th,td')).map(c => c.innerText.trim());
  const idx = {
    address: headers.indexOf('Property Address'),
    city: headers.indexOf('City'),
    state: headers.indexOf('State'),
    zip: headers.indexOf('Zip'),
    price: headers.indexOf('Price'),
    pricePerSqft: headers.indexOf('Price/SqFt'),
    sqft: headers.indexOf('SqFt'),
    beds: headers.indexOf('Beds'),
    bath: headers.indexOf('Bath'),
    year: headers.indexOf('Year Built'),
    lot: headers.indexOf('Lot SqFt'),
    dom: headers.indexOf('Days On Market'),
    date: headers.indexOf('Date'),
    subdivision: headers.indexOf('Subdivision'),
    type: headers.indexOf('Property Type'),
    status: headers.indexOf('MLS Status')
  };
  const tbodyRows = Array.from(table.querySelectorAll('tbody tr'));
  const clean = v => (v === undefined || v === '-' || v === null) ? '' : v;
  return tbodyRows.map(r => {
    const cells = Array.from(r.querySelectorAll('td')).map(c => c.innerText.trim());
    const street = clean(cells[idx.address]);
    const city = clean(cells[idx.city]);
    const state = clean(cells[idx.state]);
    const zip = clean(cells[idx.zip]);
    const fullAddress = [street, city && (', ' + city), state && (', ' + state), zip && (' ' + zip)]
      .filter(Boolean).join('');
    return {
      address: fullAddress, street, city, state, zip,
      price: clean(cells[idx.price]),
      pricePerSqft: clean(cells[idx.pricePerSqft]),
      sqft: clean(cells[idx.sqft]),
      beds: clean(cells[idx.beds]),
      bath: clean(cells[idx.bath]),
      year: clean(cells[idx.year]),
      lot: clean(cells[idx.lot]),
      dom: clean(cells[idx.dom]),
      date: clean(cells[idx.date]),
      subdivision: clean(cells[idx.subdivision]),
      type: clean(cells[idx.type]),
      status: idx.status >= 0 ? clean(cells[idx.status]) : ''
    };
  });
};

window.__getCompPagination = function () {
  const pags = document.querySelectorAll('.pagination');
  for (const p of pags) {
    if (p.innerText.includes('»') && p.innerText.includes('1')) return p;
  }
  return null;
};

window.__clickComparablesTab = async function () {
  const tabs = document.querySelectorAll('a, button, [role="tab"]');
  for (const t of tabs) {
    if ((t.innerText || '').trim() === 'Comparables') {
      t.click();
      await new Promise(r => setTimeout(r, 2500));
      return 'clicked';
    }
  }
  return 'not found';
};

window.__clickNextProperty = function () {
  const navBtns = document.querySelectorAll('button.active-navigation');
  let rightBtn = null;
  navBtns.forEach(b => {
    if (b.getBoundingClientRect().left > 500) rightBtn = b;
  });
  if (rightBtn) { rightBtn.click(); return 'clicked'; }
  return 'not found';
};

window.__captureCurrentProperty = async function () {
  let attempts = 0;
  while (attempts < 20) {
    const t = window.__findCompTable();
    if (t && t.querySelectorAll('tbody tr').length > 0) break;
    await new Promise(r => setTimeout(r, 500));
    attempts++;
  }
  let totalAdded = 0;
  let pageNum = 1;
  const page1 = window.__extractCompsFromPage();
  window.__compCSV = window.__compCSV.concat(page1);
  totalAdded += page1.length;
  for (let i = 0; i < 9; i++) {
    const pag = window.__getCompPagination();
    if (!pag) break;
    const next = Array.from(pag.querySelectorAll('a')).find(el => el.getAttribute('aria-label') === 'Next');
    if (!next) break;
    const nextLi = next.closest('li');
    if (nextLi && nextLi.classList.contains('disabled')) break;
    next.click();
    await new Promise(r => setTimeout(r, 1800));
    const pageData = window.__extractCompsFromPage();
    if (pageData.length === 0) break;
    window.__compCSV = window.__compCSV.concat(pageData);
    totalAdded += pageData.length;
    pageNum++;
  }
  return { pages: pageNum, comps: totalAdded };
};

window.__processBatch = async function (count) {
  const results = [];
  for (let i = 0; i < count; i++) {
    try {
      window.__clickNextProperty();
      await new Promise(r => setTimeout(r, 3500));
      let r = await window.__clickComparablesTab();
      if (r !== 'clicked') {
        await new Promise(r => setTimeout(r, 2500));
        r = await window.__clickComparablesTab();
      }
      if (r !== 'clicked') {
        results.push({ err: 'no comp tab' });
        window.__propertyCount++;
        window.__propertyAddresses.push({ prop: window.__propertyCount, err: 'no comp tab' });
        try {
          localStorage.setItem('__compCSV_backup', JSON.stringify(window.__compCSV));
          localStorage.setItem('__propAddrs_backup', JSON.stringify(window.__propertyAddresses));
        } catch (e) {}
        continue;
      }
      const result = await window.__captureCurrentProperty();
      window.__propertyCount++;
      window.__propertyAddresses.push({ prop: window.__propertyCount, comps: result.comps, pages: result.pages });
      results.push(result);
      try {
        localStorage.setItem('__compCSV_backup', JSON.stringify(window.__compCSV));
        localStorage.setItem('__propAddrs_backup', JSON.stringify(window.__propertyAddresses));
      } catch (e) {}
    } catch (e) {
      results.push({ err: e.message });
    }
  }
  return results;
};

window.__buildCSV = function () {
  const headers = [
    'Address', 'Zip', 'Sale Price', 'Price Per Square Foot', 'Square Footage',
    'Bedrooms', 'Bathrooms', 'Year Built', 'Lot Size', 'Days on Market',
    'Date Sold', 'Subdivision', 'Property Type', 'MLS Status'
  ];
  const escape = v => {
    if (v == null) return '';
    const s = String(v);
    return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  };
  const seen = new Set();
  const rows = [];
  for (const r of window.__compCSV) {
    if (!r.address || !r.address.trim()) continue;
    const key = [r.address, r.date, r.price, r.sqft].join('|');
    if (seen.has(key)) continue;
    seen.add(key);
    rows.push(r);
  }
  const lines = [headers.join(',')];
  for (const r of rows) {
    lines.push([
      r.address, r.zip, r.price, r.pricePerSqft, r.sqft,
      r.beds, r.bath, r.year, r.lot, r.dom,
      r.date, r.subdivision, r.type, r.status
    ].map(escape).join(','));
  }
  return lines.join('\n');
};

window.__emergencyBackup = function (reason) {
  try {
    localStorage.setItem('__compCSV_backup', JSON.stringify(window.__compCSV));
    localStorage.setItem('__propAddrs_backup', JSON.stringify(window.__propertyAddresses));
    localStorage.setItem('__emergencyReason', String(reason || 'unspecified'));
  } catch (e) {}
  try {
    const csv = window.__buildCSV();
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    const ts = new Date().toISOString().replace(/[:.]/g, '-');
    a.download = 'comparables_emergency_' + ts + '.csv';
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
  } catch (e) {}
  return 'backed up: ' + (reason || 'unspecified');
};

window.__startCrashWatchdog = function (stallMs) {
  if (window.__watchdogTimer) clearInterval(window.__watchdogTimer);
  const limit = stallMs || 120000;
  let lastCount = window.__compCSV.length;
  let lastChange = Date.now();
  window.__watchdogTimer = setInterval(() => {
    if (window.__compCSV.length !== lastCount) {
      lastCount = window.__compCSV.length;
      lastChange = Date.now();
      return;
    }
    if (Date.now() - lastChange > limit) {
      window.__emergencyBackup('watchdog: stalled for ' + limit + 'ms');
      lastChange = Date.now();
    }
  }, 15000);
  return 'watchdog started';
};

window.__downloadFinalCSV = function () {
  window.__compCSV = window.__compCSV.filter(r => r.address && r.address.trim() !== '');
  const csv = window.__buildCSV();
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'comparables_data.csv';
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  return 'downloaded ' + window.__compCSV.length + ' rows';
};

'helpers injected; __compCSV length: ' + window.__compCSV.length;
// ---- END HELPERS ----
```

After injecting, start the watchdog:

```javascript
window.__startCrashWatchdog();
```

## 2. Capture the first property

```javascript
await window.__clickComparablesTab();
await window.__captureCurrentProperty();
```

## 3. Main batch loop

For each batch (size 20, or whatever the user requested):

1. **Launch the in-page async loop** (do not await — it runs detached):
   ```javascript
   window.__lastBatch = null;
   window.__processBatch(20).then(r => { window.__lastBatch = r; });
   'batch started';
   ```

2. **Wait in long chunks.** Use `browser_batch` with 8–12 sequential `{action:"wait", duration:10}` entries. This is the fastest pattern — round-tripping per-click is wasteful.

3. **Poll for completion:**
   ```javascript
   ({ done: window.__lastBatch !== null, comps: window.__compCSV.length, props: window.__propertyCount })
   ```
   Add more 10s waits if `done: false`.

4. **Checkpoint silently** — `__processBatch` already mirrors to `localStorage` after every property. Do not summarize or pause between batches.

5. Reset `window.__lastBatch = null` and start the next batch.

### Stop conditions
- User-requested property count reached
- You estimate remaining credits cannot finish another property cleanly
- Three consecutive batches return only errors

## 4. Download the final CSV (to the user's PC)

```javascript
window.__compCSV.filter(r => !r.zip).length; // must be 0; if not, STOP and report
```

If ZIP coverage is 100%:

```javascript
clearInterval(window.__watchdogTimer);
window.__downloadFinalCSV();
```

This triggers a normal Chrome download — `comparables_data.csv` lands in the user's Downloads folder.

## 5. Print the memory update for the user

After download, print a markdown block in chat that the user can copy into the repo. Format:

```markdown
- **<YYYY-MM-DD>**, <approx session length>: <N> properties processed, <M> comp rows captured (after dedupe; <RAW> raw before dedupe). <PCT>% ZIP coverage. Method: in-page async `__processBatch` with `browser_batch` 10s wait chains. <ANY ERRORS OR NOTES>.
```

If a new pitfall was hit, add a line for it. If a faster method was discovered, describe it.

Tell the user:

> Copy the block above. Paste it under `## Session Log` in `skills/memory/session-memory.md` on the repo, OR open Claude Code on the web and tell it "add this session log entry and push" — it will commit and push for you.

## 6. Hard rules (apply throughout)

- **NEVER export through the BatchLeads UI** — costs credits, wrong schema.
- **ZIP codes are mandatory.** Never deliver a CSV with missing ZIPs. ZIP comes from the dedicated Zip column — never parsed from the address string.
- **Never scroll, never screenshot during the main loop.** Both cost time and credits.
- **Don't pause between properties** unless a checkpoint (every 250 comps) is hit or a stop condition fires.
- **Watchdog stays armed** until Step 4. If it fires, an emergency CSV downloads automatically — recover and continue if possible.

## 7. Recovery from crash

If `window.__compCSV` is empty but `localStorage.__compCSV_backup` exists:

```javascript
window.__compCSV = JSON.parse(localStorage.getItem('__compCSV_backup') || '[]');
window.__propertyAddresses = JSON.parse(localStorage.getItem('__propAddrs_backup') || '[]');
window.__propertyCount = window.__propertyAddresses.length;
```

Then continue from Step 3.

---

## Persistent memory (apply Current Best Method, treat Known Pitfalls as hard constraints)

### Current Best Method

- Inject helpers once into `window` namespace.
- `window.__processBatch(20)` for batches; `browser_batch` 10s wait chains for async settling; poll `window.__lastBatch` and `window.__compCSV.length`.
- Per-property localStorage checkpoint (built into `__processBatch`).
- Dedupe on `address+date+price+sqft` before final CSV.
- Final CSV via Blob + `a.click()` download — never BatchLeads export.
- ZIP, City, State, MLS Status from dedicated columns — never parsed from address.
- Build full address as `street + ", " + city + ", " + state + " " + zip`.
- Watchdog (`__startCrashWatchdog`) auto-triggers `__emergencyBackup` on 2-min stall.

### Known Pitfalls

- Comp table index shifts — find by content (`Price/SqFt` + `Property Address`).
- Two `.pagination` elements — pick the one with `»`.
- NEXT PROPERTY button has no aria-label/text — `button.active-navigation` with `rect.left > 500`.
- Many late properties have only 1 comp — list-end sparseness, not a bug.
- Mid-batch cancellation is safe — `__compCSV` updates row-by-row.
- **DO NOT parse ZIP from the address string** — `Property Address` cell contains street only; use the dedicated Zip column.
- Header is `MLS Status`, not `Status`.
- Renderer can transiently freeze (~30–60s CDP timeout) — just wait it out; data is preserved.
- Same comp can appear under multiple subject properties — dedupe before final CSV.
- **ZIP CODES ARE MANDATORY** — file is useless without them.
