#!/usr/bin/env python3
"""run_comp.py - the operator entrypoint. The ONLY command an operator runs.

Per subject property it: loads the pool, runs comp_engine, runs verify_answer,
appends one audit row to comp_run_log.csv, and prints ONLY the verified token
block (or a failure / no-number status). The operator pastes this stdout
verbatim. It does not retype, summarize, or adjust the numbers.

If the verifier FAILS, no number is shown -- the output is
"VERIFY FAILED, do not use" plus the reasons.
"""

import argparse
import csv
import os
from datetime import datetime, timezone

import comp_engine
import verify_answer

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(HERE, "comp_run_log.csv")
LOG_HEADER = [
    "logged_at", "run_token", "timestamp", "address", "zip", "beds", "baths",
    "sqft", "repair_level", "status", "verifier", "comps_found", "comps_used",
    "spread_before", "spread_after", "arv", "max_offer", "opening_low",
    "opening_high", "walk_away", "no_number_reason",
]


def append_log(result, verifier_result, failures):
    new_file = not os.path.exists(LOG_PATH)
    s = result["subject"]
    row = {
        "logged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_token": result["run_token"],
        "timestamp": result["timestamp"],
        "address": s["address"],
        "zip": s["zip"],
        "beds": s["beds"],
        "baths": s["baths"],
        "sqft": s["sqft"],
        "repair_level": s["repair_level"],
        "status": result["status"],
        "verifier": verifier_result if not failures else f"{verifier_result}: {'; '.join(failures)}",
        "comps_found": result["comps_found"],
        "comps_used": result["comps_used"],
        "spread_before": result["spread_before"],
        "spread_after": result["spread_after"],
        "arv": result["arv"],
        "max_offer": result["max_offer"],
        "opening_low": result["opening_low"],
        "opening_high": result["opening_high"],
        "walk_away": result["walk_away"],
        "no_number_reason": result["no_number_reason"],
    }
    with open(LOG_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_HEADER)
        if new_file:
            w.writeheader()
        w.writerow(row)


def main(argv=None):
    p = argparse.ArgumentParser(description="SwiftClose comp operator entrypoint.")
    p.add_argument("--address", required=True)
    p.add_argument("--zip", required=True)
    p.add_argument("--beds", required=True)
    p.add_argument("--baths", required=True)
    p.add_argument("--sqft", required=True)
    p.add_argument("--repair", required=True, choices=["light", "moderate", "heavy"])
    p.add_argument("--data", default=os.path.join(HERE, "data"))
    p.add_argument("--params", default=os.path.join(HERE, "comp_params.json"))
    p.add_argument("--timestamp", default=None)
    args = p.parse_args(argv)

    params = comp_engine.load_params(args.params)
    subject = comp_engine.build_subject(args)
    try:
        result = comp_engine.analyze(subject, args.data, params, timestamp=args.timestamp)
    except (ValueError, FileNotFoundError, OSError) as e:
        # No number was produced. Fail loudly but cleanly so the operator
        # reports a data error, never a guessed number.
        print("DATA ERROR, no number produced")
        print(f"  - {e}")
        return 2

    passed, failures = verify_answer.verify(result, args.data)
    append_log(result, "PASS" if passed else "FAIL", failures)

    if not passed:
        print("VERIFY FAILED, do not use")
        for msg in failures:
            print(f"  - {msg}")
        return 1

    print(comp_engine.render_block(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
