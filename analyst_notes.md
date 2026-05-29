# Comp Analyst Notes — human-maintained facts

The analyst reads this file at session start and applies CONFIRMED facts. Only a
human edits this file. The deterministic engine NEVER reads or writes it and
NEVER self-tunes. This is the deliberate, visible learning layer.

How to use this file:
- Add a fact only after you (a human) have confirmed it from `comp_run_log.csv`
  or from a real deal outcome.
- If a fact implies a parameter change (match tolerance, repair $/sqft, thin
  minimum, spread limit), change the constant in `comp_engine.py` AND
  `verify_answer.py` together (they must agree), then note it here with a date.
- Notes are guidance for picking subject inputs and reading results. They do NOT
  let the analyst override an engine number.

---

## Confirmed facts (apply these)

- _(none yet — seed entries below are templates; confirm before relying on them)_

## Market scope
- Target markets: Houston, San Antonio, Fort Worth, Dallas, Corpus Christi.
- Engine matches comps by exact ZIP, so the subject ZIP must be correct.

## ZIP-specific observations (templates — confirm before trusting)
- `77096`: candidate pattern suggests valid comps need `sqft > 2000`; runs below
  that tend to come back THIN. CONFIRM against the log before treating as a rule.
- (add more as the log reveals patterns: which ZIPs chronically return
  THIN/UNRELIABLE, and why)

## Parameter change log
- (date) — (what changed in comp_engine.py + verify_answer.py) — (why)
- Initial seed: FEE=$15,000, 70% rule, THIN<5 comps, sqft +/-20%, beds/baths
  +/-1, spread limit 30% post-trim, repairs 20/35/55 $/sqft light/moderate/heavy.

## Data hygiene reminders (do not regress)
- Read ZIP / MLS Status from dedicated columns, never regex off the street cell
  (house numbers like "10430" falsely matched as ZIPs).
- Dedupe comps; the same sale recurs across nearby subjects (raw 4,300 -> 3,377
  unique in one historical pull).
- Closed sales only; exclude Active / Pending / Canceled / Off Market / Failed.
