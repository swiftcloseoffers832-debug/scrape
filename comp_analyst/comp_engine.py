#!/usr/bin/env python3
"""comp_engine.py - the ONLY component that computes a SwiftClose comp/offer number.

Deterministic. Standard-library only. Never touches the network. Never guesses.

Given a subject property and a folder of comp CSVs it: loads + normalizes the
pool, filters to valid closed sales, runs validation gates, and ONLY if the gates
pass computes ARV and offer numbers. Every result is stamped with a run token =
sha256(subject + sorted comp rows used + timestamp). The token is the proof that a
number came from THIS execution against THIS data.

If a required column cannot be mapped, it raises (it does not guess). If the data
is insufficient it returns a NO-NUMBER status (DATA NOT FOUND / THIN / UNRELIABLE).

The math in this file never self-modifies. Tunable parameters live in
comp_params.json and are changed by a human, deliberately and visibly.
"""

import argparse
import csv
import glob
import hashlib
import json
import os
import re
from datetime import date, datetime, timezone
from statistics import median, quantiles

TOKEN_NAMESPACE = "SWIFTCLOSE-COMP-V1"
TOKEN_LEN = 32  # hex chars of the sha256 digest used as the run token

# Canonical field -> accepted header aliases (case-insensitive, punctuation-loose).
# Tune this table to the scraper's real headers; matching is first-alias-wins.
COLUMN_ALIASES = {
    "street": ["street address", "street", "address", "property address", "addr",
               "site address", "street name", "address 1", "address1", "full address"],
    "city": ["city", "municipality", "town"],
    "state": ["state", "st", "province", "state province"],
    "zip": ["zip code", "zip", "zipcode", "postal code", "postalcode", "zip5", "postal"],
    "beds": ["beds", "bed", "bedrooms", "br", "beds total", "total bedrooms", "no beds"],
    "baths": ["baths", "bath", "bathrooms", "ba", "baths total", "total bathrooms",
              "total baths", "full baths"],
    "sqft": ["sqft", "sq ft", "square feet", "square footage", "living area", "gla",
             "total sqft", "sqft total", "heated sqft", "living sqft", "approx sqft",
             "bldg sqft"],
    "price": ["close price", "sale price", "sold price", "closing price", "sales price",
              "price sold", "last sale price", "sale amount", "price"],
    "status": ["mls status", "status", "listing status", "sale status",
               "standard status", "mls_status"],
    "date_sold": ["close date", "sold date", "date sold", "closing date", "sale date",
                  "date_sold", "closed date", "settlement date", "sold on", "cod"],
}

# Required fields: if any of these cannot be mapped, the engine refuses to run.
REQUIRED_FIELDS = ["street", "zip", "beds", "baths", "sqft", "price", "status"]

DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%d-%b-%Y",
                "%b %d, %Y", "%m-%d-%Y", "%Y%m%d"]

# Status substrings that EXCLUDE a row (checked before the "sold" substrings).
EXCLUDE_STATUS_KW = ("active", "pending", "cancel", "withdraw", "expired", "fail",
                     "contingent", "coming soon", "off market", "offmarket", "hold",
                     "temp off", "backup")
# Status substrings that mark a row as a closed sale.
SOLD_STATUS_KW = ("sold", "closed", "comp")


# --------------------------------------------------------------------------- #
# Normalization helpers (the parsing spec is documented in README.md so that
# verify_answer.py can reproduce it independently).
# --------------------------------------------------------------------------- #

def norm_text(s):
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def normalize_header(h):
    return norm_text(h)


def address_key(street):
    return norm_text(street)


def norm_zip(s):
    digits = re.sub(r"\D", "", s or "")
    return digits[:5] if len(digits) >= 5 else digits


def parse_money(s):
    if s is None:
        return None
    t = re.sub(r"[^0-9.\-]", "", str(s))
    if t in ("", "-", ".", "-."):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def parse_num(s):
    return parse_money(s)


def parse_date(s):
    s = (s or "").strip()
    if not s:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def norm_date(s):
    d = parse_date(s)
    return d.isoformat() if d else (s or "").strip()


def classify_status(raw):
    t = norm_text(raw)
    if not t:
        return "excluded"
    for kw in EXCLUDE_STATUS_KW:
        if kw in t:
            return "excluded"
    for kw in SOLD_STATUS_KW:
        if kw in t:
            return "sold"
    return "excluded"


def money_key(price):
    return "" if price is None else str(int(round(price)))


def sqft_key(sqft):
    return "" if sqft is None else str(int(round(sqft)))


def numfmt(x):
    return f"{x:g}" if x is not None else ""


def round_step(x, step):
    return int(round(x / step)) * step


def months_between(d, ref):
    return (ref.year - d.year) * 12 + (ref.month - d.month)


# --------------------------------------------------------------------------- #
# Load + normalize
# --------------------------------------------------------------------------- #

def resolve_columns(headers, source=""):
    """Map canonical fields to column indices. Raise if a required field is
    missing -- never guess which column is which."""
    norm = {}
    for i, h in enumerate(headers):
        nh = normalize_header(h)
        norm.setdefault(nh, i)
    mapping = {}
    for field, aliases in COLUMN_ALIASES.items():
        idx = None
        for alias in aliases:
            na = normalize_header(alias)
            if na in norm:
                idx = norm[na]
                break
        mapping[field] = idx
    missing = [f for f in REQUIRED_FIELDS if mapping.get(f) is None]
    if missing:
        raise ValueError(
            f"COLUMN MAPPING FAILED in {source or 'CSV'}: required field(s) "
            f"{missing} could not be matched to any header in {headers}. "
            f"Add the real header to COLUMN_ALIASES. Refusing to guess.")
    return mapping


def _cell(raw, idx):
    if idx is None or idx >= len(raw):
        return ""
    return raw[idx]


def extract_row(raw, mapping, source):
    street = _cell(raw, mapping["street"])
    city = _cell(raw, mapping.get("city"))
    state = _cell(raw, mapping.get("state"))
    zipc = norm_zip(_cell(raw, mapping["zip"]))
    full = ", ".join(p for p in [street.strip(), city.strip()] if p)
    tail = " ".join(p for p in [state.strip(), zipc] if p)
    full_address = (full + " " + tail).strip() if tail else full
    return {
        "street": street.strip(),
        "city": city.strip(),
        "state": state.strip(),
        "zip": zipc,
        "full_address": full_address,
        "address_key": address_key(street),
        "beds": parse_num(_cell(raw, mapping["beds"])),
        "baths": parse_num(_cell(raw, mapping["baths"])),
        "sqft": parse_num(_cell(raw, mapping["sqft"])),
        "price": parse_money(_cell(raw, mapping["price"])),
        "status": classify_status(_cell(raw, mapping["status"])),
        "date_sold": norm_date(_cell(raw, mapping.get("date_sold"))),
        "source": os.path.basename(source),
    }


def load_pool(folder):
    files = sorted(glob.glob(os.path.join(folder, "*.csv")))
    raw_rows = []
    for path in files:
        if os.path.basename(path) == "comp_run_log.csv":
            continue
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            try:
                headers = next(reader)
            except StopIteration:
                continue
            mapping = resolve_columns(headers, source=os.path.basename(path))
            for raw in reader:
                if not any((c or "").strip() for c in raw):
                    continue
                raw_rows.append(extract_row(raw, mapping, path))

    with_zip = [r for r in raw_rows if r["zip"]]
    dropped_no_zip = len(raw_rows) - len(with_zip)

    seen = set()
    deduped = []
    for r in with_zip:
        key = (r["address_key"], money_key(r["price"]), r["date_sold"], sqft_key(r["sqft"]))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)

    stats = {
        "files": [os.path.basename(p) for p in files
                  if os.path.basename(p) != "comp_run_log.csv"],
        "raw_rows": len(raw_rows),
        "dropped_no_zip": dropped_no_zip,
        "pool_after_dedupe": len(deduped),
    }
    return deduped, stats


# --------------------------------------------------------------------------- #
# Filter + gates + calculation
# --------------------------------------------------------------------------- #

def filter_valid(pool, subject, params, ref_date):
    m = params["match"]
    lo = subject["sqft"] * (1 - m["sqft_pct_tolerance"])
    hi = subject["sqft"] * (1 + m["sqft_pct_tolerance"])
    out = []
    for r in pool:
        if r["status"] != "sold":
            continue
        if r["price"] is None or r["price"] < params["sale_price_min"] \
                or r["price"] > params["sale_price_max"]:
            continue
        if r["zip"] != subject["zip"]:
            continue
        if r["sqft"] is None or r["sqft"] <= 0:
            continue
        if r["beds"] is None or abs(r["beds"] - subject["beds"]) > m["beds_tolerance"]:
            continue
        if r["baths"] is None or abs(r["baths"] - subject["baths"]) > m["baths_tolerance"]:
            continue
        if not (lo <= r["sqft"] <= hi):
            continue
        d = parse_date(r["date_sold"])
        flagged_old = bool(d and months_between(d, ref_date) > params["recency_months"])
        row = dict(r)
        row["ppsf"] = r["price"] / r["sqft"]
        row["flagged_old"] = flagged_old
        out.append(row)
    return out


def spread_pct(rows):
    ps = [r["ppsf"] for r in rows]
    if not ps:
        return 0.0
    m = median(ps)
    if not m:
        return 0.0
    return (max(ps) - min(ps)) / m * 100.0


def trim_iqr(rows, params):
    ps = sorted(r["ppsf"] for r in rows)
    if len(ps) < 2:
        return list(rows)
    q1, _q2, q3 = quantiles(ps, n=4, method="inclusive")
    iqr = q3 - q1
    mult = params["iqr_multiplier"]
    lo = q1 - mult * iqr
    hi = q3 + mult * iqr
    return [r for r in rows if lo <= r["ppsf"] <= hi]


def calculate(rows, subject, params):
    med = median(r["ppsf"] for r in rows)
    sqft = subject["sqft"]
    repair_ppsf = params["repair_ppsf"][subject["repair_level"]]
    step = params["dollar_rounding"]
    raw_arv = med * sqft
    raw_repairs = repair_ppsf * sqft
    raw_max = raw_arv * params["wholesale_factor"] - raw_repairs - params["assignment_fee"]
    max_offer = round_step(raw_max, step)
    return {
        "median_ppsf": round(med, 2),
        "repair_ppsf": repair_ppsf,
        "arv": round_step(raw_arv, step),
        "repairs": round_step(raw_repairs, step),
        "max_offer": max_offer,
        "opening_low": round_step(raw_max - params["opening_offset_low"], step),
        "opening_high": round_step(raw_max - params["opening_offset_high"], step),
        "walk_away": max_offer,
    }


# --------------------------------------------------------------------------- #
# Token + result assembly
# --------------------------------------------------------------------------- #

def canonical_payload(subject, rows_used, timestamp):
    subj = "|".join([
        subject["address_key"], subject["zip"], numfmt(subject["beds"]),
        numfmt(subject["baths"]), str(int(round(subject["sqft"]))),
        subject["repair_level"],
    ])
    row_strs = sorted(
        "|".join([r["address_key"], money_key(r["price"]),
                  r["date_sold"] or "", sqft_key(r["sqft"])])
        for r in rows_used
    )
    return "\n".join([TOKEN_NAMESPACE, subj, "||".join(row_strs), timestamp])


def make_token(subject, rows_used, timestamp):
    payload = canonical_payload(subject, rows_used, timestamp)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:TOKEN_LEN]


def _comps_included(rows_used):
    return sorted(
        ({
            "address": r["full_address"],
            "address_key": r["address_key"],
            "price": None if r["price"] is None else round(r["price"], 2),
            "sqft": None if r["sqft"] is None else round(r["sqft"], 2),
            "date_sold": r["date_sold"],
            "ppsf": round(r["ppsf"], 2),
            "flagged_old": r["flagged_old"],
        } for r in rows_used),
        key=lambda c: c["address_key"],
    )


def analyze(subject, folder, params, timestamp=None):
    """Run the full deterministic pipeline. Returns the result dict that
    run_comp.py prints and verify_answer.py independently re-checks."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ref_date = date.today()

    pool, stats = load_pool(folder)
    matched = filter_valid(pool, subject, params, ref_date)
    spread_before = round(spread_pct(matched), 2) if matched else None

    status = None
    rows_used = []
    spread_after = None
    numbers = None
    reason = None
    thin_min = params["thin_minimum"]
    threshold = params["spread_threshold_pct"]

    if len(matched) == 0:
        status = "DATA NOT FOUND"
        reason = "0 comps matched this subject in the pool."
    elif len(matched) < thin_min:
        status = "THIN"
        rows_used = matched
        reason = f"Only {len(matched)} valid comp(s); need >= {thin_min}."
    else:
        trimmed = trim_iqr(matched, params)
        spread_after = round(spread_pct(trimmed), 2)
        rows_used = trimmed
        if spread_after > threshold:
            status = "UNRELIABLE"
            reason = (f"price/sqft spread {spread_after}% exceeds "
                      f"{threshold}% after IQR trim.")
        else:
            status = "VALID"
            numbers = calculate(trimmed, subject, params)

    run_token = make_token(subject, rows_used, timestamp)

    result = {
        "schema_version": TOKEN_NAMESPACE,
        "run_token": run_token,
        "timestamp": timestamp,
        "subject": subject,
        "status": status,
        "comps_found": len(matched),
        "comps_used": len(rows_used),
        "comps_included": _comps_included(rows_used),
        "spread_before": spread_before,
        "spread_after": spread_after,
        "median_ppsf": numbers["median_ppsf"] if numbers else None,
        "repair_ppsf": numbers["repair_ppsf"] if numbers else None,
        "arv": numbers["arv"] if numbers else None,
        "repairs": numbers["repairs"] if numbers else None,
        "max_offer": numbers["max_offer"] if numbers else None,
        "opening_low": numbers["opening_low"] if numbers else None,
        "opening_high": numbers["opening_high"] if numbers else None,
        "walk_away": numbers["walk_away"] if numbers else None,
        "no_number_reason": reason,
        "pool_stats": stats,
        "params": params,
    }
    return result


def render_block(result):
    """Render the human-readable token block. Dollar lines appear ONLY for a
    VALID status -- a NO-NUMBER status never emits a dollar figure."""
    lines = [
        f"RUN TOKEN: {result['run_token']}",
        f"COMP SET STATUS: {result['status']}",
        f"COMPS FOUND: {result['comps_found']}",
        f"COMPS USED: {result['comps_used']}",
    ]
    if result["status"] == "VALID":
        lines += [
            f"ARV: ${result['arv']:,}",
            f"MAX OFFER: ${result['max_offer']:,}",
            f"OPENING OFFER RANGE: ${result['opening_low']:,} - ${result['opening_high']:,}",
            f"WALK AWAY ABOVE: ${result['walk_away']:,}",
        ]
    if result["comps_included"]:
        lines.append("COMPS INCLUDED:")
        for c in result["comps_included"]:
            flag = " [OLD]" if c["flagged_old"] else ""
            lines.append(f"  - {c['address']} | ${c['ppsf']:,.2f}/sqft{flag}")
    before = "n/a" if result["spread_before"] is None else f"{result['spread_before']}%"
    after = "n/a" if result["spread_after"] is None else f"{result['spread_after']}%"
    lines.append(f"SPREAD: {before} -> {after}")
    if result["no_number_reason"]:
        lines.append(f"NOTE: {result['no_number_reason']}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def load_params(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_subject(args):
    return {
        "address": args.address,
        "address_key": address_key(args.address),
        "zip": norm_zip(args.zip),
        "beds": float(args.beds),
        "baths": float(args.baths),
        "sqft": float(args.sqft),
        "repair_level": args.repair,
    }


def _default_params_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "comp_params.json")


def main(argv=None):
    p = argparse.ArgumentParser(description="SwiftClose deterministic comp engine.")
    p.add_argument("--address", required=True)
    p.add_argument("--zip", required=True)
    p.add_argument("--beds", required=True)
    p.add_argument("--baths", required=True)
    p.add_argument("--sqft", required=True)
    p.add_argument("--repair", required=True, choices=["light", "moderate", "heavy"])
    p.add_argument("--data", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
    p.add_argument("--params", default=_default_params_path())
    p.add_argument("--timestamp", default=None,
                   help="Override the run timestamp (for reproducible tokens/tests).")
    p.add_argument("--block", action="store_true", help="Print the human block instead of JSON.")
    args = p.parse_args(argv)

    params = load_params(args.params)
    subject = build_subject(args)
    result = analyze(subject, args.data, params, timestamp=args.timestamp)
    if args.block:
        print(render_block(result))
    else:
        print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
