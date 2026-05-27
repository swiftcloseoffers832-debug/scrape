# SwiftClose Offers — Deterministic Comp Engine

This repo contains the **only** path to a SwiftClose comp number.

The math lives in `comp_engine.py`. The analyst (LLM) never calculates
or estimates an offer itself — it loads data, calls the engine, and
reads the result back. If the engine does not return a number, the
analyst returns `DATA NOT FOUND`. Numbers come from real rows run
through real math, or they do not exist.

## Files

| File | Purpose |
|---|---|
| `comp_engine.py` | Deterministic calculator. All filters, gates, math. Tunable parameters live at the top of the file. |
| `comp_run_log.csv` | Auto-created on first run. One row per call: subject, comps found/used, spread, status, and numbers (or no-number reason). |
| `analyst_notes.md` | Human-maintained facts the analyst loads at session start (e.g. "77096 needs sqft > 2000"). The engine does **not** read this. |

## How the analyst runs the engine

### From the command line

```bash
python comp_engine.py \
  --address "1234 Main St" \
  --zip 77096 \
  --beds 3 \
  --baths 2 \
  --sqft 1800 \
  --repair-level moderate \
  --data-dir .
```

The engine prints the report to stdout. Exit code `0` means a valid
offer was produced. Exit code `2` means no number — `THIN`,
`UNRELIABLE`, or `DATA NOT FOUND`. Add `--json` to also dump the full
result structure for downstream parsing.

### From Python

```python
from comp_engine import run_comp

result = run_comp(
    subject={
        "address": "1234 Main St",
        "zip": "77096",
        "beds": 3,
        "baths": 2,
        "sqft": 1800,
        "repair_level": "moderate",
    },
    data_dir=".",
)

print(result["report"])

if result["status"] == "VALID":
    use_offer(result["max_offer"], result["opening_range_low"], result["opening_range_high"])
else:
    return "DATA NOT FOUND"
```

## How the analyst reads results back

The engine always returns a dict with `status` set to one of:

- `VALID` — numbers are populated, use them as-is.
- `THIN` — fewer than 5 comps after trimming. **No number.**
- `UNRELIABLE` — spread > 30% even after IQR trim. **No number.**
- `DATA NOT FOUND` — zero comps matched, missing zip, missing sqft, or no data loaded. **No number.**

For any non-`VALID` status the analyst returns `DATA NOT FOUND` to the
user verbatim. It does not retry with looser tolerances. It does not
estimate. It does not "use judgment."

The human-readable report at `result["report"]` follows this format:

```
COMP SET STATUS: VALID
COMPS USED: 7
ARV: $325,400
MAX OFFER: $202,800
OPENING OFFER RANGE: $177,800 - $187,800
WALK AWAY ABOVE: $202,800

COMP DETAIL
  Subject: 1234 Main St  zip=77096  3.0bd/2.0ba  1800 sqft  repair=moderate
  Median $/sqft used: $180.78
  Repair $/sqft: $35.00  -> repairs $63,000
  Spread before trim: 28.4%
  Spread after trim:  18.2%
  Flagged old-but-otherwise-valid comps (excluded from math): 2

  Included comps:
    - 1100 Oak Ln  $178.50/sqft
    ...

  Trimmed as outliers:
    - 9000 Far Out Rd  $310.00/sqft  ($310.00/sqft above IQR fence $244.50)
    ...
```

The first 6 lines are numerical only — they are what gets quoted in
an offer. Everything below is for human audit.

## The math (fixed)

```
median_ppsf = median of price_per_sqft across kept comps
ARV         = median_ppsf * subject_sqft
repairs     = repair_ppsf * subject_sqft   (light=$20, moderate=$35, heavy=$55)
Max Offer   = ARV * 0.70 - repairs - $15,000
Opening     = Max Offer - $25,000  to  Max Offer - $15,000
Walk Away   = Max Offer
```

All dollar outputs round to the nearest $100.

## The filters (fixed)

A comp is **kept** only if:

- It is a Sold row (or a comp-export closed sale with a sale price + sold date).
- It is not flagged as refi / loan / "Last Sale Price refi".
- Same zip as subject.
- Beds within ±1 of subject.
- Baths within ±1 of subject.
- Sqft within ±20% of subject.
- Sold within the last 12 months. (Older comps are flagged and reported, but excluded from the math.)
- Has a usable $/sqft (or sale_price ÷ sqft can derive one).

Then IQR trim drops anything outside `[Q1 − 1.5·IQR, Q3 + 1.5·IQR]`.

## The gates (fixed)

| Gate | Threshold | If failed |
|---|---|---|
| Min comps after trim | < 5 | Status `THIN`, no number |
| Spread after trim | > 30% | Status `UNRELIABLE`, no number |
| Comps that matched filters | 0 | Status `DATA NOT FOUND`, no number |

## The audit log (`comp_run_log.csv`)

Every run appends one row: timestamp, subject, comps found/used,
spread before/after, status, offer numbers (or the reason there are
none).

**This log is what makes the system get better over time.** Read it,
spot patterns ("77096 is always THIN under 2000 sqft"), then update
either the parameters in `comp_engine.py` or facts in
`analyst_notes.md` — deliberately, in a commit you can review later.

## On "self-improving" / "learns as it goes"

The engine's math never self-modifies. It is a calculator;
calculators don't learn — that's why you trust them. The moment the
math could rewrite itself, the guarantee that a number came from real
data is gone, and you're back to the fabrication problem ($256K vs
$64K for the same house).

What *does* get smarter is the rule set, and only through deliberate
human edits to:

- Parameters at the top of `comp_engine.py` (repair $/sqft, match
  tolerances, IQR fence, min-comp threshold, spread cap).
- Notes in `analyst_notes.md`.

Every change is a commit; every commit is reviewable. That is the
"improvement loop you can trust."

## Data sources

The engine loads:

- Every `*.csv` in the `--data-dir`.
- Any `*.csv` anywhere under `--data-dir` whose name contains
  `comp` or `comparable` (so Google Drive-synced subfolders work).

It auto-detects common column header variants (e.g. `Sold Price` vs
`sale_price` vs `Close Price`). Rows with no zip are dropped and
counted. Rows are deduped on `(normalized_address, date_sold)` to
prevent the documented multi-row-per-sale bug.

## Tunable parameters

Edit the constants at the top of `comp_engine.py`:

```python
REPAIR_PPSF        = {"light": 20.0, "moderate": 35.0, "heavy": 55.0}
BED_TOLERANCE      = 1
BATH_TOLERANCE     = 1
SQFT_TOLERANCE_PCT = 0.20
RECENCY_DAYS       = 365
MIN_COMPS_AFTER_TRIM = 5
MAX_SPREAD_AFTER_TRIM = 0.30
ARV_DISCOUNT       = 0.70
FIXED_FEE          = 15_000
OPENING_OFFER_BUFFER_LOW  = 25_000
OPENING_OFFER_BUFFER_HIGH = 15_000
```

Change one, commit the change, watch the next week of `comp_run_log.csv`
to see whether it helped. That is how this engine gets better.
