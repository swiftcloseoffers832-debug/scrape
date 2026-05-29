#!/usr/bin/env python3
"""
Test suite for the SwiftClose comp analyst system.

Run: python3 tests/test_comp_system.py
Exits non-zero if any assertion fails. Stdlib only.

The point of these tests is the trust boundary: a tampered or impossible number
MUST be caught by verify_answer, and gates MUST refuse to emit a number.
"""
import copy
import csv as _csv
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import comp_engine
import verify_answer

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixture_77089.csv")
SAMPLE = os.path.join(ROOT, "docs", "comp-export-sample.csv")

PASSED = 0
FAILED = 0


def check(name, cond):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"PASS: {name}")
    else:
        FAILED += 1
        print(f"FAIL: {name}")


def subj(**kw):
    base = dict(address="200 Subject St", zip="77089", beds=3, baths=2,
                sqft=1850, repair_level="moderate")
    base.update(kw)
    return base


# ---- VALID path ----
res = comp_engine.run_engine(subj(), [FIXTURE])
check("valid: status VALID", res["status"] == "VALID")
check("valid: dedup dropped the duplicate (found==9)", res["comps_found"] == 9)
check("valid: IQR trimmed the outlier (used==8)", len(res["comps_used"]) == 8)
check("valid: ARV is 150ppsf*1850==277500", res["numbers"]["arv"] == 277500)
ok, probs, _ = verify_answer.verify(res, [FIXTURE])
check("valid: verifier PASS", ok and not probs)

# ---- Tamper: inflate ARV (the "looks computed but isn't" failure) ----
t = copy.deepcopy(res)
t["numbers"]["arv"] = 400000
ok, _, _ = verify_answer.verify(t, [FIXTURE])
check("tamper ARV: verifier FAIL", not ok)

# ---- Tamper: break Max Offer internal math only ----
t = copy.deepcopy(res)
t["numbers"]["max_offer"] = t["numbers"]["max_offer"] + 50000
ok, _, _ = verify_answer.verify(t, [FIXTURE])
check("tamper Max Offer: verifier FAIL", not ok)

# ---- Tamper: forge the run token ----
t = copy.deepcopy(res)
t["token"] = "deadbeef" * 4
ok, _, _ = verify_answer.verify(t, [FIXTURE])
check("tamper token: verifier FAIL", not ok)

# ---- Tamper: alter the subject so the token no longer reproduces ----
t = copy.deepcopy(res)
t["subject"]["sqft"] = 1850.0001
ok, _, _ = verify_answer.verify(t, [FIXTURE])
check("tamper subject: verifier FAIL (token no longer reproduces)", not ok)

# ---- Gate: THIN (sample file has only 1 matching comp for a 1-comp subject) ----
res_thin = comp_engine.run_engine(subj(address="10430 Sageyork Dr"), [SAMPLE])
check("thin: status THIN", res_thin["status"] == "THIN")
check("thin: NO numbers", res_thin["numbers"] is None)
ok, _, _ = verify_answer.verify(res_thin, [SAMPLE])
check("thin: verifier PASS (no number to forge)", ok)

# ---- Gate: DATA NOT FOUND (zip with no comps) ----
res_nf = comp_engine.run_engine(subj(zip="99999"), [FIXTURE])
check("not found: status DATA NOT FOUND", res_nf["status"] == "DATA NOT FOUND")
check("not found: NO numbers", res_nf["numbers"] is None)

# ---- Gate: UNRELIABLE via a high-spread synthetic pool ----
spread_path = os.path.join(HERE, "_spread.csv")
with open(spread_path, "w", newline="") as fh:
    w = _csv.writer(fh)
    w.writerow(["Address", "City", "State", "ZIP", "Beds", "Baths", "SqFt",
                "Price", "MLS Status", "Date Sold", "Property Type"])
    for i, p in enumerate([120, 145, 170, 195, 220, 245]):  # wide, survives IQR
        w.writerow([f"{i} Wide St", "Houston", "TX", "77089", 3, 2, 1850,
                    int(1850 * p), "Sold", "2025-09-01", "Single Family"])
res_unrel = comp_engine.run_engine(subj(), [spread_path])
check("unreliable: status UNRELIABLE", res_unrel["status"] == "UNRELIABLE")
check("unreliable: NO numbers", res_unrel["numbers"] is None)
os.remove(spread_path)

# ---- ZIP not regexed off street numbers (the 10430 failure) ----
zip_path = os.path.join(HERE, "_zip.csv")
with open(zip_path, "w", newline="") as fh:
    w = _csv.writer(fh)
    w.writerow(["Address", "City", "State", "ZIP", "Beds", "Baths", "SqFt",
                "Price", "MLS Status", "Date Sold", "Property Type"])
    w.writerow(["10430 Sageyork Dr", "Houston", "TX", "77089", 3, 2, 1850,
                277500, "Sold", "2025-09-01", "Single Family"])
rows, _ = comp_engine.load_pool([zip_path])
check("zip: read from dedicated column, not street '10430'",
      rows[0]["zip"] == "77089")
os.remove(zip_path)

print(f"\n{PASSED} passed, {FAILED} failed")
sys.exit(1 if FAILED else 0)
