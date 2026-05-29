"""
BatchLeads Comparables Scraper
Runs a persistent Chromium browser session; the user logs in manually once,
then the bot takes over and scrapes all comp data automatically.
"""

import asyncio
import csv
import io
import json
import logging
import os
import time
from pathlib import Path
from playwright.async_api import async_playwright, Page, BrowserContext

log = logging.getLogger("scraper")

# ── helper JS injected once per session ──────────────────────────────────────

HELPERS_JS = r"""
window.__compCSV = window.__compCSV || [];
window.__propertyAddresses = window.__propertyAddresses || [];
window.__propertyCount = window.__propertyCount || 0;
window.__processedPids = window.__processedPids || new Set(
    JSON.parse(localStorage.getItem('__processedPids_backup') || '[]')
);

window.__findCompTable = function() {
    const tables = document.querySelectorAll('table');
    for (let i = 0; i < tables.length; i++) {
        const txt = tables[i].innerText;
        if (txt.includes('Price/SqFt') && txt.includes('Property Address')) return tables[i];
    }
    return null;
};

window.__extractCompsFromPage = function() {
    const table = window.__findCompTable();
    if (!table) return [];
    const headerRow = Array.from(table.querySelectorAll('tr'))[0];
    const headers = Array.from(headerRow.querySelectorAll('th,td')).map(c => c.innerText.trim());
    const idx = {
        address:     headers.indexOf("Property Address"),
        zip:         headers.indexOf("Zip"),
        price:       headers.indexOf("Price"),
        pricePerSqft:headers.indexOf("Price/SqFt"),
        sqft:        headers.indexOf("SqFt"),
        beds:        headers.indexOf("Beds"),
        bath:        headers.indexOf("Bath"),
        year:        headers.indexOf("Year Built"),
        lot:         headers.indexOf("Lot SqFt"),
        dom:         headers.indexOf("Days On Market"),
        date:        headers.indexOf("Date"),
        subdivision: headers.indexOf("Subdivision"),
        type:        headers.indexOf("Property Type")
    };
    const tbodyRows = Array.from(table.querySelectorAll('tbody tr'));
    return tbodyRows.map(r => {
        const cells = Array.from(r.querySelectorAll('td')).map(c => c.innerText.trim());
        const clean = v => (v === undefined || v === "-" || v === null) ? "" : v;
        return {
            address:      clean(cells[idx.address]),
            zip:          clean(cells[idx.zip]),
            price:        clean(cells[idx.price]),
            pricePerSqft: clean(cells[idx.pricePerSqft]),
            sqft:         clean(cells[idx.sqft]),
            beds:         clean(cells[idx.beds]),
            bath:         clean(cells[idx.bath]),
            year:         clean(cells[idx.year]),
            lot:          clean(cells[idx.lot]),
            dom:          clean(cells[idx.dom]),
            date:         clean(cells[idx.date]),
            subdivision:  clean(cells[idx.subdivision]),
            type:         clean(cells[idx.type])
        };
    });
};

window.__getCompPagination = function() {
    const pags = document.querySelectorAll('.pagination');
    for (const p of pags) {
        if (p.innerText.includes('»') && p.innerText.includes('1')) return p;
    }
    return null;
};

window.__clickComparablesTab = async function() {
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

window.__clickNextProperty = function() {
    const navBtns = document.querySelectorAll('button.active-navigation');
    let rightBtn = null;
    navBtns.forEach(b => {
        if (b.getBoundingClientRect().left > 500) rightBtn = b;
    });
    if (rightBtn) { rightBtn.click(); return 'clicked'; }
    return 'not found';
};

window.__captureCurrentProperty = async function() {
    let attempts = 0;
    while (attempts < 20) {
        const t = window.__findCompTable();
        if (t) {
            const rows = t.querySelectorAll('tbody tr');
            if (rows.length > 0 && rows[0].querySelectorAll('td').length > 2) break;
        }
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
        const next = Array.from(pag.querySelectorAll('a')).find(
            el => el.getAttribute('aria-label') === 'Next'
        );
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
    return {pages: pageNum, comps: totalAdded};
};

window.__processBatch = async function(count) {
    const results = [];
    for (let i = 0; i < count; i++) {
        try {
            const navResult = window.__clickNextProperty();
            if (navResult !== 'clicked') {
                results.push({err: 'no next button'});
                break;
            }
            await new Promise(r => setTimeout(r, 3500));

            let r = await window.__clickComparablesTab();
            if (r !== 'clicked') {
                await new Promise(r => setTimeout(r, 2500));
                r = await window.__clickComparablesTab();
            }
            if (r !== 'clicked') {
                results.push({err: 'no comp tab'});
                window.__propertyCount++;
                window.__propertyAddresses.push({prop: window.__propertyCount, err: 'no comp tab'});
                continue;
            }

            const result = await window.__captureCurrentProperty();
            window.__propertyCount++;
            window.__propertyAddresses.push({
                prop: window.__propertyCount,
                comps: result.comps,
                pages: result.pages
            });
            results.push(result);
        } catch(e) {
            results.push({err: e.message});
        }
    }
    // checkpoint
    try {
        localStorage.setItem('__compCSV_backup', JSON.stringify(window.__compCSV));
        localStorage.setItem('__propAddrs_backup', JSON.stringify(window.__propertyAddresses));
    } catch(_) {}
    return results;
};

window.__buildCSV = function() {
    const headers = [
        "Address","Zip","Sale Price","Price Per Square Foot","Square Footage",
        "Bedrooms","Bathrooms","Year Built","Lot Size","Days on Market",
        "Date Sold","Subdivision","Property Type"
    ];
    const escape = v => {
        if (v == null) return '';
        const s = String(v);
        return /[",\n]/.test(s) ? '"' + s.replace(/"/g,'""') + '"' : s;
    };
    const lines = [headers.join(',')];
    for (const row of window.__compCSV) {
        if (!row.address || row.address.trim() === '' || row.address === 'No data!') continue;
        lines.push([
            row.address, row.zip, row.price, row.pricePerSqft, row.sqft,
            row.beds, row.bath, row.year, row.lot, row.dom,
            row.date, row.subdivision, row.type
        ].map(escape).join(','));
    }
    return lines.join('\n');
};

window.__getStatus = function() {
    return {
        properties: window.__propertyCount,
        comps: window.__compCSV.length,
        lastBatch: window.__lastBatch || null,
        running: !!window.__batchRunning
    };
};
'helpers_ready';
"""

CSV_HEADERS = [
    "Address", "Zip", "Sale Price", "Price Per Square Foot", "Square Footage",
    "Bedrooms", "Bathrooms", "Year Built", "Lot Size", "Days on Market",
    "Date Sold", "Subdivision", "Property Type"
]

ROW_KEYS = [
    "address", "zip", "price", "pricePerSqft", "sqft",
    "beds", "bath", "year", "lot", "dom",
    "date", "subdivision", "type"
]


class ScraperSession:
    def __init__(self, output_dir: str = "output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.status = {
            "state": "idle",       # idle | waiting_login | running | paused | done | error
            "properties": 0,
            "comps": 0,
            "message": "Not started",
            "csv_path": None,
        }
        self._stop_requested = False
        self._pause_requested = False
        self._task: asyncio.Task | None = None
        self._playwright = None
        self._browser = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    # ── public control API ───────────────────────────────────────────────────

    def start(self, batch_size: int = 15):
        if self._task and not self._task.done():
            return
        self._stop_requested = False
        self._pause_requested = False
        loop = asyncio.get_event_loop()
        self._task = loop.create_task(self._run(batch_size))

    def pause(self):
        self._pause_requested = True
        self.status["state"] = "paused"
        self.status["message"] = "Pause requested — will stop after current batch"

    def resume(self):
        self._pause_requested = False
        self.status["state"] = "running"
        self.status["message"] = "Resumed"

    def stop(self):
        self._stop_requested = True
        self._pause_requested = False
        self.status["message"] = "Stop requested"

    def get_csv(self) -> str | None:
        """Return CSV content from the active page or from saved file."""
        if self._page:
            try:
                loop = asyncio.get_event_loop()
                csv_content = loop.run_until_complete(
                    self._page.evaluate("window.__buildCSV ? window.__buildCSV() : null")
                )
                if csv_content:
                    return csv_content
            except Exception:
                pass
        if self.status["csv_path"] and Path(self.status["csv_path"]).exists():
            return Path(self.status["csv_path"]).read_text()
        return None

    # ── internals ────────────────────────────────────────────────────────────

    def _set(self, **kw):
        self.status.update(kw)

    async def _run(self, batch_size: int):
        try:
            await self._launch_browser()
            await self._wait_for_login()
            await self._inject_helpers()
            await self._click_first_comparables_tab()
            await self._scrape_loop(batch_size)
            await self._save_csv()
            self._set(state="done", message="Scraping complete")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.exception("Scraper error")
            self._set(state="error", message=str(e))
        finally:
            await self._save_csv()

    async def _launch_browser(self):
        self._set(state="waiting_login", message="Launching browser — please log in to BatchLeads")
        self._playwright = await async_playwright().start()
        # Use persistent context so cookies survive across bot restarts
        user_data = str(self.output_dir / "browser_profile")
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=user_data,
            headless=False,
            args=["--window-size=1400,900"],
            viewport={"width": 1400, "height": 900},
        )
        pages = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()

    async def _wait_for_login(self):
        """Wait until the user is on a BatchLeads property detail/list page."""
        self._set(message="Waiting for you to log in and open a property list in BatchLeads…")
        while True:
            if self._stop_requested:
                return
            url = self._page.url
            if "batchleads" in url and ("property" in url or "list" in url or "search" in url):
                self._set(message="Login detected — ready to scrape")
                return
            await asyncio.sleep(2)

    async def _inject_helpers(self):
        result = await self._page.evaluate(HELPERS_JS)
        log.info("Helpers injected: %s", result)

    async def _click_first_comparables_tab(self):
        """Click Comparables on whichever property modal is currently open."""
        result = await self._page.evaluate("window.__clickComparablesTab()")
        if result != "clicked":
            self._set(message="Open a property detail modal first, then the bot will take over")
            # Wait until user opens one
            for _ in range(60):
                if self._stop_requested:
                    return
                result = await self._page.evaluate("window.__clickComparablesTab()")
                if result == "clicked":
                    break
                await asyncio.sleep(2)
        # Let first property's comps load
        await asyncio.sleep(3)
        result = await self._page.evaluate("window.__captureCurrentProperty()")
        props = await self._page.evaluate("window.__propertyCount + 1")
        await self._page.evaluate("window.__propertyCount = window.__propertyCount || 0; window.__propertyCount++;")
        comps = await self._page.evaluate("window.__compCSV.length")
        self._set(properties=1, comps=comps, message=f"First property captured ({comps} comps total)")

    async def _scrape_loop(self, batch_size: int):
        self._set(state="running", message="Scraping…")
        consecutive_errors = 0

        while not self._stop_requested:
            # pause support
            while self._pause_requested and not self._stop_requested:
                await asyncio.sleep(1)
            if self._stop_requested:
                break

            # Fire batch inside the page
            await self._page.evaluate(
                f"window.__batchRunning = true; "
                f"window.__processBatch({batch_size}).then(r => {{ window.__lastBatch = r; window.__batchRunning = false; }});"
            )

            # Wait for batch to complete (poll every 5s, up to 5 min)
            deadline = time.time() + 300
            while time.time() < deadline:
                await asyncio.sleep(5)
                running = await self._page.evaluate("!!window.__batchRunning")
                if not running:
                    break

            # Read results
            status = await self._page.evaluate("window.__getStatus()")
            props = status.get("properties", 0)
            comps = status.get("comps", 0)
            last_batch = status.get("lastBatch") or []
            self._set(properties=props, comps=comps,
                      message=f"{props} properties | {comps} comps captured")
            log.info("Batch done: %d props, %d comps", props, comps)

            # Detect end-of-list: last batch had a "no next button" error
            if isinstance(last_batch, list) and any(
                isinstance(r, dict) and r.get("err") == "no next button"
                for r in last_batch
            ):
                log.info("No next button — end of property list reached")
                break

            # Detect repeated errors
            batch_errors = sum(1 for r in last_batch if isinstance(r, dict) and "err" in r) if isinstance(last_batch, list) else 0
            if batch_errors == batch_size:
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    self._set(message="Too many consecutive errors — stopping")
                    break
            else:
                consecutive_errors = 0

            # Auto-checkpoint every 250 comps
            if comps % 250 < batch_size * 10:
                await self._save_csv(checkpoint=True)

    async def _save_csv(self, checkpoint: bool = False):
        try:
            csv_content = await self._page.evaluate("window.__buildCSV ? window.__buildCSV() : ''")
        except Exception:
            csv_content = ""

        if not csv_content:
            return

        label = "checkpoint" if checkpoint else "final"
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = self.output_dir / f"comparables_{label}_{ts}.csv"
        path.write_text(csv_content, encoding="utf-8")
        self._set(csv_path=str(path), message=f"CSV saved: {path.name}")
        log.info("CSV saved to %s", path)


# Singleton session shared with Flask
_session = ScraperSession()
