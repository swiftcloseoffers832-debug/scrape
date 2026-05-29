#!/usr/bin/env python3
"""
comp_engine.py — the ONLY thing in SwiftClose that computes a comp number.

THE ONE RULE: a number exists ONLY as the output of this script having actually
run against real comp data in this turn, stamped with a RUN TOKEN. No Claude may
estimate, smooth, average, or "sanity check" a number. This engine is a
deterministic calculator. It is not a valuer.

Pipeline (see README / build doc):
  STEP 1  load + normalize the comp pool (dedicated columns, no ZIP regex)
  STEP 2  filter to valid CLOSED sales matching the subject
  STEP 3  validation gates that return NO NUMBER (THIN / UNRELIABLE / NOT FOUND)
  STEP 4  deterministic calculation (median ppsf -> ARV -> Max Offer)
  STEP 5  emit a token block; the RUN TOKEN is the proof of provenance

Stdlib only (no pandas/numpy) so the trust path has no hidden dependencies.

Usage as a library:
    from comp_engine import run_engine, format_block
    result = run_engine(subject, pool_paths)
    print(format_block(result))

Usage as a CLI:
    python3 comp_engine.py --address "123 Main St" --zip 77089 \
        --beds 3 --baths 2 --sqft 1850 --repair moderate \
        --pool docs/comp-export-sample.csv
"""

import argparse
import csv
import glob
import hashlib
import json
import os
import re
import statistics
import sys
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Constants (tunable ONLY by a human editing this file, never self-modifying)
# ---------------------------------------------------------------------------
FEE = 15000               # SwiftClose assignment fee
ARV_MULTIPLIER = 0.70     # 70% rule
THIN_MINIMUM = 5          # < this many surviving comps -> THIN, no number
SQFT_TOLERANCE = 0.20     # +/- 20%
SPREAD_LIMIT_PCT = 30.0   # post-trim ppsf spread above this -> UNRELIABLE
MONTHS_FRESH = 12         # comps older than this are kept but flagged

REPAIR_PPSF = {           # repair $/sqft by level
    "light": 20,
    "moderate": 35,
    "heavy": 55,
}
# accepted aliases for repair level input
REPAIR_ALIASES = {
    "light": "light", "low": "light", "cosmetic": "light", "minor": "light",
    "moderate": "moderate", "med": "moderate", "medium": "moderate", "mod": "moderate",
    "heavy": "heavy", "high": "heavy", "major": "heavy", "gut": "heavy",
}

# MLS statuses that count as a real closed sale
CLOSED_STATUSES = {"sold", "closed", "closed sale", "sld"}
# explicitly NOT a sale (defensive; anything not recognized as closed is excluded)
NON_SALE_STATUSES = {
    "active", "pending", "canceled", "cancelled", "off market", "off-market",
    "failed", "withdrawn", "expired", "coming soon", "temp off market",
}

# header aliases -> canonical field. matched case-insensitively after strip.
HEADER_MAP = {
    "address": "address", "street": "address", "street address": "address",
    "city": "city",
    "state": "state", "st": "state",
    "zip": "zip", "zipcode": "zip", "zip code": "zip", "postal code": "zip", "postal": "zip",
    "beds": "beds", "bed": "beds", "bedrooms": "beds", "br": "beds",
    "baths": "baths", "bath": "baths", "bathrooms": "baths", "ba": "baths",
    "sqft": "sqft", "sq ft": "sqft", "square feet": "sqft", "living area": "sqft", "sqft_living": "sqft",
    "price": "price", "sale price": "price", "close price": "price", "sold price": "price",
    "mls status": "mls_status", "status": "mls_status",
    "date sold": "date_sold", "sold date": "date_sold", "close date": "date_sold", "closing date": "date_sold",
    "property type": "property_type", "type": "property_type",
}


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------
def _norm_header(h):
    return re.sub(r"\s+", " ", (h or "").strip().lower())


def address_key(street, city="", state="", zipc=""):
    """Lowercase, strip city/state/zip, strip punctuation, collapse whitespace.

    Used for dedup and for matching comps named in a block back to the pool.
    """
    s = (street or "").lower()
    # remove trailing city/state/zip fragments if they leaked into the street cell
    for token in (str(city or "").lower(), str(state or "").lower(), str(zipc or "").lower()):
        if token:
            s = s.replace(token, " ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def to_float(v):
    if v is None:
        return None
    s = str(v).strip().replace(",", "").replace("$", "")
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_zip(v):
    """Read ZIP from its dedicated column value ONLY. Never regex off a street."""
    if v is None:
        return None
    s = str(v).strip()
    m = re.match(r"^(\d{5})", s)
    return m.group(1) if m else None


def parse_date(v):
    if not v:
        return None
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def norm_repair(level):
    key = str(level or "").strip().lower()
    if key not in REPAIR_ALIASES:
        raise ValueError(
            f"unknown repair_level {level!r}; use one of light/moderate/heavy"
        )
    return REPAIR_ALIASES[key]


def round100(x):
    """Round to nearest 100 dollars."""
    return int(round(x / 100.0)) * 100


def _months_between(d_old, d_new):
    return (d_new.year - d_old.year) * 12 + (d_new.month - d_old.month)


def _full_address(street, city, state, zipc):
    return f"{street}, {city}, {state} {zipc}".strip()


# ---------------------------------------------------------------------------
# STEP 1 — LOAD & NORMALIZE
# ---------------------------------------------------------------------------
def load_pool(paths):
    """Read all comp CSVs into one normalized, deduped table.

    Returns (rows, stats). Each row is a dict with canonical fields plus
    address_key and a numeric ppsf where computable.
    """
    raw = []
    files_read = []
    for path in paths:
        if not os.path.isfile(path):
            continue
        files_read.append(path)
        with open(path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.reader(fh)
            try:
                header = next(reader)
            except StopIteration:
                continue
            colmap = {}  # column index -> canonical field
            for i, h in enumerate(header):
                canon = HEADER_MAP.get(_norm_header(h))
                if canon:
                    colmap[i] = canon
            for cells in reader:
                if not any(c.strip() for c in cells):
                    continue
                rec = {}
                for i, val in enumerate(cells):
                    field = colmap.get(i)
                    if field:
                        rec[field] = val
                raw.append(rec)

    total_raw = len(raw)
    dropped_no_zip = 0
    normalized = []
    for rec in raw:
        zipc = parse_zip(rec.get("zip"))  # dedicated column only
        if not zipc:
            dropped_no_zip += 1
            continue
        street = (rec.get("address") or "").strip()
        city = (rec.get("city") or "").strip()
        state = (rec.get("state") or "").strip().upper()
        sqft = to_float(rec.get("sqft"))
        price = to_float(rec.get("price"))
        beds = to_float(rec.get("beds"))
        baths = to_float(rec.get("baths"))
        date_sold = parse_date(rec.get("date_sold"))
        status = _norm_header(rec.get("mls_status"))
        ppsf = (price / sqft) if (price and sqft and sqft > 0) else None
        normalized.append({
            "address": street,
            "city": city,
            "state": state,
            "zip": zipc,
            "beds": beds,
            "baths": baths,
            "sqft": sqft,
            "price": price,
            "mls_status": status,
            "date_sold": date_sold,
            "date_sold_str": (date_sold.isoformat() if date_sold else ""),
            "property_type": (rec.get("property_type") or "").strip(),
            "address_key": address_key(street, city, state, zipc),
            "full_address": _full_address(street, city, state, zipc),
            "ppsf": ppsf,
        })

    # Dedupe on key = address_key + price + date + sqft
    seen = set()
    deduped = []
    for r in normalized:
        k = (r["address_key"], r["price"], r["date_sold_str"], r["sqft"])
        if k in seen:
            continue
        seen.add(k)
        deduped.append(r)

    stats = {
        "files_read": files_read,
        "rows_raw": total_raw,
        "rows_dropped_no_zip": dropped_no_zip,
        "rows_after_zip": len(normalized),
        "rows_after_dedup": len(deduped),
    }
    return deduped, stats


# ---------------------------------------------------------------------------
# STEP 2 — FILTER TO VALID CLOSED SALES
# ---------------------------------------------------------------------------
def is_closed_sale(status):
    s = (status or "").strip().lower()
    if s in CLOSED_STATUSES:
        return True
    if s in NON_SALE_STATUSES:
        return False
    # tolerate export variants like "closed comp-export", "sold (mls)"
    return s.startswith("sold") or s.startswith("closed") or "sold" in s


def filter_comps(rows, subject, today):
    survivors = []
    flags = {"stale_kept": 0, "undated_kept": 0}
    s_zip = parse_zip(subject["zip"])
    s_beds = subject["beds"]
    s_baths = subject["baths"]
    s_sqft = subject["sqft"]
    sqft_lo = s_sqft * (1 - SQFT_TOLERANCE)
    sqft_hi = s_sqft * (1 + SQFT_TOLERANCE)

    for r in rows:
        if not is_closed_sale(r["mls_status"]):
            continue
        if not (r["price"] and r["price"] > 0):  # real sale, positive price
            continue
        if r["zip"] != s_zip:
            continue
        if r["beds"] is None or abs(r["beds"] - s_beds) > 1:
            continue
        if r["baths"] is None or abs(r["baths"] - s_baths) > 1:
            continue
        if r["sqft"] is None or not (sqft_lo <= r["sqft"] <= sqft_hi):
            continue
        if r["ppsf"] is None:
            continue
        # date: within 12 months counts; older kept but flagged; undated kept+flagged
        if r["date_sold"] is None:
            r = dict(r, _stale=True)
            flags["undated_kept"] += 1
        elif _months_between(r["date_sold"], today) > MONTHS_FRESH:
            r = dict(r, _stale=True)
            flags["stale_kept"] += 1
        survivors.append(r)

    return survivors, flags


# ---------------------------------------------------------------------------
# STEP 3 — VALIDATION GATES + IQR TRIM
# ---------------------------------------------------------------------------
def spread_pct(values):
    """Relative ppsf spread = (max - min) / median * 100."""
    if not values:
        return 0.0
    med = statistics.median(values)
    if med == 0:
        return 0.0
    return (max(values) - min(values)) / med * 100.0


def iqr_trim(survivors):
    """Drop ppsf outliers below Q1-1.5*IQR or above Q3+1.5*IQR.

    Returns (trimmed_rows, spread_before, spread_after).
    """
    ppsfs = [r["ppsf"] for r in survivors]
    spread_before = spread_pct(ppsfs)
    if len(ppsfs) < 4:
        # too few for a meaningful quartile fence; keep all
        return list(survivors), spread_before, spread_pct(ppsfs)
    qs = statistics.quantiles(ppsfs, n=4, method="inclusive")
    q1, q3 = qs[0], qs[2]
    iqr = q3 - q1
    lo = q1 - 1.5 * iqr
    hi = q3 + 1.5 * iqr
    trimmed = [r for r in survivors if lo <= r["ppsf"] <= hi]
    spread_after = spread_pct([r["ppsf"] for r in trimmed])
    return trimmed, spread_before, spread_after


# ---------------------------------------------------------------------------
# STEP 4 — CALCULATION
# ---------------------------------------------------------------------------
def compute_numbers(subject, trimmed):
    median_ppsf = statistics.median([r["ppsf"] for r in trimmed])
    sqft = subject["sqft"]
    arv = round100(median_ppsf * sqft)
    repair_ppsf = REPAIR_PPSF[subject["repair_level"]]
    repairs = round100(repair_ppsf * sqft)
    max_offer = round100(arv * ARV_MULTIPLIER - repairs - FEE)
    opening_low = round100(max_offer - 25000)
    opening_high = round100(max_offer - 15000)
    walk_away = max_offer
    return {
        "median_ppsf": median_ppsf,
        "repair_ppsf": repair_ppsf,
        "arv": arv,
        "repairs": repairs,
        "max_offer": max_offer,
        "opening_low": opening_low,
        "opening_high": opening_high,
        "walk_away": walk_away,
    }


# ---------------------------------------------------------------------------
# STEP 5 — RUN TOKEN
# ---------------------------------------------------------------------------
def canonical_subject(subject):
    """Stable serialization of the subject for hashing."""
    return json.dumps({
        "address_key": address_key(subject["address"], zipc=subject["zip"]),
        "zip": parse_zip(subject["zip"]),
        "beds": float(subject["beds"]),
        "baths": float(subject["baths"]),
        "sqft": float(subject["sqft"]),
        "repair_level": subject["repair_level"],
    }, sort_keys=True, separators=(",", ":"))


def canonical_comp(r):
    """Stable serialization of one comp row for hashing/identity."""
    return {
        "address_key": r["address_key"],
        "zip": r["zip"],
        "beds": r["beds"],
        "baths": r["baths"],
        "sqft": r["sqft"],
        "price": r["price"],
        "date": r["date_sold_str"],
    }


def canonical_comp_list(rows):
    items = [canonical_comp(r) for r in rows]
    items.sort(key=lambda d: json.dumps(d, sort_keys=True, separators=(",", ":")))
    return json.dumps(items, sort_keys=True, separators=(",", ":"))


def make_token(subject, comp_rows, timestamp):
    """RUN TOKEN = sha256(subject + sorted comp rows used + timestamp).

    NOTE: this function (and its helpers) is duplicated verbatim in
    verify_answer.py so the verifier can independently recompute the token
    without importing the engine. The two copies MUST stay byte-identical.
    """
    payload = (
        canonical_subject(subject)
        + "|" + canonical_comp_list(comp_rows)
        + "|" + timestamp
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------------------
# ORCHESTRATION
# ---------------------------------------------------------------------------
def run_engine(subject_in, pool_paths, timestamp=None):
    """Run the full pipeline. Returns a result dict (the run artifact).

    `subject_in` keys: address, zip, beds, baths, sqft, repair_level.
    """
    subject = {
        "address": str(subject_in["address"]).strip(),
        "zip": str(subject_in["zip"]).strip(),
        "beds": float(subject_in["beds"]),
        "baths": float(subject_in["baths"]),
        "sqft": float(subject_in["sqft"]),
        "repair_level": norm_repair(subject_in["repair_level"]),
    }
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    today = datetime.now(timezone.utc).date()

    rows, load_stats = load_pool(pool_paths)
    survivors, flags = filter_comps(rows, subject, today)

    result = {
        "schema": "swiftclose-comp-run/1",
        "timestamp": timestamp,
        "subject": subject,
        "load_stats": load_stats,
        "filter_flags": flags,
        "comps_found": len(survivors),
        "status": None,
        "numbers": None,
        "candidate_comps": [canonical_comp(r) for r in survivors],
        "comps_used": [],
        "comps_included": [],
        "spread_before": None,
        "spread_after": None,
        "token": None,
    }

    # The token always covers the post-filter candidate set + subject + time,
    # so it is provenance for the inputs to every downstream number.
    token = make_token(subject, survivors, timestamp)
    result["token"] = token

    # GATE: 0 matches
    if len(survivors) == 0:
        result["status"] = "DATA NOT FOUND"
        return result

    # GATE: thin
    if len(survivors) < THIN_MINIMUM:
        result["status"] = "THIN"
        result["spread_before"] = round(spread_pct([r["ppsf"] for r in survivors]), 1)
        result["spread_after"] = result["spread_before"]
        return result

    trimmed, spread_before, spread_after = iqr_trim(survivors)
    result["spread_before"] = round(spread_before, 1)
    result["spread_after"] = round(spread_after, 1)

    # A trim can theoretically remove too many; guard it.
    if len(trimmed) < THIN_MINIMUM:
        result["status"] = "THIN"
        return result

    # GATE: unreliable spread
    if spread_after > SPREAD_LIMIT_PCT:
        result["status"] = "UNRELIABLE"
        return result

    # VALID -> compute
    numbers = compute_numbers(subject, trimmed)
    result["status"] = "VALID"
    result["numbers"] = numbers
    result["comps_used"] = [canonical_comp(r) for r in trimmed]
    result["comps_included"] = [
        {"full_address": r["full_address"], "ppsf": round(r["ppsf"], 2)}
        for r in sorted(trimmed, key=lambda x: x["ppsf"])
    ]
    return result


# ---------------------------------------------------------------------------
# OUTPUT BLOCK
# ---------------------------------------------------------------------------
def _money(n):
    return f"${n:,.0f}"


def format_block(result):
    """Render the human-facing token block. Numbers ONLY appear when VALID."""
    lines = []
    lines.append(f"RUN TOKEN: {result['token']}")
    lines.append(f"TIMESTAMP: {result['timestamp']}")
    lines.append(f"COMP SET STATUS: {result['status']}")
    lines.append(f"COMPS FOUND: {result['comps_found']}")

    status = result["status"]
    if status == "VALID":
        n = result["numbers"]
        lines.append(f"COMPS USED: {len(result['comps_used'])}")
        lines.append(f"ARV: {_money(n['arv'])}")
        lines.append(f"MAX OFFER: {_money(n['max_offer'])}")
        lines.append(
            f"OPENING OFFER RANGE: {_money(n['opening_low'])} - {_money(n['opening_high'])}"
        )
        lines.append(f"WALK AWAY ABOVE: {_money(n['walk_away'])}")
        lines.append("COMPS INCLUDED:")
        for c in result["comps_included"]:
            lines.append(f"  - {c['full_address']}  (${c['ppsf']:,.2f}/sqft)")
        lines.append(
            f"SPREAD: {result['spread_before']}% -> {result['spread_after']}%"
        )
    else:
        # NO NUMBER. State why, plainly.
        reason = {
            "THIN": f"fewer than {THIN_MINIMUM} valid comps survived filtering",
            "UNRELIABLE": (
                f"ppsf spread {result.get('spread_after')}% exceeds "
                f"{SPREAD_LIMIT_PCT}% after outlier trim"
            ),
            "DATA NOT FOUND": "no closed-sale comps matched the subject",
        }.get(status, "no number produced")
        lines.append("ARV: NO NUMBER")
        lines.append("MAX OFFER: NO NUMBER")
        lines.append(f"REASON: {reason}")
        if result.get("spread_before") is not None:
            lines.append(
                f"SPREAD: {result['spread_before']}% -> {result['spread_after']}%"
            )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pool discovery (working folder; Google Drive sync folder if mounted locally)
# ---------------------------------------------------------------------------
def discover_pool(extra_dirs=None, log_name="comp_run_log.csv"):
    """Find comp CSVs: every *.csv in the working folder (and any extra dirs),
    excluding the audit log.

    NOTE: there is no live Google Drive access in this environment. To include
    Drive files named comp/comparable, sync them into the working folder (or
    pass --pool explicitly).
    """
    dirs = [".", "docs"]
    if extra_dirs:
        dirs.extend(extra_dirs)
    found = []
    for d in dirs:
        for path in glob.glob(os.path.join(d, "*.csv")):
            base = os.path.basename(path)
            if base == log_name:
                continue
            found.append(path)
    # de-dup while preserving order
    seen, out = set(), []
    for p in found:
        rp = os.path.normpath(p)
        if rp not in seen:
            seen.add(rp)
            out.append(rp)
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_arg_parser():
    p = argparse.ArgumentParser(description="SwiftClose deterministic comp engine")
    p.add_argument("--address", required=True)
    p.add_argument("--zip", required=True)
    p.add_argument("--beds", required=True, type=float)
    p.add_argument("--baths", required=True, type=float)
    p.add_argument("--sqft", required=True, type=float)
    p.add_argument("--repair", required=True, help="light | moderate | heavy")
    p.add_argument("--pool", nargs="*", default=None,
                   help="explicit comp CSV path(s); default = discover *.csv")
    p.add_argument("--artifact", default=None,
                   help="write the JSON run artifact to this path")
    return p


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    subject = {
        "address": args.address,
        "zip": args.zip,
        "beds": args.beds,
        "baths": args.baths,
        "sqft": args.sqft,
        "repair_level": args.repair,
    }
    pool = args.pool if args.pool else discover_pool()
    if not pool:
        print("RUN TOKEN: (none)")
        print("COMP SET STATUS: DATA NOT FOUND")
        print("REASON: no comp CSVs found in the pool")
        return 0
    result = run_engine(subject, pool)
    if args.artifact:
        with open(args.artifact, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2, default=str)
    print(format_block(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
