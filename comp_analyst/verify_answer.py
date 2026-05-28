#!/usr/bin/env python3
"""verify_answer.py - independent re-check of a comp_engine result.

This module DELIBERATELY does NOT import comp_engine. It re-implements the
loader, the parsing rules, and the arithmetic in its own code path so that a bug
(or fabrication) in the engine cannot hide behind shared code. Both files follow
the parsing + token spec documented in README.md; verification passes only when
the two independent implementations agree.

Given an engine result (JSON) and the comp data folder it:
  1. Recomputes the run token from (subject + sorted rows used + timestamp) and
     confirms it matches the printed token.
  2. Re-loads the pool and confirms every comp named in the block actually
     exists in the data.
  3. For a VALID result, recomputes median ppsf, ARV, repairs, max offer,
     opening range and walk-away from the reloaded data and confirms every
     printed dollar figure matches exactly (after nearest-step rounding), and
     that the math is internally consistent.
  4. For a NO-NUMBER result (THIN / UNRELIABLE / DATA NOT FOUND) confirms the
     status is justified by the data and that NO dollar figure was emitted.

Returns PASS or FAIL. A FAIL means the block must NOT be shown as a number.
"""

import argparse
import csv
import glob
import hashlib
import json
import os
import re
from datetime import datetime
from statistics import median, quantiles

TOKEN_NAMESPACE = "SWIFTCLOSE-COMP-V1"
TOKEN_LEN = 32

# Independent copy of the alias table (kept in sync with the engine via README).
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
REQUIRED_FIELDS = ["street", "zip", "beds", "baths", "sqft", "price", "status"]
DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%d-%b-%Y",
                "%b %d, %Y", "%m-%d-%Y", "%Y%m%d"]


def _norm_text(s):
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _address_key(street):
    return _norm_text(street)


def _norm_zip(s):
    digits = re.sub(r"\D", "", s or "")
    return digits[:5] if len(digits) >= 5 else digits


def _parse_money(s):
    if s is None:
        return None
    t = re.sub(r"[^0-9.\-]", "", str(s))
    if t in ("", "-", ".", "-."):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _norm_date(s):
    s = (s or "").strip()
    if not s:
        return ""
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return s


def _money_key(price):
    return "" if price is None else str(int(round(price)))


def _sqft_key(sqft):
    return "" if sqft is None else str(int(round(sqft)))


def _numfmt(x):
    return f"{x:g}" if x is not None else ""


def _round_step(x, step):
    return int(round(x / step)) * step


def _resolve_columns(headers):
    norm = {}
    for i, h in enumerate(headers):
        nh = _norm_text(h)
        norm.setdefault(nh, i)
    mapping = {}
    for field, aliases in COLUMN_ALIASES.items():
        idx = None
        for alias in aliases:
            na = _norm_text(alias)
            if na in norm:
                idx = norm[na]
                break
        mapping[field] = idx
    missing = [f for f in REQUIRED_FIELDS if mapping.get(f) is None]
    if missing:
        raise ValueError(f"verifier: required field(s) {missing} not found in {headers}")
    return mapping


def _cell(raw, idx):
    if idx is None or idx >= len(raw):
        return ""
    return raw[idx]


def _classify_status(raw):
    t = _norm_text(raw)
    if not t:
        return "excluded"
    for kw in ("active", "pending", "cancel", "withdraw", "expired", "fail",
               "contingent", "coming soon", "off market", "offmarket", "hold",
               "temp off", "backup"):
        if kw in t:
            return "excluded"
    for kw in ("sold", "closed", "comp"):
        if kw in t:
            return "sold"
    return "excluded"


def _load_index(folder):
    """Independently reload the pool and index every row by its dedupe key so
    comps named in the block can be looked up."""
    files = sorted(glob.glob(os.path.join(folder, "*.csv")))
    index = {}
    for path in files:
        if os.path.basename(path) == "comp_run_log.csv":
            continue
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            try:
                headers = next(reader)
            except StopIteration:
                continue
            mapping = _resolve_columns(headers)
            for raw in reader:
                if not any((c or "").strip() for c in raw):
                    continue
                street = _cell(raw, mapping["street"])
                zipc = _norm_zip(_cell(raw, mapping["zip"]))
                if not zipc:
                    continue
                price = _parse_money(_cell(raw, mapping["price"]))
                sqft = _parse_money(_cell(raw, mapping["sqft"]))
                date_sold = _norm_date(_cell(raw, mapping.get("date_sold")))
                key = (_address_key(street), _money_key(price), date_sold, _sqft_key(sqft))
                index.setdefault(key, {
                    "address_key": _address_key(street),
                    "price": price,
                    "sqft": sqft,
                    "date_sold": date_sold,
                    "status": _classify_status(_cell(raw, mapping["status"])),
                    "zip": zipc,
                })
    return index


def _canonical_payload(subject, comps, timestamp):
    subj = "|".join([
        subject["address_key"], subject["zip"], _numfmt(subject["beds"]),
        _numfmt(subject["baths"]), str(int(round(subject["sqft"]))),
        subject["repair_level"],
    ])
    row_strs = sorted(
        "|".join([c["address_key"], _money_key(c["price"]),
                  c["date_sold"] or "", _sqft_key(c["sqft"])])
        for c in comps
    )
    return "\n".join([TOKEN_NAMESPACE, subj, "||".join(row_strs), timestamp])


def _make_token(subject, comps, timestamp):
    payload = _canonical_payload(subject, comps, timestamp)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:TOKEN_LEN]


def _spread_pct(ppsfs):
    if not ppsfs:
        return 0.0
    m = median(ppsfs)
    return (max(ppsfs) - min(ppsfs)) / m * 100.0 if m else 0.0


def verify(result, folder):
    """Return (passed: bool, failures: list[str])."""
    failures = []
    subject = result["subject"]
    params = result["params"]
    step = params["dollar_rounding"]
    status = result["status"]
    comps = result["comps_included"]

    # 1. Run token must re-hash from (subject + rows used + timestamp).
    expected_token = _make_token(subject, comps, result["timestamp"])
    if expected_token != result["run_token"]:
        failures.append(
            f"run token mismatch: printed {result['run_token']!r} but data hashes "
            f"to {expected_token!r}")

    # 2. Every named comp must exist in the reloaded data; pull authoritative
    #    price/sqft from the data (not from the block) for recomputation.
    index = _load_index(folder)
    matched_rows = []
    for c in comps:
        key = (c["address_key"], _money_key(c["price"]),
               c["date_sold"] or "", _sqft_key(c["sqft"]))
        row = index.get(key)
        if row is None:
            failures.append(f"comp named in block not found in data: {c['address']}")
            continue
        if row["sqft"] in (None, 0):
            failures.append(f"comp has no usable sqft in data: {c['address']}")
            continue
        matched_rows.append(row)
        # ppsf printed in the block must match the data.
        recomputed_ppsf = round(row["price"] / row["sqft"], 2)
        if recomputed_ppsf != c["ppsf"]:
            failures.append(
                f"ppsf mismatch for {c['address']}: block {c['ppsf']} vs data "
                f"{recomputed_ppsf}")

    if status == "VALID":
        if len(matched_rows) == len(comps) and matched_rows:
            ppsfs = [r["price"] / r["sqft"] for r in matched_rows]
            med = median(ppsfs)
            repair_ppsf = params["repair_ppsf"][subject["repair_level"]]
            sqft = subject["sqft"]
            raw_arv = med * sqft
            raw_repairs = repair_ppsf * sqft
            raw_max = raw_arv * params["wholesale_factor"] - raw_repairs - params["assignment_fee"]
            expect = {
                "median_ppsf": round(med, 2),
                "arv": _round_step(raw_arv, step),
                "repairs": _round_step(raw_repairs, step),
                "max_offer": _round_step(raw_max, step),
                "opening_low": _round_step(raw_max - params["opening_offset_low"], step),
                "opening_high": _round_step(raw_max - params["opening_offset_high"], step),
                "walk_away": _round_step(raw_max, step),
            }
            for field, want in expect.items():
                got = result.get(field)
                if got != want:
                    failures.append(f"{field} mismatch: printed {got} vs recomputed {want}")
            # Internal consistency: max offer is exactly factor*ARV - repairs - fee.
            if expect["max_offer"] != _round_step(
                    raw_arv * params["wholesale_factor"] - raw_repairs - params["assignment_fee"], step):
                failures.append("internal math inconsistency in max offer")
            # Status justification: enough comps, spread within threshold.
            if len(matched_rows) < params["thin_minimum"]:
                failures.append("VALID but comps_used below thin minimum")
            sa = round(_spread_pct(ppsfs), 2)
            if sa > params["spread_threshold_pct"]:
                failures.append(
                    f"VALID but recomputed spread {sa}% exceeds threshold")
    elif status in ("THIN", "UNRELIABLE", "DATA NOT FOUND"):
        # NO dollar figure may be present.
        for field in ("arv", "max_offer", "opening_low", "opening_high", "walk_away"):
            if result.get(field) is not None:
                failures.append(f"{status} result must not contain {field}")
        if status == "DATA NOT FOUND" and comps:
            failures.append("DATA NOT FOUND but comps were listed")
        if status == "THIN" and len(comps) >= params["thin_minimum"]:
            failures.append("THIN but comps_used meets thin minimum")
        if status == "UNRELIABLE" and matched_rows and len(matched_rows) == len(comps):
            sa = round(_spread_pct([r["price"] / r["sqft"] for r in matched_rows]), 2)
            if sa <= params["spread_threshold_pct"]:
                failures.append(
                    f"UNRELIABLE but recomputed spread {sa}% is within threshold")
    else:
        failures.append(f"unknown status: {status!r}")

    return (len(failures) == 0), failures


def main(argv=None):
    p = argparse.ArgumentParser(description="Independently verify a comp_engine result.")
    p.add_argument("--result", required=True, help="Path to engine result JSON ('-' for stdin).")
    p.add_argument("--data", required=True, help="Comp data folder.")
    args = p.parse_args(argv)

    if args.result == "-":
        import sys
        result = json.load(sys.stdin)
    else:
        with open(args.result, encoding="utf-8") as f:
            result = json.load(f)

    passed, failures = verify(result, args.data)
    if passed:
        print("VERIFIER: PASS")
        return 0
    print("VERIFIER: FAIL")
    for msg in failures:
        print(f"  - {msg}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
