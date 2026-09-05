"""
Split-Adjustment Guard
======================

Finds — and marks for repair — price history that is stuck on a stale
split-adjustment scale.

Why this exists
---------------
``downloader.smart_update()`` fetches only the days it is missing. Yahoo, by
contrast, re-adjusts a ticker's *entire* history the moment that ticker
splits: after a 2-for-1, every historical bar it serves comes back halved.
Rows already on disk are never refetched, so the CSV ends up carrying two
price scales stitched together at the split date — a synthetic one-day -50%
cliff that the analysers read as a genuine crash. (Amphenol's 2-for-1 put
APH at #1 in the dip report with a -51% "30-day return" and a -6.6 z-score.)

Detection is deliberately two-stage, because neither stage works alone:

* A **seam scan** over the stored closes costs nothing and never misses a
  stale split — one always leaves a one-day jump near the split ratio. But it
  is hopeless at *deciding*: scanning the real 500-ticker CSV turns up 281
  split-shaped seams, and nearly all of them are ordinary crashes (2008,
  March 2020, Netflix's -35% earnings day). Roughly a 95% false-positive rate.
* **Refetching the seam** settles it outright, but is far too many requests to
  run against every ticker on every update.

So the scan proposes and a refetch disposes. For each candidate we pull the
two bars that straddle the seam and compare the fresh one-day ratio with the
stored one. Both come from the same source on the same adjustment basis, so a
genuine crash reproduces exactly, while a stale scale shows up as the split
ratio itself. Verified-clean seams are cached, so a stock's crash is checked
once and never again, keeping steady-state traffic near zero.

An earlier version of this matched seams against Yahoo's split calendar
instead. It does not work, and the reason is worth recording: the seam does
*not* sit on the split date. It sits at the boundary of the last incremental
fetch, which is wherever the previous update happened to stop — KLAC's 10-for-1
split fell on 2026-06-12, but its seam is dated 2026-05-05, five weeks earlier.
Matching on dates missed every real case, and inferring a split ratio from the
jump would still confuse a -33% crash with a 3-for-2 split.

Repair itself lives in ``downloader.repair_tickers()``, which owns the
download helpers. It must refetch from ``START_DATE``: a partial refetch would
simply move the seam to the start of the refetched window. Because repair
rewrites a ticker's whole history, one confirmed seam per ticker is enough —
no need to prove every seam individually.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from config import (
    CSV_PATH,
    SPLIT_CLEAN_CACHE_DAYS,
    SPLIT_SCAN_LOOKBACK_ROWS,
    SPLIT_SEAM_BAND,
    SPLIT_VERIFY_SLEEP,
    SPLIT_VERIFY_TOLERANCE,
    SPLIT_VERIFY_WINDOW_DAYS,
)

log = logging.getLogger("split_guard")

# Ratios worth treating as split-shaped, forward and reverse. Anything below
# 3-for-2 is not a split any exchange actually runs, and would drown the scan
# in ordinary volatility.
COMMON_SPLIT_RATIOS = (
    1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 10.0, 15.0, 20.0, 25.0, 30.0,
)


def _candidate_ratios() -> np.ndarray:
    """Every common split ratio plus its inverse, sorted."""
    both = [r for ratio in COMMON_SPLIT_RATIOS for r in (ratio, 1.0 / ratio)]
    return np.array(sorted(both))


# ─────────────────────────────────────────────
# STATE FILES
# ─────────────────────────────────────────────
# Kept beside the CSV so they land on the Railway volume with it, rather than
# inside the container image where every deploy would wipe them.

def _state_path(csv_path: str, suffix: str) -> Path:
    p = Path(csv_path)
    return p.with_name(f"{p.stem}{suffix}")


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as e:
        log.warning(f"Could not read {path.name}: {e} — treating as empty")
        return default


def _write_json(path: Path, payload) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
    except Exception as e:
        log.warning(f"Could not write {path.name}: {e}")


# ── Quarantine ───────────────────────────────
# Tickers known to be on a stale scale that we could not repair (usually a
# failed download). The analysers drop these, so a corrupted series cannot
# reach a report even when the repair pass could not finish its job.

def load_quarantine(csv_path: str = CSV_PATH) -> set:
    """Tickers whose stored history is known-bad and still unrepaired."""
    data = _read_json(_state_path(csv_path, ".quarantine.json"), {})
    return set(data.get("tickers", []))


def save_quarantine(tickers, csv_path: str = CSV_PATH, note: str = "") -> None:
    _write_json(
        _state_path(csv_path, ".quarantine.json"),
        {
            "updated": datetime.today().strftime("%Y-%m-%d %H:%M:%S"),
            "note": note or "Stale split adjustment; repair did not complete.",
            "tickers": sorted(set(tickers)),
        },
    )


# ── Verification cache ───────────────────────

def _load_cache(csv_path: str) -> dict:
    return _read_json(_state_path(csv_path, ".splitcache.json"), {})


def _save_cache(cache: dict, csv_path: str) -> None:
    _write_json(_state_path(csv_path, ".splitcache.json"), cache)


def _cache_is_fresh(entry: dict) -> bool:
    """A cached 'clean' verdict expires, so one bad API reply is not forever."""
    try:
        checked = datetime.strptime(entry["checked"], "%Y-%m-%d")
    except (KeyError, TypeError, ValueError):
        return False
    return datetime.today() - checked <= timedelta(days=SPLIT_CLEAN_CACHE_DAYS)


# ─────────────────────────────────────────────
# STAGE 1 — SEAM SCAN (free, no network)
# ─────────────────────────────────────────────

def find_seam_candidates(
    df: pd.DataFrame,
    lookback_rows: int = SPLIT_SCAN_LOOKBACK_ROWS,
    band: float = SPLIT_SEAM_BAND,
) -> list:
    """
    One-day close-to-close jumps that are shaped like a split.

    Only the most recent ``lookback_rows`` bars per ticker are scanned: that
    window is what the reports actually read (the deepest lookback is the
    stable-growth 3-year window), and older seams cost requests to verify
    without changing a single published number. Pass 0 to scan all history.

    Returns a list of dicts: ticker, date, prev_date, ratio, nearest.
    """
    if df is None or df.empty:
        return []

    work = df[["ticker", "date", "close"]].copy()
    work["close"] = pd.to_numeric(work["close"], errors="coerce")
    work = work.dropna(subset=["close"])
    work = work[work["close"] > 0]
    if work.empty:
        return []

    work["date"] = work["date"].astype(str)
    work = work.sort_values(["ticker", "date"])

    if lookback_rows and lookback_rows > 0:
        # +1 so the oldest scanned bar still has a predecessor to compare to.
        work = work.groupby("ticker", sort=False).tail(lookback_rows + 1)

    grouped = work.groupby("ticker", sort=False)
    work["prev"] = grouped["close"].shift(1)
    work["prev_date"] = grouped["date"].shift(1)
    work = work.dropna(subset=["prev", "prev_date"])
    if work.empty:
        return []

    ratios = (work["close"] / work["prev"]).to_numpy(dtype=float)

    # Nearest common split ratio for each observed jump, by relative distance.
    cands = _candidate_ratios()
    idx = np.clip(np.searchsorted(cands, ratios), 1, len(cands) - 1)
    left, right = cands[idx - 1], cands[idx]
    take_right = (np.abs(ratios - right) / right) <= (np.abs(ratios - left) / left)
    nearest = np.where(take_right, right, left)
    hit = (np.abs(ratios - nearest) / nearest) <= band

    work = work.assign(ratio=ratios, nearest=nearest)[hit]
    return [
        {
            "ticker": row.ticker,
            "date": row.date,
            "prev_date": row.prev_date,
            "ratio": round(float(row.ratio), 6),
            "nearest": float(row.nearest),
        }
        for row in work.itertuples(index=False)
    ]


# ─────────────────────────────────────────────
# STAGE 2 — REFETCH THE SEAM AND COMPARE
# ─────────────────────────────────────────────

def _fetch_closes(ticker: str, start: str, end: str) -> dict:
    """
    {'YYYY-MM-DD': close} for a short window, on today's adjustment basis.

    Raises on a failed request, so the caller can tell an empty window from a
    request that never landed.
    """
    import yfinance as yf  # imported lazily: the analysers import this module

    raw = yf.download(
        ticker, start=start, end=end,
        auto_adjust=True, progress=False, threads=False,
    )
    if raw is None or raw.empty or "Close" not in raw:
        return {}

    closes = raw["Close"]
    if isinstance(closes, pd.DataFrame):
        # Recent yfinance returns MultiIndex columns even for one ticker.
        closes = closes.iloc[:, 0]

    return {
        pd.Timestamp(stamp).strftime("%Y-%m-%d"): float(value)
        for stamp, value in closes.items()
        if pd.notna(value) and float(value) > 0
    }


def _verify_seam(seam: dict, fresh: dict) -> tuple:
    """
    Compare the stored one-day jump with the same jump fetched fresh.

    Returns (verdict, scale) where verdict is 'stale', 'clean' or 'unknown'
    and scale is stored_ratio / fresh_ratio — the factor the stored history is
    off by, which lands on the split ratio when the history is stale.

    Both ratios come from the same source, so a genuine crash reproduces
    essentially exactly; anything else means the two stored bars were written
    on different adjustment bases.
    """
    before, after = fresh.get(seam["prev_date"]), fresh.get(seam["date"])
    if not before or not after:
        return "unknown", None

    fresh_ratio = after / before
    if fresh_ratio <= 0:
        return "unknown", None

    scale = seam["ratio"] / fresh_ratio
    if abs(scale - 1.0) <= SPLIT_VERIFY_TOLERANCE:
        return "clean", scale
    return "stale", scale


def confirm_split_seams(candidates: list, csv_path: str = CSV_PATH) -> dict:
    """
    Refetch each candidate seam and decide whether the stored history is stale.

    Returns {'confirmed': [seams + scale],
             'unverified': [tickers we could not settle],
             'checked': number of tickers actually queried}
    """
    if not candidates:
        return {"confirmed": [], "unverified": [], "checked": 0}

    cache = _load_cache(csv_path)
    by_ticker: dict = {}
    for seam in candidates:
        by_ticker.setdefault(seam["ticker"], []).append(seam)

    confirmed, unverified, checked = [], [], 0

    for ticker, seams in sorted(by_ticker.items()):
        pending = [
            s for s in seams
            if not _cache_is_fresh(cache.get(f"{ticker}@{s['date']}", {}))
        ]
        if not pending:
            continue

        settled = False
        for seam in pending:
            # Repair rewrites the whole ticker, so stop at the first seam that
            # proves the history is stale rather than pricing out every one.
            if settled:
                break

            window = (
                (pd.Timestamp(seam["prev_date"]) - timedelta(days=SPLIT_VERIFY_WINDOW_DAYS))
                .strftime("%Y-%m-%d"),
                (pd.Timestamp(seam["date"]) + timedelta(days=SPLIT_VERIFY_WINDOW_DAYS))
                .strftime("%Y-%m-%d"),
            )
            try:
                fresh = _fetch_closes(ticker, *window)
                checked += 1
            except Exception as e:
                log.warning(f"{ticker}: could not refetch {seam['date']} ({e})")
                unverified.append(ticker)
                break
            finally:
                time.sleep(SPLIT_VERIFY_SLEEP)  # gentle on Yahoo's rate limits

            verdict, scale = _verify_seam(seam, fresh)

            if verdict == "unknown":
                log.warning(f"{ticker}: no fresh bars for {seam['prev_date']} to "
                            f"{seam['date']}, cannot settle this seam")
                unverified.append(ticker)
                continue

            if verdict == "clean":
                # A real price move. Remember it, so the next run does not
                # spend a request asking the same question again.
                cache[f"{ticker}@{seam['date']}"] = {
                    "verdict": "clean",
                    "checked": datetime.today().strftime("%Y-%m-%d"),
                    "ratio": seam["ratio"],
                }
                continue

            log.warning(
                f"{ticker}: history is on a stale adjustment scale - the "
                f"{(seam['ratio'] - 1) * 100:+.1f}% jump stored for "
                f"{seam['date']} is off by {scale:.4g}x against a fresh fetch"
            )
            confirmed.append({**seam, "scale": round(float(scale), 6)})
            settled = True

    _save_cache(cache, csv_path)
    return {
        "confirmed": confirmed,
        "unverified": sorted(set(unverified) - {c["ticker"] for c in confirmed}),
        "checked": checked,
    }


def scan_for_stale_splits(
    df: pd.DataFrame,
    csv_path: str = CSV_PATH,
    lookback_rows: int = SPLIT_SCAN_LOOKBACK_ROWS,
) -> dict:
    """
    Run both stages over a price frame.

    Returns {'candidates': int, 'confirmed': [...], 'tickers': [...],
             'unverified': [...], 'checked': int}
    """
    candidates = find_seam_candidates(df, lookback_rows=lookback_rows)
    if not candidates:
        log.info("Split guard: no split-shaped seams in the scanned window")
        return {"candidates": 0, "confirmed": [], "tickers": [],
                "unverified": [], "checked": 0}

    log.info(
        f"Split guard: {len(candidates)} split-shaped seam(s) across "
        f"{len({c['ticker'] for c in candidates})} ticker(s) - refetching "
        f"them to see which are real"
    )
    result = confirm_split_seams(candidates, csv_path=csv_path)
    tickers = sorted({s["ticker"] for s in result["confirmed"]})

    if tickers:
        log.warning(f"Split guard: {len(tickers)} ticker(s) need repair: {tickers}")
    else:
        log.info(
            f"Split guard: no stale splits ({result['checked']} ticker(s) "
            f"queried, the rest cached or genuine price moves)"
        )

    return {
        "candidates": len(candidates),
        "confirmed": result["confirmed"],
        "tickers": tickers,
        "unverified": result["unverified"],
        "checked": result["checked"],
    }
