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
Examples to write yourself, replace these with confirmed facts:

- 77096: sqft over 2000 is required for a valid comp set; smaller
  homes return THIN.
- 77018: pool is fine, 12 months of data routinely passes the
  spread gate.
- Corpus Christi pool too thin overall, default to skip.
-->

_(no confirmed notes yet)_

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
