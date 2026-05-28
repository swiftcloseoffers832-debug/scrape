# SwiftClose Offers — Comp Analyst System

A deterministic calculator for turning a subject property into trustworthy offer
numbers (ARV, Max Offer, Opening Range, Walk-Away) for SwiftClose Offers, a
Houston-area wholesaling operation (contract assignment).

## The one rule everything serves

> A comp number exists ONLY as the stdout of an executed script that wrote a run
> token and passed the verifier. If the script did not run this turn, there is no
> number — the correct output is **NOT RUN**.

The analyst has fabricated comp numbers before, including fabricating the
reassurance that it had not fabricated. A language model cannot be instructed out
of that; it can only be removed from the calculation path. This system removes it.
**You are an operator of a calculator, not a valuer.**

## Rules for the human-facing Claude (operator)

- You may ONLY state a comp number that appears in **this turn's**
  `run_comp.py` stdout, pasted **verbatim**, with its run token.
- If asked "what's X worth?" and you have not run the script this turn: say
  **"NOT RUN — running it now"** and run it. Never answer from memory, a prior
  turn, or estimation.
- You may NEVER say a number "came from a query" / "from the data" unless the
  token block is in front of you in this turn. (That exact lie has happened.)
- If the verifier returns **FAIL** (`VERIFY FAILED, do not use`): report the
  failure, show **no number**.
- You may not adjust, round, smooth, average, or "sanity-check" the engine's
  number with your own judgment. The engine is the authority; you are the
  messenger. Copy the block, or say NOT RUN.
- "Confident-sounding" is not "verified." Only the token + verifier PASS is
  verified.
- At session start, read `analyst_notes.md` and apply confirmed facts.

## How to run (one command per property)

```bash
python3 comp_analyst/run_comp.py \
  --address "101 Main St" --zip 77002 \
  --beds 3 --baths 2 --sqft 1800 --repair moderate
```

`--repair` is one of `light | moderate | heavy`. Optional: `--data <folder>`
(defaults to `comp_analyst/data/`), `--params <file>`, `--timestamp <iso>`.

`run_comp.py` loads the pool → runs `comp_engine.py` → runs `verify_answer.py` →
appends one row to `comp_run_log.csv` → prints **only** the verified block (or a
failure / no-number status). Example PASS output:

```
RUN TOKEN: ec5cb591c9413161c2a930dbb08320af
COMP SET STATUS: VALID
COMPS FOUND: 9
COMPS USED: 8
ARV: $288,000
MAX OFFER: $123,600
OPENING OFFER RANGE: $98,600 - $108,600
WALK AWAY ABOVE: $123,600
COMPS INCLUDED:
  - 100 Main St, Houston TX 77002 | $160.00/sqft
  ...
SPREAD: 41.85% -> 5.46%
```

## Statuses (only VALID produces a number)

- **VALID** — gates passed; ARV and offer numbers are emitted.
- **THIN** — fewer than `thin_minimum` (5) valid comps. No number.
- **UNRELIABLE** — price/sqft spread still exceeds `spread_threshold_pct` (30%)
  after IQR trimming. No number.
- **DATA NOT FOUND** — 0 comps matched. No number.
- **DATA ERROR, no number produced** — a required column could not be mapped (the
  engine refuses to guess) or the data could not be read. No number.

## The engine pipeline (what `comp_engine.py` does)

1. **Load + normalize** every `*.csv` in the data folder into one table. Read
   `zip, city, state, status` from their **dedicated columns by header name** —
   never regex a ZIP out of the street cell. Dedupe on
   `(address_key, price, date_sold, sqft)`. Drop rows with no zip.
2. **Filter to valid closed sales**: status is a closed sale; price within sane
   bounds (rejects refi/loan-shaped values); **same zip**; beds ±1; baths ±1;
   sqft ±20%. Comps older than 12 months are **kept but flagged `[OLD]`**.
3. **Gates** (return NO NUMBER): 0 matches → DATA NOT FOUND; `<5` → THIN; IQR-trim
   outliers; post-trim spread `>30%` → UNRELIABLE.
4. **Calculate** (only if gates pass): `median_ppsf` (median, never mean) ×
   subject sqft = ARV; repairs = repair_ppsf × sqft (20/35/55 light/moderate/
   heavy); `Max Offer = ARV×0.70 − repairs − $15,000`; Opening Range =
   `Max−$25,000 .. Max−$15,000`; Walk-Away Above = Max Offer. All dollars rounded
   to the nearest $100.

All tunables live in `comp_params.json` and are changed by a human, deliberately.
The math never self-modifies.

## The verifier (`verify_answer.py`) — independent by design

`verify_answer.py` **does not import `comp_engine`.** It re-implements the loader,
parsing, and arithmetic in its own code path, then:

- recomputes the **run token** from `(subject + sorted rows used + timestamp)` and
  confirms it matches the printed token;
- confirms every comp named in the block exists in the reloaded data;
- for VALID, recomputes median/ARV/repairs/Max Offer/range/walk-away from the
  reloaded data and confirms every printed dollar figure matches exactly, and
  that the math is internally consistent;
- for THIN/UNRELIABLE/DATA NOT FOUND, confirms the status is justified and that
  **no dollar figure** was emitted.

A FAIL means the block must not be shown as a number.

### Canonical token spec (so both implementations agree)

```
payload = "SWIFTCLOSE-COMP-V1\n"
        + "<address_key>|<zip>|<beds:g>|<baths:g>|<sqft:int>|<repair_level>\n"
        + "||".join(sorted("<address_key>|<price:int>|<date_sold>|<sqft:int>"
                           for each comp used))
        + "\n<timestamp>"
run_token = sha256(payload).hexdigest()[:32]
```

Parsing spec both files follow: `address_key` = lowercased street with
punctuation→space, whitespace collapsed; `zip` = first 5 digits of the dedicated
zip column; `price`/`sqft` parsed by stripping non-numeric characters; dates
normalized to `YYYY-MM-DD` when parseable.

## Pulling comp data from Google Drive

The engine is offline and reads only local CSVs. To use Drive `comp`/`comparable`
files, the operator pulls them into the data folder first, then runs the engine:

1. Use the Google Drive MCP `search_files` for files named `comp`/`comparable`.
2. `download_file_content` (or `read_file_content`) and save each into
   `comp_analyst/data/` as a `.csv`.
3. Run `run_comp.py` as usual. The run is now fully reproducible from local data.

## Files

| File | Role |
| --- | --- |
| `comp_engine.py` | The only component that computes a number. Deterministic, stdlib-only. |
| `verify_answer.py` | Independent re-check (does not import the engine). |
| `run_comp.py` | Operator entrypoint: load → engine → verify → log → print. |
| `comp_params.json` | Human-tunable parameters (deliberate, visible). |
| `comp_run_log.csv` | Append-only audit log, one row per run. |
| `analyst_notes.md` | Human-confirmed facts, read at session start. |
| `data/` | Comp CSVs (includes `sample_comps.csv`, a synthetic fixture — NOT real comps). |

## The learning layer (safe self-improvement)

The math never self-modifies — that is what makes it trustworthy. What improves
over time, **through the human, deliberately and visibly**:

- `comp_run_log.csv` reveals patterns (which zips chronically return
  THIN/UNRELIABLE) so the human can tune `comp_params.json`.
- `analyst_notes.md` holds human-confirmed facts the operator applies each
  session.

Nothing edits its own calculation.
