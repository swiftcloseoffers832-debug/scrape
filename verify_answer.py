#!/usr/bin/env python3
"""
verify_answer.py — deterministic provenance gate for SwiftClose answers.

Reads an analyst's final answer text and confirms that every dollar figure in
it traces to a comp_engine.py run that was logged THIS session (a matching run
token AND a matching number). This is the external, non-LLM check that turns
the run-token scheme into an actual gate.

The guarantee only holds if this runs OUTSIDE the model: capture the analyst's
final text, run this script, and release the answer to the user only on exit 0.
A model "checking itself" is not a gate.

What it catches:
  - a fabricated dollar figure that was never produced by the engine
  - a real number quoted with a wrong / old / missing run token
  - a hand-edited (tampered) log row whose numbers no longer match its token

What it cannot do: stop the model from emitting text. It makes fabrication
detectable and blockable, not impossible to type.

Usage:
    # answer on stdin
    echo "...analyst answer..." | python verify_answer.py --session-id abc123

    # answer from a file, explicit log path
    python verify_answer.py --answer-file ans.txt --log comp_run_log.csv --session-id abc123

Exit codes:
    0  every dollar figure is provenanced (or the answer is exactly DATA NOT FOUND)
    1  at least one dollar figure has no logged run-token provenance this session
    2  usage / input error
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import sys

from comp_engine import (
    LOG_FILE,
    canonical_token_string,
    _current_session_id,
)

# Numbers that legitimately constitute an "offer" — the only dollar figures an
# answer to the user should contain. The engine's COMP DETAIL block (repairs,
# $/sqft, IQR fences) is audit information and must NOT be delivered as the
# answer; if it leaks in, those figures will (correctly) fail this gate.
VALUE_FIELDS = [
    "arv",
    "max_offer",
    "opening_range_low",
    "opening_range_high",
    "walk_away_above",
]

DOLLAR_RE = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)")
TOKEN_RE = re.compile(r"SC-[A-Za-z0-9_.:-]+?-\d+-[0-9a-f]{8}")
DATA_NOT_FOUND = "DATA NOT FOUND"


def to_int_dollars(raw: str) -> int | None:
    s = raw.replace(",", "").strip()
    if not s:
        return None
    try:
        return int(round(float(s)))
    except ValueError:
        return None


def token_hash8(token: str) -> str:
    """Last hyphen-delimited segment of the token is the 8-char hash."""
    return token.rsplit("-", 1)[-1] if token else ""


def load_valid_pairs(log_path: str, session_id: str) -> tuple[set[tuple[str, int]], list[str]]:
    """Return ({(run_token, dollar_value)} for this session's untampered VALID
    rows, [tokens of rows that failed the hash check])."""
    pairs: set[tuple[str, int]] = set()
    tampered: list[str] = []
    if not os.path.exists(log_path):
        return pairs, tampered

    with open(log_path, "r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if row.get("session_id", "") != session_id:
                continue
            if row.get("status", "") != "VALID":
                continue
            token = row.get("run_token", "") or ""
            recomputed = hashlib.sha256(
                canonical_token_string(row).encode("utf-8")
            ).hexdigest()
            # Row integrity: stored hash matches, and the token embeds it.
            if recomputed != row.get("input_hash", "") or token_hash8(token) != recomputed[:8]:
                tampered.append(token or "(no token)")
                continue
            for field in VALUE_FIELDS:
                val = to_int_dollars(row.get(field, "") or "")
                if val is not None:
                    pairs.add((token, val))
    return pairs, tampered


def verify(answer: str, log_path: str, session_id: str) -> tuple[int, list[str]]:
    """Return (exit_code, message_lines)."""
    lines: list[str] = []

    if answer.strip() == DATA_NOT_FOUND:
        return 0, ["OK: answer is DATA NOT FOUND — no number to verify."]

    pairs, tampered = load_valid_pairs(log_path, session_id)
    tokens_in_answer = set(TOKEN_RE.findall(answer))
    figures = [v for v in (to_int_dollars(m) for m in DOLLAR_RE.findall(answer)) if v is not None]

    if tampered:
        lines.append(
            f"TAMPER WARNING: {len(tampered)} VALID log row(s) failed the hash "
            f"check and were ignored: {tampered}"
        )

    offending = sorted({fig for fig in figures
                        if not any((tok, fig) in pairs for tok in tokens_in_answer)})

    if offending:
        lines.append(
            "FABRICATION DETECTED — these dollar figures have no logged "
            f"run-token provenance for session '{session_id}':"
        )
        lines.extend(f"  ${f:,}" for f in offending)
        lines.append(
            f"tokens quoted in answer: {sorted(tokens_in_answer) or 'NONE'}"
        )
        return 1, lines

    if not figures:
        lines.append("OK: no dollar figures in answer — nothing to verify.")
        return 0, lines

    lines.append(
        f"OK: all {len(figures)} dollar figure(s) trace to logged run "
        f"token(s) for session '{session_id}'."
    )
    return 0, lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Provenance gate for SwiftClose answers.")
    ap.add_argument("--answer-file", help="File with the analyst's final answer; omit to read stdin.")
    ap.add_argument("--log", default=LOG_FILE, help="Path to comp_run_log.csv.")
    ap.add_argument("--session-id", help="Session id to check against (default: $SWIFTCLOSE_SESSION_ID or 'local').")
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])

    session_id = args.session_id or _current_session_id()

    if args.answer_file:
        try:
            with open(args.answer_file, "r", encoding="utf-8") as fh:
                answer = fh.read()
        except OSError as exc:
            print(f"error: cannot read --answer-file: {exc}", file=sys.stderr)
            return 2
    else:
        answer = sys.stdin.read()

    code, lines = verify(answer, args.log, session_id)
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
