# Standalone Chrome Extension Prompt

This is the **single self-contained prompt** to paste into Claude for Chrome when you want to run a BatchLeads scraping session. No GitHub fetch required — everything Claude needs is inline.

**Workflow:**
1. Open BatchLeads in Chrome, log in, navigate to the property you want scraping to begin from.
2. Open the Claude for Chrome extension on that tab.
3. Copy everything between the `=== COPY BELOW ===` and `=== COPY ABOVE ===` markers.
4. Paste into Claude for Chrome and send. Tell Claude how many properties to scrape when asked.

---

=== COPY BELOW ===

You are running a BatchLeads comparables scraper. I am on a BatchLeads property page in this tab, already logged in. Drive the entire scrape end-to-end with minimal questions. Follow every rule below exactly. Do not deviate.

## STEP 1 — Ask me ONE question

Ask me exactly: "How many properties should I process this session?" Wait for my answer. If I say "all" or give no number, default to 250.

## STEP 2 — Inject helpers (use javascript_tool, ONE call, paste this entire block)

```javascript
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
  const idx = { address: headers.indexOf('Property Address'), city: headers.indexOf('City'), state: headers.indexOf('State'), zip: headers.indexOf('Zip'), price: headers.indexOf('Price'), pricePerSqft: headers.indexOf('Price/SqFt'), sqft: headers.indexOf('SqFt'), beds: headers.indexOf('Beds'), bath: headers.indexOf('Bath'), year: headers.indexOf('Year Built'), lot: headers.indexOf('Lot SqFt'), dom: headers.indexOf('Days On Market'), date: headers.indexOf('Date'), subdivision: headers.indexOf('Subdivision'), type: headers.indexOf('Property Type'), status: headers.indexOf('MLS Status') };
  const rows = Array.from(table.querySelectorAll('tbody tr'));
  const c = v => (v === undefined || v === '-' || v === null) ? '' : v;
  return rows.map(r => {
    const cells = Array.from(r.querySelectorAll('td')).map(x => x.innerText.trim());
    const street = c(cells[idx.address]), city = c(cells[idx.city]), state = c(cells[idx.state]), zip = c(cells[idx.zip]);
    const address = [street, city && (', ' + city), state && (', ' + state), zip && (' ' + zip)].filter(Boolean).join('');
    return { address, street, city, state, zip, price: c(cells[idx.price]), pricePerSqft: c(cells[idx.pricePerSqft]), sqft: c(cells[idx.sqft]), beds: c(cells[idx.beds]), bath: c(cells[idx.bath]), year: c(cells[idx.year]), lot: c(cells[idx.lot]), dom: c(cells[idx.dom]), date: c(cells[idx.date]), subdivision: c(cells[idx.subdivision]), type: c(cells[idx.type]), status: idx.status >= 0 ? c(cells[idx.status]) : '' };
  });
};
window.__getCompPagination = function () {
  const pags = document.querySelectorAll('.pagination');
  for (const p of pags) if (p.innerText.includes('»') && p.innerText.includes('1')) return p;
  return null;
};
window.__clickComparablesTab = async function () {
  const tabs = document.querySelectorAll('a, button, [role="tab"]');
  for (const t of tabs) if ((t.innerText || '').trim() === 'Comparables') { t.click(); await new Promise(r => setTimeout(r, 2500)); return 'clicked'; }
  return 'not found';
};
window.__clickNextProperty = function () {
  const btns = document.querySelectorAll('button.active-navigation');
  let right = null;
  btns.forEach(b => { if (b.getBoundingClientRect().left > 500) right = b; });
  if (right) { right.click(); return 'clicked'; }
  return 'not found';
};
window.__captureCurrentProperty = async function () {
  let a = 0;
  while (a < 20) { const t = window.__findCompTable(); if (t && t.querySelectorAll('tbody tr').length > 0) break; await new Promise(r => setTimeout(r, 500)); a++; }
  let total = 0, pageNum = 1;
  const p1 = window.__extractCompsFromPage();
  window.__compCSV = window.__compCSV.concat(p1); total += p1.length;
  for (let i = 0; i < 9; i++) {
    const pag = window.__getCompPagination(); if (!pag) break;
    const next = Array.from(pag.querySelectorAll('a')).find(el => el.getAttribute('aria-label') === 'Next'); if (!next) break;
    const li = next.closest('li'); if (li && li.classList.contains('disabled')) break;
    next.click(); await new Promise(r => setTimeout(r, 1800));
    const pd = window.__extractCompsFromPage(); if (pd.length === 0) break;
    window.__compCSV = window.__compCSV.concat(pd); total += pd.length; pageNum++;
  }
  return { pages: pageNum, comps: total };
};
window.__processBatch = async function (count) {
  const out = [];
  for (let i = 0; i < count; i++) {
    try {
      window.__clickNextProperty();
      await new Promise(r => setTimeout(r, 3500));
      let r = await window.__clickComparablesTab();
      if (r !== 'clicked') { await new Promise(r => setTimeout(r, 2500)); r = await window.__clickComparablesTab(); }
      if (r !== 'clicked') {
        out.push({ err: 'no comp tab' });
        window.__propertyCount++;
        window.__propertyAddresses.push({ prop: window.__propertyCount, err: 'no comp tab' });
        try { localStorage.setItem('__compCSV_backup', JSON.stringify(window.__compCSV)); localStorage.setItem('__propAddrs_backup', JSON.stringify(window.__propertyAddresses)); } catch (e) {}
        continue;
      }
      const res = await window.__captureCurrentProperty();
      window.__propertyCount++;
      window.__propertyAddresses.push({ prop: window.__propertyCount, comps: res.comps, pages: res.pages });
      out.push(res);
      try { localStorage.setItem('__compCSV_backup', JSON.stringify(window.__compCSV)); localStorage.setItem('__propAddrs_backup', JSON.stringify(window.__propertyAddresses)); } catch (e) {}
    } catch (e) { out.push({ err: e.message }); }
  }
  return out;
};
window.__buildCSV = function () {
  const h = ['Address','Zip','Sale Price','Price Per Square Foot','Square Footage','Bedrooms','Bathrooms','Year Built','Lot Size','Days on Market','Date Sold','Subdivision','Property Type','MLS Status'];
  const esc = v => { if (v == null) return ''; const s = String(v); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
  const seen = new Set(), rows = [];
  for (const r of window.__compCSV) {
    if (!r.address || !r.address.trim()) continue;
    const k = [r.address, r.date, r.price, r.sqft].join('|');
    if (seen.has(k)) continue;
    seen.add(k); rows.push(r);
  }
  const lines = [h.join(',')];
  for (const r of rows) lines.push([r.address,r.zip,r.price,r.pricePerSqft,r.sqft,r.beds,r.bath,r.year,r.lot,r.dom,r.date,r.subdivision,r.type,r.status].map(esc).join(','));
  return lines.join('\n');
};
window.__emergencyBackup = function (reason) {
  try { localStorage.setItem('__compCSV_backup', JSON.stringify(window.__compCSV)); localStorage.setItem('__propAddrs_backup', JSON.stringify(window.__propertyAddresses)); localStorage.setItem('__emergencyReason', String(reason || 'unspecified')); } catch (e) {}
  try {
    const csv = window.__buildCSV();
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'comparables_emergency_' + new Date().toISOString().replace(/[:.]/g, '-') + '.csv';
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
  } catch (e) {}
  return 'backed up: ' + (reason || 'unspecified');
};
window.__startCrashWatchdog = function () {
  if (window.__watchdogTimer) clearInterval(window.__watchdogTimer);
  let last = window.__compCSV.length, lastChange = Date.now();
  window.__watchdogTimer = setInterval(() => {
    if (window.__compCSV.length !== last) { last = window.__compCSV.length; lastChange = Date.now(); return; }
    if (Date.now() - lastChange > 120000) { window.__emergencyBackup('watchdog stall'); lastChange = Date.now(); }
  }, 15000);
  return 'watchdog armed';
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
'helpers injected; existing rows: ' + window.__compCSV.length;
```

Then immediately: `window.__startCrashWatchdog();`

## STEP 3 — Capture the first property

```javascript
await window.__clickComparablesTab();
await window.__captureCurrentProperty();
```

## STEP 4 — Main loop (repeat until property count reached)

For each batch of 20 (or fewer if remaining):

a) Launch the async batch — DO NOT await:
```javascript
window.__lastBatch = null;
window.__processBatch(20).then(r => { window.__lastBatch = r; });
'batch started';
```

b) Use `browser_batch` with **10 sequential `{action:"wait", duration:10}` entries**. This is the fastest pattern — never round-trip per click.

c) Poll:
```javascript
({ done: window.__lastBatch !== null, comps: window.__compCSV.length, props: window.__propertyCount })
```

d) If `done: false`, do another 10 waits. Repeat until done.

e) Do NOT summarize or pause between batches. Reset `window.__lastBatch = null;` and continue immediately.

## STEP 5 — Stop conditions

Stop when ANY of these is true:
- The property count I gave you is reached.
- Three consecutive batches return only errors.
- You sense session credits are running low.

## STEP 6 — Final download (only after all batches done)

a) Verify ZIP coverage:
```javascript
({ missingZip: window.__compCSV.filter(r => !r.zip).length, total: window.__compCSV.length })
```

b) If `missingZip > 0`, STOP and report. Do not download.

c) If all zips present:
```javascript
clearInterval(window.__watchdogTimer);
window.__downloadFinalCSV();
```

This triggers a normal Chrome download — `comparables_data.csv` lands in my Downloads folder. **This is the ONLY non-emergency download in the session.**

## STEP 7 — Print the memory update (last thing you do)

Print a single markdown code block I can copy. Format exactly:

```markdown
- **YYYY-MM-DD**, ~XX minutes: N properties processed, M comp rows captured (after dedupe; RAW raw before dedupe). 100% ZIP coverage. Method: in-page async `__processBatch` with `browser_batch` 10s wait chains. <any errors or improvements>.
```

Tell me: "Copy the block above and paste it under `## Session Log` in `skills/memory/session-memory.md`, or hand it to Claude Code on the web to commit."

## HARD RULES (apply throughout — non-negotiable)

1. **ZIP CODES ARE MANDATORY.** Never deliver a CSV with missing zips. ZIP comes from the dedicated Zip column — NEVER parse from the address string (street numbers like "10430" will false-match a 5-digit regex).
2. **Never export through the BatchLeads UI.** Always use the in-page Blob download.
3. **Never scroll, never screenshot during the main loop.** The DOM is fully readable via `javascript_tool`.
4. **Never pause between properties.** No commentary, no summaries until session end.
5. **The only downloads during a session are:** (a) the final `comparables_data.csv` in STEP 6, and (b) automatic emergency backups from the watchdog if a 2-minute stall is detected. Nothing else.
6. **The comp table has separate columns** for Address (street only), City, State, Zip, and MLS Status. Build the full address as `street + ", " + city + ", " + state + " " + zip`.
7. **Find the comp table by content** (a `<table>` containing both "Price/SqFt" AND "Property Address"). Never by index — it shifts.
8. **There are two `.pagination` elements** on the page. The comp pagination is the one containing `»`. The helpers already pick the right one.
9. **The "Next Property" button** has no aria-label and no inline text — it is `button.active-navigation` with `getBoundingClientRect().left > 500`. The helpers already pick the right one.
10. **Many properties at the end of the list have only 1 comp** — this is normal list-end sparseness, not a bug. Keep going.
11. **The renderer can transiently freeze for 30–60 seconds** during long batches. Just wait it out — per-property checkpointing means no data is lost.
12. **Same comp can appear under multiple subject properties.** Dedupe on `address+date+price+sqft` happens automatically inside `__buildCSV()`.
13. **If `window.__compCSV` is empty but `localStorage.__compCSV_backup` exists**, restore it:
```javascript
window.__compCSV = JSON.parse(localStorage.getItem('__compCSV_backup') || '[]');
window.__propertyAddresses = JSON.parse(localStorage.getItem('__propAddrs_backup') || '[]');
window.__propertyCount = window.__propertyAddresses.length;
```
Then resume from STEP 4.

## TIMINGS (minimums, do not shorten — already baked into the helpers)

- 3.5s after `__clickNextProperty()` before clicking Comparables
- 2.5s after `__clickComparablesTab()`
- 1.8s between comp pagination clicks

Begin with STEP 1.

=== COPY ABOVE ===
