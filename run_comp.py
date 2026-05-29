#!/usr/bin/env python3
"""
run_comp.py — the OPERATOR entrypoint. The single command the human-facing
Claude runs per property.

It is the ONLY sanctioned path by which a comp number reaches a human:
    engine executed  ->  verifier passed  ->  token block printed verbatim.
No other path exists. If the verifier fails, NO number is printed.

What it does, every run:
  1. Discover/load the comp pool, run comp_engine, run verify_answer.
  2. Append one row to comp_run_log.csv (append-only audit trail).
  3. Print ONLY the verified token block, or the failure status.

The human-facing Claude pastes this stdout verbatim. It does not retype,
summarize, round, or "sanity check" the numbers. Copy the block or say NOT RUN.

Usage:
    python3 run_comp.py --address "123 Main St" --zip 77089 \
        --beds 3 --baths 2 --sqft 1850 --repair moderate

    # explicit pool instead of auto-discovery:
    python3 run_comp.py ... --pool docs/comp-export-sample.csv other.csv
"""

import argparse
import csv
import json
import os
import sys

import comp_engine
import verify_answer

LOG_PATH = "comp_run_log.csv"
LOG_HEADER = [
    "timestamp", "address", "zip", "beds", "baths", "sqft", "repair_level",
    "comps_found", "comps_used", "spread_before", "spread_after",
    "status", "token", "verifier", "verify_problems",
    "arv", "max_offer", "opening_low", "opening_high", "walk_away",
    "no_number_reason",
]


def append_log(result, verify_ok, problems, log_path=LOG_PATH):
    subject = result["subject"]
    n = result.get("numbers") or {}
    status = result["status"]
    no_number_reason = "" if status == "VALID" else status
    row = {
        "timestamp": result["timestamp"],
        "address": subject["address"],
        "zip": subject["zip"],
        "beds": subject["beds"],
        "baths": subject["baths"],
        "sqft": subject["sqft"],
        "repair_level": subject["repair_level"],
        "comps_found": result["comps_found"],
        "comps_used": len(result.get("comps_used", [])),
        "spread_before": result.get("spread_before"),
        "spread_after": result.get("spread_after"),
        "status": status,
        "token": result["token"],
        "verifier": "PASS" if verify_ok else "FAIL",
        "verify_problems": " | ".join(problems),
        "arv": n.get("arv", ""),
        "max_offer": n.get("max_offer", ""),
        "opening_low": n.get("opening_low", ""),
        "opening_high": n.get("opening_high", ""),
        "walk_away": n.get("walk_away", ""),
        "no_number_reason": no_number_reason,
    }
    new_file = not os.path.exists(log_path)
    with open(log_path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=LOG_HEADER)
        if new_file:
            writer.writeheader()
        writer.writerow(row)


def build_arg_parser():
    p = argparse.ArgumentParser(description="SwiftClose comp operator entrypoint")
    p.add_argument("--address", required=True)
    p.add_argument("--zip", required=True)
    p.add_argument("--beds", required=True, type=float)
    p.add_argument("--baths", required=True, type=float)
    p.add_argument("--sqft", required=True, type=float)
    p.add_argument("--repair", required=True, help="light | moderate | heavy")
    p.add_argument("--pool", nargs="*", default=None,
                   help="explicit comp CSV path(s); default = discover *.csv")
    p.add_argument("--artifact", default=None,
                   help="optional path to also write the JSON run artifact")
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

    pool = args.pool if args.pool else comp_engine.discover_pool(log_name=LOG_PATH)
    if not pool:
        print("RUN TOKEN: (none)")
        print("COMP SET STATUS: DATA NOT FOUND")
        print("REASON: no comp CSVs found in the pool")
        return 2

    # 1. Run engine.
    result = comp_engine.run_engine(subject, pool)

    if args.artifact:
        with open(args.artifact, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2, default=str)

    # 2. Independent verify.
    verify_ok, problems, _notes = verify_answer.verify(result, pool)

    # 3. Append audit log (always, pass or fail).
    append_log(result, verify_ok, problems)

    # 4. Print ONLY a verified block, or the failure.
    if not verify_ok:
        print("VERIFY: FAIL")
        print("VERIFY FAILED, do not use.")
        print(f"RUN TOKEN: {result['token']}")
        print(f"COMP SET STATUS: {result['status']}")
        for prob in problems:
            print(f"  - {prob}")
        return 1

    print(comp_engine.format_block(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
