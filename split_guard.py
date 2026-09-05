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

Verification is the stage most exposed to throttling — it runs before any
repair, and on a cold cache it has the whole candidate list to get through —
so it is batched through the downloader's retrying batch path rather than
fetching a ticker at a time. A universe-wide sweep costs a handful of requests
instead of one per candidate, and inherits retry, backoff and the per-ticker
fallback. A batch that still cannot be settled leaves those tickers untouched
and reported, not quarantined: most candidates are genuine crashes, and
dropping them on a failed request would silently bury exactly the dips these
reports exist to surface. They are re-detected and retried on the next run.

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
    COMMON_SPLIT_RATIOS,
    CSV_PATH,
    SLEEP_BETWEEN_BATCHES_UPDATE,
    SPLIT_CLEAN_CACHE_DAYS,
    SPLIT_SCAN_LOOKBACK_ROWS,
    SPLIT_SEAM_BAND,
    SPLIT_VERIFY_BATCH_SIZE,
    SPLIT_VERIFY_SLEEP,
    SPLIT_VERIFY_TOLERANCE,
    SPLIT_VERIFY_WINDOW_DAYS,
)

log = logging.getLogger("split_guard")

# COMMON_SPLIT_RATIOS lives in config so the API can share it without pulling
# pandas in; re-exported here because this is where it is conceptually owned.
__all__ = ["COMMON_SPLIT_RATIOS", "find_seam_candidates", "confirm_split_seams",
           "scan_for_stale_splits", "load_quarantine", "save_quarantine"]


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

def _chunked(items: list, size: int):
    """Yield successive size-length chunks from items."""
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _default_fetcher(tickers: list, start: str, end: str) -> pd.DataFrame:
    """
    Fetch daily bars for a group of tickers in one call, with retries.

    Deliberately reuses the downloader's batch path rather than calling
    yfinance directly: that is where the retry/backoff and the per-ticker
    fallback already live, and verification is the stage most exposed to
    throttling — it runs before any repair, on a cold cache.

    The import is lazy because downloader imports this module at load time.
    Doing it here breaks the cycle, and keeps yfinance out of the analysers,
    which import split_guard only for load_quarantine().
    """
    from downloader import _download_batch_with_retry

    frame, _failed = _download_batch_with_retry(
        tickers, start, end,
        label=f"split verify {tickers[0]}..{tickers[-1]}",
        sleep_seconds=SLEEP_BETWEEN_BATCHES_UPDATE,
    )
    return frame


def _closes_by_ticker(frame: pd.DataFrame) -> dict:
    """{ticker: {'YYYY-MM-DD': close}} from a long-format price frame."""
    lookup: dict = {}
    if frame is None or frame.empty:
        return lookup
    for row in frame.itertuples(index=False):
        close = getattr(row, "close", None)
        if close is None or pd.isna(close) or float(close) <= 0:
            continue
        lookup.setdefault(row.ticker, {})[str(row.date)] = float(close)
    return lookup


def _pad(day: str, days: int, sign: int) -> str:
    """Shift a date string by `days`, so a window survives weekends/holidays."""
    return (pd.Timestamp(day) + sign * timedelta(days=days)).strftime("%Y-%m-%d")


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


def confirm_split_seams(candidates: list, csv_path: str = CSV_PATH,
                        fetcher=None) -> dict:
    """
    Refetch the candidate seams and decide which stored histories are stale.

    Tickers are verified in batches, not one at a time. Each batch is a single
    request covering every seam in it, so a universe-wide sweep costs a handful
    of requests rather than one per candidate — verification runs before any
    repair and on a cold cache, so it is the stage most likely to be throttled,
    and the cheapest place to spend fewer requests.

    ``fetcher(tickers, start, end) -> long-format frame`` is injectable for
    tests; the default goes through the downloader's retrying batch path.

    Returns {'confirmed': [seams + scale],
             'unverified': [tickers we could not settle],
             'checked': tickers covered by a fetch,
             'requests': batches actually issued}
    """
    empty = {"confirmed": [], "unverified": [], "checked": 0, "requests": 0}
    if not candidates:
        return empty

    cache = _load_cache(csv_path)

    # Drop anything already settled as a genuine price move on an earlier run.
    pending: dict = {}
    for seam in candidates:
        if _cache_is_fresh(cache.get(f"{seam['ticker']}@{seam['date']}", {})):
            continue
        pending.setdefault(seam["ticker"], []).append(seam)

    if not pending:
        return empty

    fetcher = fetcher or _default_fetcher
    confirmed, unverified, checked, requests = [], [], 0, 0
    batches = list(_chunked(sorted(pending), SPLIT_VERIFY_BATCH_SIZE))

    for batch_no, batch in enumerate(batches, 1):
        seams = [s for ticker in batch for s in pending[ticker]]
        start = _pad(min(s["prev_date"] for s in seams), SPLIT_VERIFY_WINDOW_DAYS, -1)
        end = _pad(max(s["date"] for s in seams), SPLIT_VERIFY_WINDOW_DAYS, +1)

        try:
            frame = fetcher(batch, start, end)
            requests += 1
        except Exception as e:
            log.warning(f"Split guard: verification batch {batch_no}/{len(batches)} "
                        f"failed ({e}) - {len(batch)} ticker(s) left unsettled")
            unverified.extend(batch)
            continue
        finally:
            if batch_no < len(batches):
                time.sleep(SPLIT_VERIFY_SLEEP)  # gentle on Yahoo's rate limits

        fresh_by_ticker = _closes_by_ticker(frame)
        checked += len(batch)

        for ticker in batch:
            fresh = fresh_by_ticker.get(ticker, {})
            for seam in pending[ticker]:
                verdict, scale = _verify_seam(seam, fresh)

                if verdict == "unknown":
                    log.warning(f"{ticker}: no fresh bars for {seam['prev_date']} "
                                f"to {seam['date']}, cannot settle this seam")
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
                # Repair rewrites the ticker's whole history, so one proven
                # seam is enough — no need to price out the rest.
                break

    _save_cache(cache, csv_path)
    return {
        "confirmed": confirmed,
        "unverified": sorted(set(unverified) - {c["ticker"] for c in confirmed}),
        "checked": checked,
        "requests": requests,
    }


def scan_for_stale_splits(
    df: pd.DataFrame,
    csv_path: str = CSV_PATH,
    lookback_rows: int = SPLIT_SCAN_LOOKBACK_ROWS,
) -> dict:
    """
    Run both stages over a price frame.

    Returns {'candidates': int, 'confirmed': [...], 'tickers': [...],
             'unverified': [...], 'checked': int, 'requests': int}
    """
    candidates = find_seam_candidates(df, lookback_rows=lookback_rows)
    if not candidates:
        log.info("Split guard: no split-shaped seams in the scanned window")
        return {"candidates": 0, "confirmed": [], "tickers": [],
                "unverified": [], "checked": 0, "requests": 0}

    log.info(
        f"Split guard: {len(candidates)} split-shaped seam(s) across "
        f"{len({c['ticker'] for c in candidates})} ticker(s) - refetching "
        f"them to see which are real"
    )
    result = confirm_split_seams(candidates, csv_path=csv_path)
    tickers = sorted({s["ticker"] for s in result["confirmed"]})

    log.info(f"Split guard: verified {result['checked']} ticker(s) in "
             f"{result['requests']} request(s)")

    if tickers:
        log.warning(f"Split guard: {len(tickers)} ticker(s) need repair: {tickers}")
    else:
        log.info("Split guard: no stale splits - every seam checked out as a "
                 "genuine price move, or was already cached as one")

    if result["unverified"]:
        log.warning(
            f"Split guard: {len(result['unverified'])} ticker(s) could not be "
            f"settled this run and stay in the reports unchanged; they are "
            f"retried next run: {result['unverified']}"
        )

    return {
        "candidates": len(candidates),
        "confirmed": result["confirmed"],
        "tickers": tickers,
        "unverified": result["unverified"],
        "checked": result["checked"],
        "requests": result["requests"],
    }
