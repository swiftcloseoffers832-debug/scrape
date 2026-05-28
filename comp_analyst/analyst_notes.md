# Analyst Notes — read this at the start of every session

These are **human-confirmed facts** and operating reminders. The engine does NOT
read this file; YOU (the operator) read it and apply it by choosing the right
inputs or by deliberately editing `comp_params.json`. Nothing here changes the
math automatically.

## Session-start checklist

1. Read this file top to bottom.
2. Confirm the comp data folder (`comp_analyst/data/`) holds the CSVs you intend
   to use. If you need Drive `comp`/`comparable` files, pull them in first (see
   README "Pulling comp data from Google Drive").
3. For any subject, the ONLY way to a number is:
   `python3 comp_analyst/run_comp.py ...` → verifier PASS → paste the block.
4. Never state a number that is not in this turn's `run_comp.py` stdout.

## Confirmed facts (append as the human confirms them)

- `77096`: valid comps generally require `sqft > 2000`; smaller homes pull from a
  different sub-market and come back THIN/UNRELIABLE. When working 77096, expect
  to use larger subjects or widen tolerances **deliberately** in
  `comp_params.json` (and note why here).
- (add new confirmed facts here, dated, with the reason)

## How to tune parameters (the safe "learning layer")

When the log (`comp_run_log.csv`) shows a zip chronically returning THIN or
UNRELIABLE, that is a signal to **deliberately** adjust `comp_params.json` — for
example loosen `sqft_pct_tolerance`, raise `recency_months`, or adjust
`repair_ppsf`. Do this as a visible, human-made edit. Record what you changed and
why under "Confirmed facts" above. The engine's arithmetic never edits itself.

## Markets

Houston, San Antonio, Fort Worth, Dallas, Corpus Christi (contract assignment /
wholesaling). Comps are matched within the **same zip** as the subject only.
