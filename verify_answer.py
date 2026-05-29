#!/usr/bin/env python3
"""
verify_answer.py — INDEPENDENT re-check of a comp engine run.

This file deliberately does NOT import comp_engine. It is a second, independent
implementation of the load/filter/trim/calculate pipeline plus the token spec.
Two independent implementations agreeing is the verification. If they diverge,
that is a real bug to fix — never paper over it.

It catches the exact failure that started this project: numbers that "look
computed" but fail their own math, and numbers claimed to "come from a query"
that no execution actually produced.

Checks performed against a run artifact (JSON from comp_engine.run_engine) + the
live comp pool:
  1. Re-load the pool and independently re-derive the candidate comp set.
  2. Recompute the RUN TOKEN from that independent set + subject + timestamp,
     and confirm it equals the artifact's token (provenance).
  3. Independently re-derive the status path (VALID/THIN/UNRELIABLE/NOT FOUND).
  4. For VALID runs: independently recompute median ppsf, ARV, repairs, Max
     Offer, opening range, walk-away, and confirm each equals the artifact.
  5. Confirm internal math is self-consistent (Max Offer really equals
     ARV*0.70 - repairs - fee, ranges and walk-away derived correctly).
  6. Confirm every comp named in COMPS INCLUDED exists in the pool with the
     stated $/sqft.

Returns PASS or FAIL. A FAIL means: show NO number. Surface
"VERIFY FAILED, do not use."

Usage:
    python3 verify_answer.py --artifact run.json --pool docs/comp-export-sample.csv
"""

import argparse
import csv
import hashlib
import json
import os
import re
import statistics
import sys
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Constants — duplicated from the spec. If these drift from comp_engine.py the
# verifier will (correctly) fail runs; keep both in sync via the README spec.
# ---------------------------------------------------------------------------
FEE = 15000
ARV_MULTIPLIER = 0.70
THIN_MINIMUM = 5
SQFT_TOLERANCE = 0.20
SPREAD_LIMIT_PCT = 30.0
MONTHS_FRESH = 12
REPAIR_PPSF = {"light": 20, "moderate": 35, "heavy": 55}

CLOSED_STATUSES = {"sold", "closed", "closed sale", "sld"}
NON_SALE_STATUSES = {
    "active", "pending", "canceled", "cancelled", "off market", "off-market",
    "failed", "withdrawn", "expired", "coming soon", "temp off market",
}

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
# Helpers (independent reimplementation)
# ---------------------------------------------------------------------------
def _norm_header(h):
    return re.sub(r"\s+", " ", (h or "").strip().lower())


def address_key(street, city="", state="", zipc=""):
    s = (street or "").lower()
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
    if v is None:
        return None
    m = re.match(r"^(\d{5})", str(v).strip())
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


def round100(x):
    return int(round(x / 100.0)) * 100


def is_closed_sale(status):
    s = (status or "").strip().lower()
    if s in CLOSED_STATUSES:
        return True
    if s in NON_SALE_STATUSES:
        return False
    return s.startswith("sold") or s.startswith("closed") or "sold" in s


def spread_pct(values):
    if not values:
        return 0.0
    med = statistics.median(values)
    if med == 0:
        return 0.0
    return (max(values) - min(values)) / med * 100.0


# ---------------------------------------------------------------------------
# Token spec — MUST stay byte-identical to comp_engine.make_token et al.
# ---------------------------------------------------------------------------
def canonical_subject(subject):
    return json.dumps({
        "address_key": address_key(subject["address"], zipc=subject["zip"]),
        "zip": parse_zip(subject["zip"]),
        "beds": float(subject["beds"]),
        "baths": float(subject["baths"]),
        "sqft": float(subject["sqft"]),
        "repair_level": subject["repair_level"],
    }, sort_keys=True, separators=(",", ":"))


def canonical_comp(r):
    return {
        "address_key": r["address_key"],
        "zip": r["zip"],
        "beds": r["beds"],
        "baths": r["baths"],
        "sqft": r["sqft"],
        "price": r["price"],
        "date": r["date_sold_str"],
    }


def canonical_comp_list_from_canon(items):
    items = list(items)
    items.sort(key=lambda d: json.dumps(d, sort_keys=True, separators=(",", ":")))
    return json.dumps(items, sort_keys=True, separators=(",", ":"))


def make_token(subject, canon_comps, timestamp):
    payload = (
        canonical_subject(subject)
        + "|" + canonical_comp_list_from_canon(canon_comps)
        + "|" + timestamp
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------------------
# Independent pool load + candidate derivation
# ---------------------------------------------------------------------------
def load_pool(paths):
    raw = []
    for path in paths:
        if not os.path.isfile(path):
            continue
        with open(path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.reader(fh)
            try:
                header = next(reader)
            except StopIteration:
                continue
            colmap = {}
            for i, h in enumerate(header):
                canon = HEADER_MAP.get(_norm_header(h))
                if canon:
                    colmap[i] = canon
            for cells in reader:
                if not any(c.strip() for c in cells):
                    continue
                rec = {colmap[i]: val for i, val in enumerate(cells) if i in colmap}
                raw.append(rec)

    normalized = []
    for rec in raw:
        zipc = parse_zip(rec.get("zip"))
        if not zipc:
            continue
        street = (rec.get("address") or "").strip()
        city = (rec.get("city") or "").strip()
        state = (rec.get("state") or "").strip().upper()
        sqft = to_float(rec.get("sqft"))
        price = to_float(rec.get("price"))
        d = parse_date(rec.get("date_sold"))
        normalized.append({
            "address": street, "city": city, "state": state, "zip": zipc,
            "beds": to_float(rec.get("beds")), "baths": to_float(rec.get("baths")),
            "sqft": sqft, "price": price,
            "mls_status": _norm_header(rec.get("mls_status")),
            "date_sold": d, "date_sold_str": (d.isoformat() if d else ""),
            "address_key": address_key(street, city, state, zipc),
            "full_address": f"{street}, {city}, {state} {zipc}".strip(),
            "ppsf": (price / sqft) if (price and sqft and sqft > 0) else None,
        })

    seen, deduped = set(), []
    for r in normalized:
        k = (r["address_key"], r["price"], r["date_sold_str"], r["sqft"])
        if k in seen:
            continue
        seen.add(k)
        deduped.append(r)
    return deduped


def derive_candidates(rows, subject):
    s_zip = parse_zip(subject["zip"])
    s_beds, s_baths, s_sqft = subject["beds"], subject["baths"], subject["sqft"]
    lo, hi = s_sqft * (1 - SQFT_TOLERANCE), s_sqft * (1 + SQFT_TOLERANCE)
    out = []
    for r in rows:
        if not is_closed_sale(r["mls_status"]):
            continue
        if not (r["price"] and r["price"] > 0):
            continue
        if r["zip"] != s_zip:
            continue
        if r["beds"] is None or abs(r["beds"] - s_beds) > 1:
            continue
        if r["baths"] is None or abs(r["baths"] - s_baths) > 1:
            continue
        if r["sqft"] is None or not (lo <= r["sqft"] <= hi):
            continue
        if r["ppsf"] is None:
            continue
        out.append(r)
    return out


def iqr_trim(survivors):
    ppsfs = [r["ppsf"] for r in survivors]
    if len(ppsfs) < 4:
        return list(survivors)
    qs = statistics.quantiles(ppsfs, n=4, method="inclusive")
    q1, q3 = qs[0], qs[2]
    iqr = q3 - q1
    fence_lo, fence_hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    return [r for r in survivors if fence_lo <= r["ppsf"] <= fence_hi]


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
def verify(artifact, pool_paths):
    """Return (ok: bool, problems: list[str], notes: list[str])."""
    problems = []
    notes = []
    subject = artifact["subject"]
    timestamp = artifact["timestamp"]
    status = artifact["status"]

    rows = load_pool(pool_paths)
    cand = derive_candidates(rows, subject)
    cand_canon = [canonical_comp(r) for r in cand]

    # ---- Check 1: independent candidate count matches ----
    if len(cand) != artifact["comps_found"]:
        problems.append(
            f"candidate count mismatch: engine={artifact['comps_found']} "
            f"verifier={len(cand)}"
        )

    # ---- Check 2: token reproduces from independent candidate set ----
    recomputed_token = make_token(subject, cand_canon, timestamp)
    if recomputed_token != artifact["token"]:
        problems.append(
            f"RUN TOKEN mismatch: artifact={artifact['token']} "
            f"recomputed={recomputed_token} (data/subject/timestamp do not hash "
            f"to the claimed token)"
        )
    else:
        notes.append("token reproduces from pool")

    # ---- Check 3: status-path independent re-derivation ----
    indep_status, indep_numbers = _rederive_status(subject, cand)
    if indep_status != status:
        problems.append(
            f"status mismatch: engine={status} verifier={indep_status}"
        )

    if status == "VALID":
        numbers = artifact.get("numbers") or {}

        # ---- Check 4: independent numbers match ----
        if indep_numbers is None:
            problems.append("engine says VALID but verifier produced no numbers")
        else:
            for key in ("arv", "repairs", "max_offer", "opening_low",
                        "opening_high", "walk_away"):
                a = numbers.get(key)
                b = indep_numbers.get(key)
                if a != b:
                    problems.append(f"{key} mismatch: engine={a} verifier={b}")

        # ---- Check 5: internal math self-consistency on engine's own numbers ----
        _check_internal_math(subject, numbers, problems)

        # ---- Check 6: comps included exist in pool with stated ppsf ----
        _check_included(artifact.get("comps_included", []), rows, problems)

    elif status in ("THIN", "UNRELIABLE", "DATA NOT FOUND"):
        # numbers must be absent for non-valid statuses
        if artifact.get("numbers"):
            problems.append(f"status {status} must carry NO numbers, but numbers present")
    else:
        problems.append(f"unknown status {status!r}")

    return (len(problems) == 0, problems, notes)


def _rederive_status(subject, cand):
    if len(cand) == 0:
        return "DATA NOT FOUND", None
    if len(cand) < THIN_MINIMUM:
        return "THIN", None
    trimmed = iqr_trim(cand)
    if len(trimmed) < THIN_MINIMUM:
        return "THIN", None
    spread_after = spread_pct([r["ppsf"] for r in trimmed])
    if spread_after > SPREAD_LIMIT_PCT:
        return "UNRELIABLE", None
    median_ppsf = statistics.median([r["ppsf"] for r in trimmed])
    sqft = subject["sqft"]
    arv = round100(median_ppsf * sqft)
    repairs = round100(REPAIR_PPSF[subject["repair_level"]] * sqft)
    max_offer = round100(arv * ARV_MULTIPLIER - repairs - FEE)
    return "VALID", {
        "arv": arv, "repairs": repairs, "max_offer": max_offer,
        "opening_low": round100(max_offer - 25000),
        "opening_high": round100(max_offer - 15000),
        "walk_away": max_offer,
    }


def _check_internal_math(subject, numbers, problems):
    try:
        arv = numbers["arv"]
        repairs = numbers["repairs"]
        max_offer = numbers["max_offer"]
    except (KeyError, TypeError):
        problems.append("VALID run missing core numbers (arv/repairs/max_offer)")
        return
    expect_repairs = round100(REPAIR_PPSF[subject["repair_level"]] * subject["sqft"])
    if repairs != expect_repairs:
        problems.append(
            f"repairs internally inconsistent: stated={repairs} "
            f"expected={expect_repairs}"
        )
    expect_max = round100(arv * ARV_MULTIPLIER - repairs - FEE)
    if max_offer != expect_max:
        problems.append(
            f"Max Offer internally inconsistent: stated={max_offer} "
            f"expected ARV*{ARV_MULTIPLIER}-repairs-{FEE}={expect_max}"
        )
    if numbers.get("walk_away") != max_offer:
        problems.append("walk-away must equal Max Offer")
    if numbers.get("opening_low") != round100(max_offer - 25000):
        problems.append("opening_low must equal Max Offer - 25000")
    if numbers.get("opening_high") != round100(max_offer - 15000):
        problems.append("opening_high must equal Max Offer - 15000")


def _check_included(included, rows, problems):
    by_key = {}
    for r in rows:
        if r["ppsf"] is not None:
            by_key.setdefault(r["address_key"], []).append(r["ppsf"])
    for c in included:
        key = address_key(c["full_address"].split(",")[0])
        ppsfs = by_key.get(key)
        if not ppsfs:
            problems.append(f"included comp not found in pool: {c['full_address']}")
            continue
        if not any(abs(p - c["ppsf"]) <= 0.01 for p in ppsfs):
            problems.append(
                f"included comp ppsf mismatch for {c['full_address']}: "
                f"stated {c['ppsf']}, pool has {[round(p,2) for p in ppsfs]}"
            )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None):
    p = argparse.ArgumentParser(description="Independent verifier for a comp run")
    p.add_argument("--artifact", required=True, help="JSON run artifact path")
    p.add_argument("--pool", nargs="*", required=True, help="comp CSV path(s)")
    args = p.parse_args(argv)

    with open(args.artifact, encoding="utf-8") as fh:
        artifact = json.load(fh)

    ok, problems, notes = verify(artifact, args.pool)
    if ok:
        print("VERIFY: PASS")
        for n in notes:
            print(f"  - {n}")
        return 0
    print("VERIFY: FAIL")
    print("VERIFY FAILED, do not use.")
    for prob in problems:
        print(f"  - {prob}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
