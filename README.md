# BatchLeads Comparables Bot

One-button automated scraper for BatchLeads comparables data.

## Quick Start

```bash
bash run_bot.sh
```

Then open **http://localhost:5000** in your browser.

## How it works

1. Click **▶ START** — a real Chromium window opens.
2. Log in to BatchLeads in that window and open a property list.
3. The bot detects you're on the right page and takes over automatically:
   - Clicks the Comparables tab on each property
   - Captures every comp row (all pages, up to 10 pages × 10 rows each)
   - Advances to the next property and repeats
4. Watch the live counter in the control panel.
5. Click **⬇ DOWNLOAD CSV** at any time to grab what's been collected so far.

## Controls

| Button | Action |
|---|---|
| ▶ START | Launch browser & begin scraping |
| ⏸ PAUSE | Finish current batch then pause |
| ▶ RESUME | Continue after a pause |
| ■ STOP | Stop after current batch & save CSV |
| ⬇ DOWNLOAD CSV | Download all captured data |

## Settings

- **Batch size** (default 15): properties processed per async loop. Increase to 20–25 for faster runs; lower if you see errors.

## Output

- CSV is auto-saved to `output/` at each checkpoint (every ~250 comps) and on stop/done.
- Download is always available from the control panel.
- Browser profile saved to `output/browser_profile/` — login cookies persist across restarts.

## Column order

```
Address, Zip, Sale Price, Price Per Square Foot, Square Footage,
Bedrooms, Bathrooms, Year Built, Lot Size, Days on Market,
Date Sold, Subdivision, Property Type
```

## Known limits

- ~400 properties / ~4,200 comp rows per continuous run (DOM memory ceiling).
- After hitting the ceiling: download CSV, reload the BatchLeads page, click START again.

## Requirements

- Python 3.10+
- Playwright + Flask (auto-installed by `run_bot.sh`)