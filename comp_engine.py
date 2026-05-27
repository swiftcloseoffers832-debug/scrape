"""
SwiftClose Offers - Deterministic Comp Engine

This is the ONLY path to a comp number. The analyst (LLM) must never
calculate or estimate an offer. It loads data, calls this engine, and
reads back the result. If the engine does not return a number, the
analyst returns DATA NOT FOUND.

The math here is fixed. It does not self-modify. The only things that
change over time are the rule parameters at the top of this file, and
they only change when a human edits them deliberately.

Usage (CLI):
    python comp_engine.py \\
        --address "1234 Main St" \\
        --zip 77096 \\
        --beds 3 \\
        --baths 2 \\
        --sqft 1800 \\
        --repair-level moderate \\
        --data-dir .

Usage (programmatic):
    from comp_engine import run_comp
    result = run_comp(subject={...}, data_dir=".")
    print(result["report"])
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
import statistics
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Tunable rule parameters. Edit these deliberately; do not auto-modify.
# ---------------------------------------------------------------------------

REPAIR_PPSF = {
    "light": 20.0,
    "moderate": 35.0,
    "heavy": 55.0,
}

# Match tolerances vs subject
BED_TOLERANCE = 1          # +/- this many beds
BATH_TOLERANCE = 1         # +/- this many baths
SQFT_TOLERANCE_PCT = 0.20  # +/- 20% of subject sqft

# Recency
RECENCY_DAYS = 365         # 12 months; older comps are flagged, not dropped

# Validation gates
MIN_COMPS_AFTER_TRIM = 5
MAX_SPREAD_AFTER_TRIM = 0.30  # 30%

# Math constants
ARV_DISCOUNT = 0.70
FIXED_FEE = 15_000
OPENING_OFFER_BUFFER_LOW = 25_000   # Max Offer minus this = low end of opening
OPENING_OFFER_BUFFER_HIGH = 15_000  # Max Offer minus this = high end of opening
DOLLAR_ROUND = 100

# File names
LOG_FILE = "comp_run_log.csv"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Subject:
    address: str
    zip: str
    beds: float
    baths: float
    sqft: float
    repair_level: str

    def validate(self) -> str | None:
        if not self.zip or not str(self.zip).strip():
            return "missing zip"
        if not self.sqft or self.sqft <= 0:
            return "missing or invalid sqft"
        if self.repair_level not in REPAIR_PPSF:
            return f"repair_level must be one of {list(REPAIR_PPSF)}"
        return None


@dataclass
class Comp:
    address: str
    address_key: str
    zip: str
    mls_status: str
    sale_price: float | None
    price_per_sqft: float | None
    sqft: float | None
    beds: float | None
    baths: float | None
    year_built: int | None
    date_sold: datetime | None
    subdivision: str
    property_type: str
    source_file: str
    raw: dict[str, str] = field(default_factory=dict)


@dataclass
class LoadStats:
    files_read: list[str] = field(default_factory=list)
    rows_read: int = 0
    rows_dropped_no_zip: int = 0
    rows_after_dedupe: int = 0


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

ADDRESS_SUFFIX_RE = re.compile(
    r"\s+(houston|tx|texas|usa|us)\b[\s,]*",
    flags=re.IGNORECASE,
)
ZIP_RE = re.compile(r"\b\d{5}(?:-\d{4})?\b")
PUNCT_RE = re.compile(r"[^\w\s]")
WS_RE = re.compile(r"\s+")

REFI_FLAGS = {"refi", "refinance", "loan", "last sale price refi"}


def normalize_address(raw: str) -> str:
    if not raw:
        return ""
    s = raw.lower()
    s = ZIP_RE.sub(" ", s)
    s = ADDRESS_SUFFIX_RE.sub(" ", s)
    s = PUNCT_RE.sub(" ", s)
    s = WS_RE.sub(" ", s).strip()
    return s


def normalize_zip(raw: str) -> str:
    if raw is None:
        return ""
    s = str(raw).strip()
    m = re.search(r"\d{5}", s)
    return m.group(0) if m else ""


def parse_float(raw: Any) -> float | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    s = s.replace("$", "").replace(",", "").replace("%", "")
    try:
        return float(s)
    except ValueError:
        return None


def parse_int(raw: Any) -> int | None:
    v = parse_float(raw)
    return int(v) if v is not None else None


DATE_FORMATS = [
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%m-%d-%Y",
    "%m/%d/%y",
    "%b %d %Y",
    "%B %d %Y",
    "%d-%b-%Y",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
]


def parse_date(raw: Any) -> datetime | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    # Last try: take leading YYYY-MM-DD
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


# Column header aliases. Headers vary by export source.
COLUMN_ALIASES = {
    "address": ["address", "property address", "street address", "addr", "site address"],
    "zip": ["zip", "zip code", "postal code", "zipcode", "zip_code"],
    "mls_status": ["mls_status", "status", "mls status", "listing status"],
    "sale_price": ["sale_price", "sold price", "sale price", "close price", "closed price", "sold_price"],
    "price_per_sqft": ["price_per_sqft", "$/sqft", "price/sqft", "ppsf", "$ per sqft", "price per sqft"],
    "sqft": ["sqft", "sq ft", "square feet", "living area", "gla", "building sqft"],
    "beds": ["beds", "bedrooms", "br", "bed"],
    "baths": ["baths", "bathrooms", "ba", "bath", "total baths"],
    "year_built": ["year_built", "year built", "yr built", "yearbuilt"],
    "date_sold": ["date_sold", "sold date", "close date", "closed date", "sale date", "date sold"],
    "subdivision": ["subdivision", "subdiv", "neighborhood"],
    "property_type": ["property_type", "type", "property type", "prop type"],
    "transaction_type": ["transaction_type", "transaction type", "sale_type", "sale type"],
}


def build_header_map(headers: Iterable[str]) -> dict[str, str]:
    """Return {canonical_field: actual_header} for whatever this file has."""
    lowered = {h.lower().strip(): h for h in headers}
    result: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lowered:
                result[canonical] = lowered[alias]
                break
    return result


# ---------------------------------------------------------------------------
# Load + normalize
# ---------------------------------------------------------------------------

def discover_comp_files(data_dir: str) -> list[str]:
    """Every CSV in the data dir, plus any CSV anywhere with 'comp' or
    'comparable' in its name (covers Google Drive-synced files dropped
    into subfolders)."""
    found: set[str] = set()
    for p in glob.glob(os.path.join(data_dir, "*.csv")):
        found.add(os.path.abspath(p))
    for p in glob.glob(os.path.join(data_dir, "**", "*.csv"), recursive=True):
        name = os.path.basename(p).lower()
        if "comp" in name or "comparable" in name:
            found.add(os.path.abspath(p))
    # Don't ingest our own log file
    log_abs = os.path.abspath(os.path.join(data_dir, LOG_FILE))
    found.discard(log_abs)
    return sorted(found)


def load_comps(data_dir: str) -> tuple[list[Comp], LoadStats]:
    stats = LoadStats()
    files = discover_comp_files(data_dir)
    stats.files_read = files
    all_rows: list[Comp] = []

    for path in files:
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as fh:
                reader = csv.DictReader(fh)
                if not reader.fieldnames:
                    continue
                hmap = build_header_map(reader.fieldnames)
                if "address" not in hmap:
                    # Not a comp-shaped file
                    continue
                for raw in reader:
                    stats.rows_read += 1
                    zip_val = normalize_zip(raw.get(hmap.get("zip", ""), ""))
                    if not zip_val:
                        stats.rows_dropped_no_zip += 1
                        continue
                    address = (raw.get(hmap["address"], "") or "").strip()
                    comp = Comp(
                        address=address,
                        address_key=normalize_address(address),
                        zip=zip_val,
                        mls_status=(raw.get(hmap.get("mls_status", ""), "") or "").strip(),
                        sale_price=parse_float(raw.get(hmap.get("sale_price", ""), "")),
                        price_per_sqft=parse_float(raw.get(hmap.get("price_per_sqft", ""), "")),
                        sqft=parse_float(raw.get(hmap.get("sqft", ""), "")),
                        beds=parse_float(raw.get(hmap.get("beds", ""), "")),
                        baths=parse_float(raw.get(hmap.get("baths", ""), "")),
                        year_built=parse_int(raw.get(hmap.get("year_built", ""), "")),
                        date_sold=parse_date(raw.get(hmap.get("date_sold", ""), "")),
                        subdivision=(raw.get(hmap.get("subdivision", ""), "") or "").strip(),
                        property_type=(raw.get(hmap.get("property_type", ""), "") or "").strip(),
                        source_file=os.path.basename(path),
                        raw=raw,
                    )
                    all_rows.append(comp)
        except (OSError, csv.Error):
            continue

    deduped = dedupe(all_rows)
    stats.rows_after_dedupe = len(deduped)
    return deduped, stats


def dedupe(rows: list[Comp]) -> list[Comp]:
    """Dedupe on (address_key + date_sold). Fixes the documented
    multi-row-per-sale bug (e.g. 6916 Berger appearing 9 times for
    ~6 real sales)."""
    seen: dict[tuple[str, str], Comp] = {}
    for r in rows:
        if not r.address_key:
            continue
        date_key = r.date_sold.strftime("%Y-%m-%d") if r.date_sold else ""
        key = (r.address_key, date_key)
        existing = seen.get(key)
        if existing is None:
            seen[key] = r
            continue
        # Prefer the row with more information populated
        if _row_score(r) > _row_score(existing):
            seen[key] = r
    return list(seen.values())


def _row_score(c: Comp) -> int:
    score = 0
    for v in (c.sale_price, c.price_per_sqft, c.sqft, c.beds, c.baths, c.date_sold):
        if v is not None:
            score += 1
    if c.mls_status:
        score += 1
    return score


# ---------------------------------------------------------------------------
# Filter to valid sold comps
# ---------------------------------------------------------------------------

def is_sold(comp: Comp) -> bool:
    status = (comp.mls_status or "").strip().lower()
    # A comp-export closed sale may have no status but a sale_price + date_sold.
    if status == "sold":
        return True
    if status in {"active", "pending", "canceled", "cancelled", "off market", "off-market", "withdrawn", "expired"}:
        return False
    if not status and comp.sale_price and comp.date_sold:
        return True
    return False


def is_refi(comp: Comp) -> bool:
    """Reject rows flagged as loans/refis rather than arms-length sales."""
    tx = (comp.raw.get("transaction_type") or comp.raw.get("Transaction Type") or "").strip().lower()
    if any(flag in tx for flag in REFI_FLAGS):
        return True
    for k, v in comp.raw.items():
        if v is None:
            continue
        if "refi" in str(v).lower() or "last sale price refi" in str(v).lower():
            return True
    return False


@dataclass
class FilterResult:
    survivors: list[Comp]
    drop_reasons: dict[str, int]
    flagged_old: list[Comp]  # >12 months but otherwise valid


def filter_comps(comps: list[Comp], subject: Subject, now: datetime) -> FilterResult:
    drops: dict[str, int] = {}
    survivors: list[Comp] = []
    flagged_old: list[Comp] = []
    cutoff = now - timedelta(days=RECENCY_DAYS)

    sqft_lo = subject.sqft * (1 - SQFT_TOLERANCE_PCT)
    sqft_hi = subject.sqft * (1 + SQFT_TOLERANCE_PCT)

    for c in comps:
        if not is_sold(c):
            drops["not_sold"] = drops.get("not_sold", 0) + 1
            continue
        if is_refi(c):
            drops["refi_or_loan"] = drops.get("refi_or_loan", 0) + 1
            continue
        if c.zip != normalize_zip(subject.zip):
            drops["wrong_zip"] = drops.get("wrong_zip", 0) + 1
            continue
        if c.beds is None or abs(c.beds - subject.beds) > BED_TOLERANCE:
            drops["beds_mismatch"] = drops.get("beds_mismatch", 0) + 1
            continue
        if c.baths is None or abs(c.baths - subject.baths) > BATH_TOLERANCE:
            drops["baths_mismatch"] = drops.get("baths_mismatch", 0) + 1
            continue
        if c.sqft is None or not (sqft_lo <= c.sqft <= sqft_hi):
            drops["sqft_mismatch"] = drops.get("sqft_mismatch", 0) + 1
            continue
        # Need a usable $/sqft. Derive from sale_price/sqft if missing.
        if c.price_per_sqft is None and c.sale_price and c.sqft:
            c.price_per_sqft = c.sale_price / c.sqft
        if c.price_per_sqft is None or c.price_per_sqft <= 0:
            drops["no_ppsf"] = drops.get("no_ppsf", 0) + 1
            continue
        if c.date_sold is None:
            drops["no_sale_date"] = drops.get("no_sale_date", 0) + 1
            continue
        if c.date_sold < cutoff:
            flagged_old.append(c)
            # Flag, do not hard-drop -- but exclude from the math set so
            # we are not silently averaging stale prices in. Reviewer
            # can relax this by widening RECENCY_DAYS if needed.
            drops["older_than_12mo"] = drops.get("older_than_12mo", 0) + 1
            continue
        survivors.append(c)

    return FilterResult(survivors=survivors, drop_reasons=drops, flagged_old=flagged_old)


# ---------------------------------------------------------------------------
# IQR trim
# ---------------------------------------------------------------------------

@dataclass
class TrimResult:
    kept: list[Comp]
    trimmed: list[tuple[Comp, str]]  # (comp, reason)
    q1: float | None
    q3: float | None
    iqr: float | None
    spread_before: float | None
    spread_after: float | None


def _spread(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    lo, hi = min(values), max(values)
    if lo <= 0:
        return None
    return (hi - lo) / lo


def trim_outliers(comps: list[Comp]) -> TrimResult:
    values = sorted(c.price_per_sqft for c in comps if c.price_per_sqft is not None)
    spread_before = _spread(values)
    if len(values) < 4:
        # Not enough to compute IQR meaningfully; keep all.
        return TrimResult(
            kept=list(comps),
            trimmed=[],
            q1=None, q3=None, iqr=None,
            spread_before=spread_before,
            spread_after=spread_before,
        )
    q1 = statistics.quantiles(values, n=4)[0]
    q3 = statistics.quantiles(values, n=4)[2]
    iqr = q3 - q1
    lo_fence = q1 - 1.5 * iqr
    hi_fence = q3 + 1.5 * iqr

    kept: list[Comp] = []
    trimmed: list[tuple[Comp, str]] = []
    for c in comps:
        v = c.price_per_sqft
        if v is None:
            trimmed.append((c, "no $/sqft"))
        elif v < lo_fence:
            trimmed.append((c, f"${v:.2f}/sqft below IQR fence ${lo_fence:.2f}"))
        elif v > hi_fence:
            trimmed.append((c, f"${v:.2f}/sqft above IQR fence ${hi_fence:.2f}"))
        else:
            kept.append(c)

    kept_values = [c.price_per_sqft for c in kept if c.price_per_sqft is not None]
    return TrimResult(
        kept=kept,
        trimmed=trimmed,
        q1=q1, q3=q3, iqr=iqr,
        spread_before=spread_before,
        spread_after=_spread(sorted(kept_values)),
    )


# ---------------------------------------------------------------------------
# Math
# ---------------------------------------------------------------------------

def round_to(value: float, step: int) -> int:
    return int(round(value / step) * step)


@dataclass
class OfferMath:
    median_ppsf: float
    arv: int
    repairs: int
    max_offer: int
    opening_low: int
    opening_high: int
    walk_away_above: int


def compute_offer(kept: list[Comp], subject: Subject) -> OfferMath:
    values = [c.price_per_sqft for c in kept if c.price_per_sqft is not None]
    median_ppsf = statistics.median(values)
    arv_raw = median_ppsf * subject.sqft
    repair_ppsf = REPAIR_PPSF[subject.repair_level]
    repairs_raw = repair_ppsf * subject.sqft
    max_offer_raw = arv_raw * ARV_DISCOUNT - repairs_raw - FIXED_FEE
    opening_low_raw = max_offer_raw - OPENING_OFFER_BUFFER_LOW
    opening_high_raw = max_offer_raw - OPENING_OFFER_BUFFER_HIGH

    return OfferMath(
        median_ppsf=median_ppsf,
        arv=round_to(arv_raw, DOLLAR_ROUND),
        repairs=round_to(repairs_raw, DOLLAR_ROUND),
        max_offer=round_to(max_offer_raw, DOLLAR_ROUND),
        opening_low=round_to(opening_low_raw, DOLLAR_ROUND),
        opening_high=round_to(opening_high_raw, DOLLAR_ROUND),
        walk_away_above=round_to(max_offer_raw, DOLLAR_ROUND),
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

VALID = "VALID"
THIN = "THIN"
UNRELIABLE = "UNRELIABLE"
DATA_NOT_FOUND = "DATA NOT FOUND"


def run_comp(
    subject: dict | Subject,
    data_dir: str = ".",
    now: datetime | None = None,
) -> dict:
    if isinstance(subject, dict):
        subj = Subject(
            address=str(subject.get("address", "")).strip(),
            zip=normalize_zip(subject.get("zip", "")),
            beds=float(subject.get("beds") or 0),
            baths=float(subject.get("baths") or 0),
            sqft=float(subject.get("sqft") or 0),
            repair_level=str(subject.get("repair_level", "")).strip().lower(),
        )
    else:
        subj = subject

    now = now or datetime.now(timezone.utc).replace(tzinfo=None)

    err = subj.validate()
    if err:
        return _no_number_result(
            subj, status=DATA_NOT_FOUND, reason=f"subject invalid: {err}",
            data_dir=data_dir, now=now,
        )

    comps, load_stats = load_comps(data_dir)
    if not comps:
        return _no_number_result(
            subj, status=DATA_NOT_FOUND, reason="no comp rows loaded from data dir",
            data_dir=data_dir, now=now, load_stats=load_stats,
        )

    filt = filter_comps(comps, subj, now)
    if not filt.survivors:
        return _no_number_result(
            subj, status=DATA_NOT_FOUND,
            reason=f"zero comps matched filters; drops={filt.drop_reasons}",
            data_dir=data_dir, now=now, load_stats=load_stats,
            filter_result=filt,
        )

    trim = trim_outliers(filt.survivors)

    if len(trim.kept) < MIN_COMPS_AFTER_TRIM:
        return _no_number_result(
            subj, status=THIN,
            reason=f"only {len(trim.kept)} comps after trim (need {MIN_COMPS_AFTER_TRIM})",
            data_dir=data_dir, now=now, load_stats=load_stats,
            filter_result=filt, trim_result=trim,
        )

    if trim.spread_after is not None and trim.spread_after > MAX_SPREAD_AFTER_TRIM:
        return _no_number_result(
            subj, status=UNRELIABLE,
            reason=f"spread {trim.spread_after*100:.1f}% > {MAX_SPREAD_AFTER_TRIM*100:.0f}% after trim",
            data_dir=data_dir, now=now, load_stats=load_stats,
            filter_result=filt, trim_result=trim,
        )

    math = compute_offer(trim.kept, subj)
    result = _ok_result(
        subj, math, filt, trim, load_stats=load_stats, data_dir=data_dir, now=now,
    )
    append_log(result, data_dir)
    return result


def _no_number_result(
    subj: Subject,
    status: str,
    reason: str,
    data_dir: str,
    now: datetime,
    load_stats: LoadStats | None = None,
    filter_result: FilterResult | None = None,
    trim_result: TrimResult | None = None,
) -> dict:
    comps_found = len(filter_result.survivors) if filter_result else 0
    comps_used = len(trim_result.kept) if trim_result else 0
    spread_before = trim_result.spread_before if trim_result else None
    spread_after = trim_result.spread_after if trim_result else None

    report = _format_no_number_report(
        status=status,
        reason=reason,
        comps_found=comps_found,
        comps_used=comps_used,
        filter_result=filter_result,
    )

    result = {
        "status": status,
        "reason": reason,
        "subject": asdict(subj),
        "comps_found": comps_found,
        "comps_used": comps_used,
        "spread_before": spread_before,
        "spread_after": spread_after,
        "arv": None,
        "max_offer": None,
        "opening_range_low": None,
        "opening_range_high": None,
        "walk_away_above": None,
        "report": report,
        "timestamp": now.isoformat(timespec="seconds"),
    }
    append_log(result, data_dir)
    return result


def _ok_result(
    subj: Subject,
    math: OfferMath,
    filt: FilterResult,
    trim: TrimResult,
    load_stats: LoadStats,
    data_dir: str,
    now: datetime,
) -> dict:
    included = [(c.address, c.price_per_sqft) for c in trim.kept]
    trimmed = [(c.address, c.price_per_sqft, reason) for c, reason in trim.trimmed]

    report = _format_valid_report(
        subj=subj,
        math=math,
        comps_used=len(trim.kept),
        included=included,
        trimmed=trimmed,
        spread_before=trim.spread_before,
        spread_after=trim.spread_after,
        flagged_old=filt.flagged_old,
    )

    return {
        "status": VALID,
        "reason": "",
        "subject": asdict(subj),
        "comps_found": len(filt.survivors),
        "comps_used": len(trim.kept),
        "spread_before": trim.spread_before,
        "spread_after": trim.spread_after,
        "median_ppsf": math.median_ppsf,
        "arv": math.arv,
        "repairs": math.repairs,
        "max_offer": math.max_offer,
        "opening_range_low": math.opening_low,
        "opening_range_high": math.opening_high,
        "walk_away_above": math.walk_away_above,
        "included_comps": included,
        "trimmed_comps": trimmed,
        "flagged_old_count": len(filt.flagged_old),
        "report": report,
        "timestamp": now.isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------------------
# Report formatting (numbers first, numerical only at the top)
# ---------------------------------------------------------------------------

def _fmt_dollars(n: int | None) -> str:
    if n is None:
        return "N/A"
    return f"${n:,}"


def _fmt_pct(p: float | None) -> str:
    if p is None:
        return "N/A"
    return f"{p*100:.1f}%"


def _format_valid_report(
    subj: Subject,
    math: OfferMath,
    comps_used: int,
    included: list[tuple[str, float | None]],
    trimmed: list[tuple[str, float | None, str]],
    spread_before: float | None,
    spread_after: float | None,
    flagged_old: list[Comp],
) -> str:
    lines = []
    lines.append(f"COMP SET STATUS: {VALID}")
    lines.append(f"COMPS USED: {comps_used}")
    lines.append(f"ARV: {_fmt_dollars(math.arv)}")
    lines.append(f"MAX OFFER: {_fmt_dollars(math.max_offer)}")
    lines.append(
        f"OPENING OFFER RANGE: {_fmt_dollars(math.opening_low)} - "
        f"{_fmt_dollars(math.opening_high)}"
    )
    lines.append(f"WALK AWAY ABOVE: {_fmt_dollars(math.walk_away_above)}")
    lines.append("")
    lines.append("COMP DETAIL")
    lines.append(f"  Subject: {subj.address}  zip={subj.zip}  "
                 f"{subj.beds}bd/{subj.baths}ba  {int(subj.sqft)} sqft  "
                 f"repair={subj.repair_level}")
    lines.append(f"  Median $/sqft used: ${math.median_ppsf:.2f}")
    lines.append(f"  Repair $/sqft: ${REPAIR_PPSF[subj.repair_level]:.2f}  "
                 f"-> repairs {_fmt_dollars(math.repairs)}")
    lines.append(f"  Spread before trim: {_fmt_pct(spread_before)}")
    lines.append(f"  Spread after trim:  {_fmt_pct(spread_after)}")
    lines.append(f"  Flagged old-but-otherwise-valid comps (excluded from math): "
                 f"{len(flagged_old)}")
    lines.append("")
    lines.append("  Included comps:")
    for addr, ppsf in included:
        ppsf_s = f"${ppsf:.2f}/sqft" if ppsf is not None else "N/A"
        lines.append(f"    - {addr}  {ppsf_s}")
    if trimmed:
        lines.append("")
        lines.append("  Trimmed as outliers:")
        for addr, ppsf, reason in trimmed:
            ppsf_s = f"${ppsf:.2f}/sqft" if ppsf is not None else "N/A"
            lines.append(f"    - {addr}  {ppsf_s}  ({reason})")
    return "\n".join(lines)


def _format_no_number_report(
    status: str,
    reason: str,
    comps_found: int,
    comps_used: int,
    filter_result: FilterResult | None,
) -> str:
    lines = []
    lines.append(f"COMP SET STATUS: {status}")
    lines.append(f"COMPS USED: {comps_used}")
    lines.append("ARV: N/A")
    lines.append("MAX OFFER: N/A")
    lines.append("OPENING OFFER RANGE: N/A")
    lines.append("WALK AWAY ABOVE: N/A")
    lines.append("")
    lines.append(f"REASON: {reason}")
    if filter_result is not None:
        lines.append("")
        lines.append("FILTER DROPS:")
        for k, v in sorted(filter_result.drop_reasons.items()):
            lines.append(f"  {k}: {v}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

LOG_HEADERS = [
    "timestamp",
    "subject_address",
    "subject_zip",
    "subject_beds",
    "subject_baths",
    "subject_sqft",
    "subject_repair_level",
    "comps_found",
    "comps_used",
    "spread_before",
    "spread_after",
    "status",
    "reason",
    "median_ppsf",
    "arv",
    "max_offer",
    "opening_range_low",
    "opening_range_high",
    "walk_away_above",
]


def append_log(result: dict, data_dir: str) -> None:
    path = os.path.join(data_dir, LOG_FILE)
    new_file = not os.path.exists(path)
    subj = result.get("subject", {})
    row = {
        "timestamp": result.get("timestamp", ""),
        "subject_address": subj.get("address", ""),
        "subject_zip": subj.get("zip", ""),
        "subject_beds": subj.get("beds", ""),
        "subject_baths": subj.get("baths", ""),
        "subject_sqft": subj.get("sqft", ""),
        "subject_repair_level": subj.get("repair_level", ""),
        "comps_found": result.get("comps_found", ""),
        "comps_used": result.get("comps_used", ""),
        "spread_before": _fmt_pct(result.get("spread_before")),
        "spread_after": _fmt_pct(result.get("spread_after")),
        "status": result.get("status", ""),
        "reason": result.get("reason", ""),
        "median_ppsf": result.get("median_ppsf", ""),
        "arv": result.get("arv", ""),
        "max_offer": result.get("max_offer", ""),
        "opening_range_low": result.get("opening_range_low", ""),
        "opening_range_high": result.get("opening_range_high", ""),
        "walk_away_above": result.get("walk_away_above", ""),
    }
    try:
        with open(path, "a", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=LOG_HEADERS)
            if new_file:
                writer.writeheader()
            writer.writerow(row)
    except OSError:
        # Logging must never block returning a result.
        pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="SwiftClose deterministic comp engine."
    )
    p.add_argument("--address", required=True)
    p.add_argument("--zip", required=True)
    p.add_argument("--beds", type=float, required=True)
    p.add_argument("--baths", type=float, required=True)
    p.add_argument("--sqft", type=float, required=True)
    p.add_argument(
        "--repair-level", required=True,
        choices=sorted(REPAIR_PPSF.keys()),
        help="light / moderate / heavy",
    )
    p.add_argument("--data-dir", default=".")
    p.add_argument("--json", action="store_true",
                   help="Emit the full result as JSON in addition to the report.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    result = run_comp(
        subject={
            "address": args.address,
            "zip": args.zip,
            "beds": args.beds,
            "baths": args.baths,
            "sqft": args.sqft,
            "repair_level": args.repair_level,
        },
        data_dir=args.data_dir,
    )
    print(result["report"])
    if args.json:
        print()
        print(json.dumps(
            {k: v for k, v in result.items() if k != "report"},
            indent=2, default=str,
        ))
    # Exit code reflects whether a number was produced.
    return 0 if result["status"] == VALID else 2


if __name__ == "__main__":
    sys.exit(main())
