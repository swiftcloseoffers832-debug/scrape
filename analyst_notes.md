# Analyst Notes — SwiftClose Comp Engine

These are human-confirmed facts the analyst loads at session start.
This file is the *only* memory layer outside the audit log. The comp
engine itself does not read this file; it is read by the analyst
(LLM) so it can interpret engine output sensibly and decide when to
stop trying.

**Rule for adding entries:** only add a note here once *you* have
seen the pattern at least twice in `comp_run_log.csv`. Do not let the
analyst add notes on its own. If a note ever feels like it is doing
math, delete it — math belongs in `comp_engine.py`.

---

## Markets / ZIPs

<!--
Add a note here only after YOU have seen the pattern at least twice in
comp_run_log.csv. Format: ZIP/market -> the confirmed fact.
-->

- **Corpus Christi (78404, 78405, 78410, 78411, 78412, 78414, 78415,
  78418): expect UNRELIABLE, no number.** Verified against
  `comparables_data_final.csv` (28 May 2026): for 3/2 homes across the
  full ±20% sqft band, the price/sqft spread stays above the 30% gate
  even after IQR trim (e.g. 78414 @ 1450 sqft = 73% spread on 23
  comps). There are plenty of comps — the pool is *noisy*, not thin.
  By zip+bed+bath+sqft alone the engine cannot comp Corpus to a
  reliable number; that is correct behavior, not a bug. If Corpus must
  be comped, it needs tighter (e.g. subdivision-level) matching — a
  deliberate rule change, decided by a human, not an engine guess.

---

## Subdivisions

_(no confirmed notes yet)_

---

## Known data quirks

- The pre-engine bug where one sale showed as ~9 rows (e.g.
  6916 Berger appearing 9 times for ~6 real sales) is handled
  inside the engine via `(address_key + date_sold)` dedupe. Do
  not work around it manually.
- Rows flagged as refi / loan / "Last Sale Price refi" are
  excluded by the engine. If a comp you trust is being dropped
  for this reason, check the source row, do not bypass the
  engine.

---

## When to return DATA NOT FOUND

The analyst returns DATA NOT FOUND verbatim if the engine returns
any of:

- `COMP SET STATUS: THIN`
- `COMP SET STATUS: UNRELIABLE`
- `COMP SET STATUS: DATA NOT FOUND`

It does *not* try to estimate, average, or "use judgment." The
guarantee is: every number that ever leaves this system came out
of the engine.
