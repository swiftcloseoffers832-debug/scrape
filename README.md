# SwiftClose — Comp Analyst System

A deterministic comp-analysis system for SwiftClose Offers (Houston-area
contract-assignment wholesaling; markets: Houston, San Antonio, Fort Worth,
Dallas, Corpus Christi). It turns a subject property into trustworthy offer
numbers from a pool of comp CSVs — and it is built so that a language model
**cannot** fabricate a number.

## THE ONE RULE

No Claude — not the operator, not the analyst, not any future agent — ever
produces, estimates, reasons toward, or transcribes from memory a comp number.
A number exists ONLY as the stdout of `run_comp.py` having actually executed in
this turn, written a RUN TOKEN, and passed the independent verifier. If the
script did not run this turn, **there is no number, and the correct output is
`NOT RUN`.**

The analyst is the **operator of a calculator**. It is not a valuer. The instant
it eyeballs comps and reasons to an ARV, it becomes the fabricating agent again.
This system removes the model from the number-producing path entirely.

## Files

| File | Role |
|------|------|
| `comp_engine.py` | The ONLY thing that computes a number. Deterministic, stdlib only. |
| `verify_answer.py` | Independent re-check (a separate implementation; does not import the engine). Returns PASS/FAIL. |
| `run_comp.py` | Operator entrypoint: load pool → engine → verifier → log → print verified block. |
| `comp_run_log.csv` | Append-only audit log, one row per run. |
| `analyst_notes.md` | Human-maintained facts the analyst reads at session start. |
| `docs/comp-export-sample.csv` | Example comp pool (CSV schema reference). |
| `tests/test_comp_system.py` | Trust tests incl. tamper detection (18 checks). |

No third-party packages — Python 3 standard library only.

## How to run a property (the ONLY sanctioned path)

```bash
python3 run_comp.py \
  --address "200 Subject St" --zip 77089 \
  --beds 3 --baths 2 --sqft 1850 --repair moderate
# default pool = every *.csv in the working folder and ./docs (minus the log).
# explicit pool: add  --pool docs/comp-export-sample.csv other.csv
```

`--repair` is one of `light | moderate | heavy` (repair $/sqft = 20 / 35 / 55).

Output is a token block, e.g.:

```
RUN TOKEN: 6f8a4e1b9c2d7a3e5f0b8c1d4e6a9b2c
TIMESTAMP: 2026-05-29T03:21:14+00:00
COMP SET STATUS: VALID
COMPS FOUND: 9
COMPS USED: 8
ARV: $277,500
MAX OFFER: $114,400
OPENING OFFER RANGE: $89,400 - $99,400
WALK AWAY ABOVE: $114,400
COMPS INCLUDED:
  - 106 Tight St, Houston, TX 77089  ($147.00/sqft)
  ...
SPREAD: 4.0% -> 4.0%
```

If the verifier fails, `run_comp.py` prints **`VERIFY FAILED, do not use.`** and
**no number**. If no script ran this turn, the answer is **`NOT RUN`**.

## CSV schema

Columns are read from their dedicated headers (case-insensitive; common aliases
accepted). The canonical set:

```
Address, City, State, ZIP, Beds, Baths, SqFt, Price, MLS Status, Date Sold, Property Type
```

ZIP, City, State, and MLS Status are ALWAYS read from their own columns — never
regex'd off the street cell (house numbers like `10430` previously matched as
ZIPs). See `docs/comp-export-sample.csv`.

## What the engine does (deterministic pipeline)

1. **Load & normalize** every comp CSV. Dedupe on
   `address_key + price + date + sqft`. Rows with no ZIP are dropped and counted.
2. **Filter to valid closed sales**: MLS Status is a closed sale (exclude Active
   / Pending / Canceled / Off Market / Failed); positive sale price; **same ZIP**;
   beds ±1; baths ±1; sqft ±20%. Comps older than 12 months are kept but flagged.
3. **Validation gates (these return NO NUMBER):**
   - `< 5` surviving comps → **THIN**
   - IQR-trim ppsf outliers; if spread still `> 30%` after trim → **UNRELIABLE**
   - `0` matches → **DATA NOT FOUND**
4. **Calculation (only if gates pass):**
   - `median_ppsf` = MEDIAN price/sqft of trimmed survivors (median, never mean)
   - `ARV = median_ppsf × subject_sqft`
   - `repairs = repair_ppsf × subject_sqft`
   - `Max Offer = ARV × 0.70 − repairs − $15,000 fee`
   - `Opening Range = (Max Offer − 25,000) … (Max Offer − 15,000)`
   - `Walk Away Above = Max Offer`; all dollars rounded to nearest 100.
5. **Emit with a RUN TOKEN** = `sha256(subject + sorted candidate comp rows +
   timestamp)`. The token is the proof the number came from this execution
   against this data.

## What the verifier independently confirms

`verify_answer.py` is a **separate implementation** (it does not import the
engine). Against the same pool it: re-derives the candidate comp set; recomputes
the RUN TOKEN and confirms it matches; independently re-derives the status path;
recomputes median/ARV/Max Offer/range/walk-away and confirms each matches;
confirms the math is self-consistent (`Max Offer == ARV×0.70 − repairs − fee`,
etc.); and confirms every comp named in the block exists in the pool with the
stated $/sqft. Any mismatch → **FAIL → no number shown**. This catches the exact
prior failure: numbers that "look computed" but fail their own math, and numbers
claimed to "come from a query" that no execution produced.

## RULES FOR THE HUMAN-FACING CLAUDE (operator, not analyst)

- You may ONLY state a comp number that appears in `run_comp.py` stdout from
  **this turn**, pasted **verbatim**, with its run token.
- Asked "what's X worth?" with no run this turn: say **`NOT RUN — running it
  now`** and run it. Never answer from memory, prior turns, or estimation.
- **Never** say a number "came from a query" unless the token block is in front
  of you this turn. (That exact lie is what this system exists to prevent.)
- Verifier returns FAIL → report the failure, show no number.
- You may NOT adjust, round, smooth, average, or "sanity check" the engine's
  number with your own judgment. The engine is the authority; you are the
  messenger. Copy the block or say `NOT RUN`.
- "Confident-sounding" is not "verified." Only token + verifier PASS is verified.
- At session start, read `analyst_notes.md` and apply confirmed facts.

## The learning layer (the safe version of "self-improving")

The **math never self-modifies** — that is what makes it trustworthy. What
improves over time is human-driven and visible: `comp_run_log.csv` reveals
patterns (which ZIPs chronically come back THIN/UNRELIABLE) so a human can
deliberately tune parameters; `analyst_notes.md` holds human-confirmed facts.
Constants live in `comp_engine.py` AND `verify_answer.py` and must be changed
together. Nothing edits its own calculation.

## Tests

```bash
python3 tests/test_comp_system.py    # 18 checks incl. tamper detection
```

## Note on the comp data pool / Google Drive

There is no live Google Drive access in this environment. To include Drive files
named comp/comparable, sync them into the working folder (or pass them via
`--pool`); `run_comp.py` picks up every `*.csv` in the folder and `./docs`
automatically.
