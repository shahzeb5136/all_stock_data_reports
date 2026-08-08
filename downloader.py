"""
Core download logic — OHLCV Edition (CSV-only).

Downloads Open, High, Low, Close, Volume for every ticker.
All price columns are split- and dividend-adjusted (auto_adjust=True).

Two main functions:
  - bulk_download()   : fetches full history from START_DATE for all tickers
  - smart_update()    : fetches only missing/new data since last CSV entry
                        (works whether run daily, weekly, or monthly)

Both write directly to CSV — no database involved.
"""

import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
from functools import reduce
from collections import defaultdict

import pandas as pd
import yfinance as yf

from config import (
    ALL_TICKERS,
    TOP_TICKERS,
    START_DATE,
    BATCH_SIZE,
    SLEEP_BETWEEN_BATCHES,
    SLEEP_BETWEEN_BATCHES_UPDATE,
    CSV_PATH,
    MAX_RETRIES,
    RETRY_DELAY,
    TICKER_FALLBACK_BATCH_SIZE,
    FLUSH_EVERY_N_BATCHES,
    MIN_EXPECTED_ROWS_PER_TICKER,
    MAX_MISSING_DAYS_PCT,
    LOG_LEVEL,
    LOG_FORMAT,
    LOG_DATE_FORMAT,
)

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
log = logging.getLogger("downloader")


# ─────────────────────────────────────────────
# CSV HELPERS
# ─────────────────────────────────────────────

CSV_COLUMNS = ["ticker", "date", "open", "high", "low", "close", "volume"]


def _load_csv(csv_path: str = CSV_PATH) -> pd.DataFrame:
    """Load existing CSV, or return an empty DataFrame if it doesn't exist."""
    p = Path(csv_path)
    if p.exists() and p.stat().st_size > 0:
        try:
            df = pd.read_csv(csv_path, dtype={"date": str})
            # Ensure all expected columns are present
            for col in CSV_COLUMNS:
                if col not in df.columns:
                    df[col] = None
            return df[CSV_COLUMNS]
        except Exception as e:
            log.error(f"Failed to read CSV '{csv_path}': {e}")
            log.warning("Starting with empty DataFrame — existing data preserved on disk")
            return pd.DataFrame(columns=CSV_COLUMNS)
    return pd.DataFrame(columns=CSV_COLUMNS)


def _save_csv(df: pd.DataFrame, csv_path: str = CSV_PATH) -> None:
    """Save the DataFrame to CSV, sorted by ticker then date."""
    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    df.to_csv(csv_path, index=False)
    log.info(f"Saved {len(df):,} rows → {csv_path}")


def _upsert_to_csv(new_df: pd.DataFrame, csv_path: str = CSV_PATH) -> int:
    """
    Merge new_df into the existing CSV using (ticker, date) as the key.
    New rows are added; existing rows are updated (replaced).
    Returns the number of new/updated rows.
    """
    if new_df.empty:
        return 0

    existing = _load_csv(csv_path)

    if existing.empty:
        combined = new_df[CSV_COLUMNS].copy()
    else:
        # Drop existing rows that will be replaced
        key = existing.set_index(["ticker", "date"]).index
        new_key = new_df.set_index(["ticker", "date"]).index
        mask = ~key.isin(new_key)
        combined = pd.concat(
            [existing[mask], new_df[CSV_COLUMNS]], ignore_index=True
        )

    _save_csv(combined, csv_path)
    return len(new_df)


def _get_last_dates(csv_path: str = CSV_PATH) -> dict:
    """Return {ticker: last_date_string} from the CSV."""
    df = _load_csv(csv_path)
    if df.empty:
        return {}
    return df.groupby("ticker")["date"].max().to_dict()


# ─────────────────────────────────────────────
# DOWNLOAD HELPERS
# ─────────────────────────────────────────────

def _download_batch(
    tickers: list,
    start: str,
    end: str,
    label: str = "",
) -> pd.DataFrame:
    """
    Download OHLCV data for a list of tickers in ONE yfinance call.
    Returns a long-format DataFrame with columns:
        ticker, date, open, high, low, close, volume
    """
    if not tickers:
        return pd.DataFrame(columns=CSV_COLUMNS)

    ticker_str = " ".join(tickers)
    log.info(f"[{label}] Downloading {len(tickers)} tickers: "
             f"{tickers[0]}..{tickers[-1]}  ({start} → {end})")

    try:
        raw = yf.download(
            ticker_str,
            start=start,
            end=end,
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as e:
        log.error(f"[{label}] Batch download failed: {e}")
        return pd.DataFrame(columns=CSV_COLUMNS)

    if raw.empty:
        log.warning(f"[{label}] No data returned for batch")
        return pd.DataFrame(columns=CSV_COLUMNS)

    # ── Normalize to long format ──────────────
    frames = []

    if isinstance(raw.columns, pd.MultiIndex):
        # Multiple tickers
        for field, db_col in [("Open", "open"), ("High", "high"),
                               ("Low", "low"), ("Close", "close"),
                               ("Volume", "volume")]:
            if field not in raw.columns.get_level_values(0):
                continue
            sub = raw[field].copy()
            sub.index.name = "date"
            sub = sub.reset_index()
            melted = sub.melt(id_vars="date", var_name="ticker", value_name=db_col)
            frames.append(melted)
    else:
        # Single ticker
        t = tickers[0]
        df_single = raw.copy()
        df_single.index.name = "date"
        df_single = df_single.reset_index()
        for field, db_col in [("Open", "open"), ("High", "high"),
                               ("Low", "low"), ("Close", "close"),
                               ("Volume", "volume")]:
            if field in df_single.columns:
                sub = df_single[["date", field]].copy()
                sub = sub.rename(columns={field: db_col})
                sub["ticker"] = t
                frames.append(sub)

    if not frames:
        return pd.DataFrame(columns=CSV_COLUMNS)

    merged = reduce(
        lambda left, right: pd.merge(left, right, on=["ticker", "date"], how="outer"),
        frames,
    )

    merged["date"] = pd.to_datetime(merged["date"]).dt.strftime("%Y-%m-%d")
    merged = merged.dropna(subset=["close"])

    merged["volume"] = pd.to_numeric(merged["volume"], errors="coerce")
    merged.loc[merged["volume"].notna(), "volume"] = (
        merged.loc[merged["volume"].notna(), "volume"].astype(int)
    )

    return merged[CSV_COLUMNS]


def _download_batch_with_retry(
    tickers: list,
    start: str,
    end: str,
    label: str = "",
    sleep_seconds: float = SLEEP_BETWEEN_BATCHES,
) -> tuple[pd.DataFrame, list[str]]:
    """
    Download a batch with retry logic and per-ticker fallback.

    Returns:
        (DataFrame of successfully downloaded data, list of failed tickers)
    """
    failed_tickers = []

    # ── Attempt 1..MAX_RETRIES on the full batch ──
    for attempt in range(1, MAX_RETRIES + 1):
        df = _download_batch(tickers, start, end, label=f"{label} attempt {attempt}/{MAX_RETRIES}")
        if not df.empty:
            # Check which tickers actually returned data
            got_tickers = set(df["ticker"].unique())
            missing = [t for t in tickers if t not in got_tickers]
            if missing:
                log.warning(f"[{label}] {len(missing)} tickers returned no data: {missing[:10]}"
                            f"{'...' if len(missing) > 10 else ''}")
                # These aren't "failures" per se — they may just have no data
                # in the requested range. We'll try them individually below.
                failed_tickers.extend(missing)
            return df, failed_tickers

        # Batch returned empty — retry
        if attempt < MAX_RETRIES:
            delay = RETRY_DELAY * (2 ** (attempt - 1))
            log.warning(f"[{label}] Attempt {attempt} returned no data. "
                        f"Retrying in {delay}s...")
            time.sleep(delay)

    # ── All retries exhausted — fallback to individual downloads ──
    log.warning(f"[{label}] Batch failed after {MAX_RETRIES} retries. "
                f"Falling back to individual ticker downloads...")

    all_frames = []
    mini_batches = list(_chunked(tickers, TICKER_FALLBACK_BATCH_SIZE))

    for i, mini in enumerate(mini_batches, 1):
        for ticker in mini:
            df = _download_batch([ticker], start, end, label=f"{label} fallback {ticker}")
            if not df.empty:
                all_frames.append(df)
            else:
                failed_tickers.append(ticker)
                log.error(f"[{label}] Ticker {ticker} failed even individually")
            time.sleep(0.5)  # gentle rate limit for individual calls

        if i < len(mini_batches):
            time.sleep(sleep_seconds)

    if all_frames:
        return pd.concat(all_frames, ignore_index=True), failed_tickers
    return pd.DataFrame(columns=CSV_COLUMNS), failed_tickers


def _chunked(lst: list, n: int):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def _format_elapsed(seconds: float) -> str:
    """Format elapsed seconds into a human-readable string."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{int(m)}m {int(s)}s"
    else:
        h, remainder = divmod(seconds, 3600)
        m, s = divmod(remainder, 60)
        return f"{int(h)}h {int(m)}m {int(s)}s"


# ─────────────────────────────────────────────
# DATA VALIDATION
# ─────────────────────────────────────────────

def validate_data(csv_path: str = CSV_PATH) -> dict:
    """
    Run data quality checks on the CSV.
    Returns a dict with validation results.
    """
    df = _load_csv(csv_path)
    if df.empty:
        log.warning("No data to validate — CSV is empty")
        return {"status": "empty"}

    results = {
        "total_rows": len(df),
        "total_tickers": df["ticker"].nunique(),
        "date_range": (df["date"].min(), df["date"].max()),
        "warnings": [],
        "errors": [],
        "ticker_details": {},
    }

    # Generate expected trading days (rough: ~252/year)
    start = pd.Timestamp(df["date"].min())
    end = pd.Timestamp(df["date"].max())
    # Use pandas business day range as approximation
    expected_bdays = len(pd.bdate_range(start, end))

    for ticker, group in df.groupby("ticker"):
        detail = {
            "rows": len(group),
            "date_range": (group["date"].min(), group["date"].max()),
        }

        # Check 1: Too few rows
        if len(group) < MIN_EXPECTED_ROWS_PER_TICKER:
            msg = f"{ticker}: Only {len(group)} rows (expected >= {MIN_EXPECTED_ROWS_PER_TICKER})"
            results["warnings"].append(msg)
            detail["low_row_count"] = True

        # Check 2: Duplicate dates
        dupes = group["date"].duplicated().sum()
        if dupes > 0:
            msg = f"{ticker}: {dupes} duplicate date(s)"
            results["errors"].append(msg)
            detail["duplicate_dates"] = dupes

        # Check 3: Negative prices
        for col in ["open", "high", "low", "close"]:
            neg_count = (pd.to_numeric(group[col], errors="coerce") < 0).sum()
            if neg_count > 0:
                msg = f"{ticker}: {neg_count} negative {col} price(s)"
                results["errors"].append(msg)
                detail[f"negative_{col}"] = neg_count

        # Check 4: Missing days percentage
        ticker_start = pd.Timestamp(group["date"].min())
        ticker_end = pd.Timestamp(group["date"].max())
        ticker_expected = len(pd.bdate_range(ticker_start, ticker_end))
        if ticker_expected > 0:
            missing_pct = ((ticker_expected - len(group)) / ticker_expected) * 100
            if missing_pct > MAX_MISSING_DAYS_PCT:
                msg = (f"{ticker}: {missing_pct:.1f}% of trading days missing "
                       f"({len(group)}/{ticker_expected} days)")
                results["warnings"].append(msg)
                detail["missing_days_pct"] = round(missing_pct, 1)

        # Check 5: Zero volume days (just track, don't flag as error)
        zero_vol = (pd.to_numeric(group["volume"], errors="coerce") == 0).sum()
        if zero_vol > 0:
            detail["zero_volume_days"] = zero_vol

        results["ticker_details"][ticker] = detail

    results["status"] = "clean" if not results["errors"] else "has_errors"
    return results


def print_validation_report(results: dict) -> None:
    """Print a formatted validation report."""
    if results.get("status") == "empty":
        print("No data to validate — CSV is empty.")
        return

    print("\n" + "=" * 60)
    print("DATA VALIDATION REPORT")
    print("=" * 60)
    print(f"  Total rows    : {results['total_rows']:,}")
    print(f"  Total tickers : {results['total_tickers']}")
    print(f"  Date range    : {results['date_range'][0]} → {results['date_range'][1]}")
    print(f"  Status        : {results['status'].upper()}")

    if results["errors"]:
        print(f"\n  ❌ ERRORS ({len(results['errors'])}):")
        for msg in results["errors"][:20]:
            print(f"     • {msg}")
        if len(results["errors"]) > 20:
            print(f"     ... and {len(results['errors']) - 20} more")

    if results["warnings"]:
        print(f"\n  ⚠️  WARNINGS ({len(results['warnings'])}):")
        for msg in results["warnings"][:20]:
            print(f"     • {msg}")
        if len(results["warnings"]) > 20:
            print(f"     ... and {len(results['warnings']) - 20} more")

    if not results["errors"] and not results["warnings"]:
        print("\n  ✅ All checks passed — data looks clean!")

    print("=" * 60 + "\n")


# ─────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────

def bulk_download(
    tickers: list = None,
    start_date: str = None,
) -> dict:
    """
    Full historical download for all tickers from START_DATE to today.
    Writes directly to CSV.

    Returns a summary dict with download statistics.
    """
    tickers = tickers or ALL_TICKERS
    start_date = start_date or START_DATE

    if not tickers:
        log.error("No tickers configured. Add tickers to config.py.")
        return {"status": "error", "message": "No tickers configured"}

    end_date = datetime.today().strftime("%Y-%m-%d")
    t_start = time.time()

    log.info(f"BULK DOWNLOAD: {len(tickers)} tickers, {start_date} → {end_date}")
    log.info(f"Batch size: {BATCH_SIZE}, sleep: {SLEEP_BETWEEN_BATCHES}s, "
             f"retries: {MAX_RETRIES}")

    all_frames = []
    all_failed = []
    batches = list(_chunked(tickers, BATCH_SIZE))
    total_batches = len(batches)
    tickers_done = 0

    for i, batch in enumerate(batches, 1):
        df, failed = _download_batch_with_retry(
            batch, start_date, end_date,
            label=f"bulk {i}/{total_batches}",
            sleep_seconds=SLEEP_BETWEEN_BATCHES,
        )
        if not df.empty:
            all_frames.append(df)
        all_failed.extend(failed)

        tickers_done += len(batch)
        elapsed = time.time() - t_start
        rate = tickers_done / elapsed if elapsed > 0 else 0
        remaining = (len(tickers) - tickers_done) / rate if rate > 0 else 0

        log.info(f"Progress: {tickers_done}/{len(tickers)} tickers "
                 f"({i}/{total_batches} batches) | "
                 f"Elapsed: {_format_elapsed(elapsed)} | "
                 f"ETA: {_format_elapsed(remaining)}")

        # Intermediate flush for crash protection
        if FLUSH_EVERY_N_BATCHES > 0 and i % FLUSH_EVERY_N_BATCHES == 0 and all_frames:
            log.info(f"Intermediate save ({i} batches done)...")
            combined = pd.concat(all_frames, ignore_index=True)
            _upsert_to_csv(combined)
            all_frames = []  # reset accumulator since data is saved

        if i < total_batches:
            time.sleep(SLEEP_BETWEEN_BATCHES)

    # Final save
    if all_frames:
        combined = pd.concat(all_frames, ignore_index=True)
        total_rows = _upsert_to_csv(combined)
    else:
        total_rows = 0

    elapsed = time.time() - t_start

    # ── Summary ──
    summary = {
        "status": "done",
        "tickers_requested": len(tickers),
        "tickers_succeeded": len(tickers) - len(all_failed),
        "tickers_failed": len(all_failed),
        "failed_tickers": all_failed,
        "rows_written": total_rows,
        "elapsed": _format_elapsed(elapsed),
    }
    _print_summary(summary, title="BULK DOWNLOAD COMPLETE")
    return summary


def smart_update(
    tickers: list = None,
) -> dict:
    """
    Incremental update: only fetches data from each ticker's last CSV date
    to today. Works whether run daily, weekly, or after months of inactivity.

    Strategy:
      1. Group tickers by their last-known date in the CSV.
      2. For each group, do one batch download from (last_date + 1 day) → today.
      3. Tickers not yet in the CSV get a full historical download from START_DATE.
      4. Tickers in CSV but not in config are logged but left untouched.

    Returns a summary dict with download statistics.
    """
    tickers = tickers or ALL_TICKERS

    if not tickers:
        log.error("No tickers configured. Add tickers to config.py.")
        return {"status": "error", "message": "No tickers configured"}

    t_start = time.time()
    last_dates = _get_last_dates()
    today = datetime.today().strftime("%Y-%m-%d")

    # ── Check for orphaned tickers (in CSV but not in config) ──
    config_set = set(t.upper() for t in tickers)
    csv_tickers = set(last_dates.keys())
    orphaned = csv_tickers - config_set
    if orphaned:
        log.info(f"{len(orphaned)} ticker(s) in CSV but not in config "
                 f"(data preserved): {sorted(orphaned)[:10]}"
                 f"{'...' if len(orphaned) > 10 else ''}")

    # ── Separate tickers into groups ──────────
    new_tickers = [t for t in tickers if t not in last_dates]
    existing = {t: last_dates[t] for t in tickers if t in last_dates}

    # Group existing tickers by their last date so we can batch them
    groups: dict = defaultdict(list)
    for t, last in existing.items():
        next_day = (datetime.strptime(last, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        if next_day <= today:
            groups[next_day].append(t)

    already_current = len(existing) - sum(len(v) for v in groups.values())
    need_update = sum(len(v) for v in groups.values())

    log.info(f"UPDATE: {len(tickers)} tickers total")
    log.info(f"  • {already_current} already up to date")
    log.info(f"  • {need_update} need incremental update ({len(groups)} date-groups)")
    log.info(f"  • {len(new_tickers)} are new (full download from {START_DATE})")

    all_new_frames = []
    all_failed = []
    total_work = need_update + len(new_tickers)
    work_done = 0

    # ── Incremental updates (grouped by start date) ──
    for start_date, group_tickers in sorted(groups.items()):
        batches = list(_chunked(group_tickers, BATCH_SIZE))
        for i, batch in enumerate(batches, 1):
            df, failed = _download_batch_with_retry(
                batch, start_date, today,
                label=f"update from {start_date}",
                sleep_seconds=SLEEP_BETWEEN_BATCHES_UPDATE,
            )
            if not df.empty:
                all_new_frames.append(df)
            all_failed.extend(failed)
            work_done += len(batch)

            if i < len(batches):
                time.sleep(SLEEP_BETWEEN_BATCHES_UPDATE)

        time.sleep(SLEEP_BETWEEN_BATCHES_UPDATE)

        # Progress logging
        if total_work > 0:
            elapsed = time.time() - t_start
            pct = (work_done / total_work) * 100
            log.info(f"Progress: {work_done}/{total_work} tickers ({pct:.0f}%) | "
                     f"Elapsed: {_format_elapsed(elapsed)}")

    # ── New tickers: full historical download ──
    if new_tickers:
        log.info(f"Full download for {len(new_tickers)} new tickers from {START_DATE}...")
        batches = list(_chunked(new_tickers, BATCH_SIZE))
        for i, batch in enumerate(batches, 1):
            df, failed = _download_batch_with_retry(
                batch, START_DATE, today,
                label=f"new tickers {i}/{len(batches)}",
                sleep_seconds=SLEEP_BETWEEN_BATCHES,
            )
            if not df.empty:
                all_new_frames.append(df)
            all_failed.extend(failed)
            work_done += len(batch)

            # Intermediate flush for large new-ticker downloads
            if (FLUSH_EVERY_N_BATCHES > 0 and
                    i % FLUSH_EVERY_N_BATCHES == 0 and all_new_frames):
                log.info(f"Intermediate save ({i} batches of new tickers done)...")
                combined = pd.concat(all_new_frames, ignore_index=True)
                _upsert_to_csv(combined)
                all_new_frames = []

            if i < len(batches):
                time.sleep(SLEEP_BETWEEN_BATCHES)

    # ── Final save ──
    if all_new_frames:
        combined = pd.concat(all_new_frames, ignore_index=True)
        total_rows = _upsert_to_csv(combined)
    else:
        total_rows = 0

    elapsed = time.time() - t_start

    # ── Summary ──
    summary = {
        "status": "done",
        "tickers_requested": len(tickers),
        "tickers_already_current": already_current,
        "tickers_updated": need_update - len([f for f in all_failed if f not in new_tickers]),
        "tickers_new_downloaded": len(new_tickers) - len([f for f in all_failed if f in new_tickers]),
        "tickers_failed": len(all_failed),
        "failed_tickers": all_failed,
        "rows_written": total_rows,
        "elapsed": _format_elapsed(elapsed),
    }
    _print_summary(summary, title="UPDATE COMPLETE")
    return summary


# Backward compatibility alias
daily_update = smart_update


def _print_summary(summary: dict, title: str = "SUMMARY") -> None:
    """Print a formatted run summary."""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)
    print(f"  Tickers requested   : {summary.get('tickers_requested', 'N/A')}")

    if "tickers_already_current" in summary:
        print(f"  Already up to date  : {summary['tickers_already_current']}")
    if "tickers_updated" in summary:
        print(f"  Updated             : {summary['tickers_updated']}")
    if "tickers_new_downloaded" in summary:
        print(f"  New downloaded      : {summary['tickers_new_downloaded']}")
    if "tickers_succeeded" in summary:
        print(f"  Succeeded           : {summary['tickers_succeeded']}")

    print(f"  Failed              : {summary.get('tickers_failed', 0)}")
    print(f"  Rows written        : {summary.get('rows_written', 0):,}")
    print(f"  Elapsed time        : {summary.get('elapsed', 'N/A')}")

    if summary.get("failed_tickers"):
        failed = summary["failed_tickers"]
        print(f"\n  ❌ Failed tickers ({len(failed)}):")
        for t in failed[:30]:
            print(f"     • {t}")
        if len(failed) > 30:
            print(f"     ... and {len(failed) - 30} more")
    else:
        print(f"\n  ✅ All tickers processed successfully!")

    print("=" * 60 + "\n")


def query_csv(
    ticker: str = None,
    start_date: str = None,
    end_date: str = None,
    csv_path: str = CSV_PATH,
) -> pd.DataFrame:
    """Convenience function to query the local CSV."""
    df = _load_csv(csv_path)
    if ticker:
        df = df[df["ticker"] == ticker.upper()]
    if start_date:
        df = df[df["date"] >= start_date]
    if end_date:
        df = df[df["date"] <= end_date]
    return df.reset_index(drop=True)
