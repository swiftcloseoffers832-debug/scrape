// BatchLeads Comparables Scraper — shared in-page helpers.
// Inject once per browser session before running any skill.
// All state is attached to window.__* so skills can read/write it across calls.

// ---------------------------------------------------------------------------
// 1. Storage
// ---------------------------------------------------------------------------
window.__compCSV = window.__compCSV || [];
window.__propertyAddresses = window.__propertyAddresses || [];
window.__propertyCount = window.__propertyCount || 0;
window.__lastBatch = window.__lastBatch || null;

// ---------------------------------------------------------------------------
// 2. Find the comp table by content (index shifts — never hard-code)
// ---------------------------------------------------------------------------
window.__findCompTable = function () {
  const tables = document.querySelectorAll('table');
  for (let i = 0; i < tables.length; i++) {
    const txt = tables[i].innerText;
    if (txt.includes('Price/SqFt') && txt.includes('Property Address')) return tables[i];
  }
  return null;
};

// ---------------------------------------------------------------------------
// 3. Extract comps from the current page.
// ZIP / City / State / MLS Status come from dedicated columns — never parsed
// from the address string.
// ---------------------------------------------------------------------------
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
      address: fullAddress,
      street: street,
      city: city,
      state: state,
      zip: zip,
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

// ---------------------------------------------------------------------------
// 4. Comp-table pagination — pick the one containing »
// ---------------------------------------------------------------------------
window.__getCompPagination = function () {
  const pags = document.querySelectorAll('.pagination');
  for (const p of pags) {
    if (p.innerText.includes('»') && p.innerText.includes('1')) return p;
  }
  return null;
};

// ---------------------------------------------------------------------------
// 5. Click the Comparables tab
// ---------------------------------------------------------------------------
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

// ---------------------------------------------------------------------------
// 6. Click NEXT PROPERTY — button.active-navigation on the right edge
// ---------------------------------------------------------------------------
window.__clickNextProperty = function () {
  const navBtns = document.querySelectorAll('button.active-navigation');
  let rightBtn = null;
  navBtns.forEach(b => {
    if (b.getBoundingClientRect().left > 500) rightBtn = b;
  });
  if (rightBtn) { rightBtn.click(); return 'clicked'; }
  return 'not found';
};

// ---------------------------------------------------------------------------
// 7. Capture every comp page for the current property
// ---------------------------------------------------------------------------
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

// ---------------------------------------------------------------------------
// 8. Batch process N properties — the workhorse loop
// ---------------------------------------------------------------------------
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
        } catch (e) { /* quota — ignore */ }
        continue;
      }
      const result = await window.__captureCurrentProperty();
      window.__propertyCount++;
      window.__propertyAddresses.push({ prop: window.__propertyCount, comps: result.comps, pages: result.pages });
      results.push(result);
      try {
        localStorage.setItem('__compCSV_backup', JSON.stringify(window.__compCSV));
        localStorage.setItem('__propAddrs_backup', JSON.stringify(window.__propertyAddresses));
      } catch (e) { /* quota — ignore */ }
    } catch (e) {
      results.push({ err: e.message });
    }
  }
  return results;
};

// ---------------------------------------------------------------------------
// 9. CSV builder. Header order is fixed per SKILL 3 spec.
// Dedupe on address+date+price+sqft; drop rows with no address.
// ---------------------------------------------------------------------------
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

// ---------------------------------------------------------------------------
// 10. Imminent-crash backup: JSON to localStorage + immediate CSV download
// ---------------------------------------------------------------------------
window.__emergencyBackup = function (reason) {
  try {
    localStorage.setItem('__compCSV_backup', JSON.stringify(window.__compCSV));
    localStorage.setItem('__propAddrs_backup', JSON.stringify(window.__propertyAddresses));
    localStorage.setItem('__emergencyReason', String(reason || 'unspecified'));
  } catch (e) { /* quota — ignore */ }
  try {
    const csv = window.__buildCSV();
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    const ts = new Date().toISOString().replace(/[:.]/g, '-');
    a.download = 'comparables_emergency_' + ts + '.csv';
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
  } catch (e) { /* download failed — localStorage still has data */ }
  return 'backed up: ' + (reason || 'unspecified');
};

// ---------------------------------------------------------------------------
// 11. Watchdog — auto-trigger emergency backup if no new comps for 2 min
// ---------------------------------------------------------------------------
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
      lastChange = Date.now(); // avoid retriggering immediately
    }
  }, 15000);
  return 'watchdog started (stall threshold ' + limit + 'ms)';
};

// ---------------------------------------------------------------------------
// 12. Final download — call after the last batch
// ---------------------------------------------------------------------------
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

// ---------------------------------------------------------------------------
// 13. Return the final CSV as a string. Preferred path for Claude Code on
// the web: Claude pulls the string out via browser_evaluate, then writes it
// to the container filesystem and delivers it to the user as a chat file.
// Non-destructive: does not mutate window.__compCSV.
// ---------------------------------------------------------------------------
window.__getCSV = function () {
  return {
    csv: window.__buildCSV(),
    rows: window.__compCSV.filter(r => r.address && r.address.trim() !== '').length,
    properties: window.__propertyCount,
    zipCoverage: window.__compCSV.length === 0
      ? 0
      : window.__compCSV.filter(r => r.zip && r.zip.trim() !== '').length / window.__compCSV.length
  };
};
