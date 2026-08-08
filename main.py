#!/usr/bin/env python3
"""
Stock Price Downloader — Main Entry Point (OHLCV Edition)
=========================================================

Usage:
    python main.py bulk       Full historical download from 2005 (initial load)
    python main.py update     Smart incremental update (fetches only missing data)
    python main.py query AAPL Query a specific ticker from the CSV
    python main.py stats      Show CSV statistics
    python main.py validate   Run data quality checks on the CSV

Examples:
    # First run — download everything since 2005:
    python main.py bulk

    # Any time after that — grab only new data since last run:
    python main.py update

    # Pull data for one ticker:
    python main.py query AAPL

    # Check data quality:
    python main.py validate
"""

import sys
import os

from config import CSV_PATH, ALL_TICKERS, TOP_TICKERS, START_DATE
from downloader import (
    bulk_download,
    smart_update,
    query_csv,
    validate_data,
    print_validation_report,
)


def cmd_bulk():
    print("=" * 60)
    print("BULK DOWNLOAD — Full Historical Load (OHLCV)")
    print(f"  From: {START_DATE}  |  Tickers: {len(ALL_TICKERS)}")
    print(f"  Fields: open, high, low, close, volume")
    print("=" * 60)
    bulk_download()


def cmd_update():
    print("=" * 60)
    print("SMART UPDATE — Incremental (OHLCV)")
    print(f"  Tickers: {len(ALL_TICKERS)}")
    print("=" * 60)
    smart_update()


def cmd_query(ticker: str):
    import pandas as pd
    df = query_csv(ticker=ticker.upper())
    if df.empty:
        print(f"No data found for {ticker.upper()}")
    else:
        print(f"\n{ticker.upper()} — {len(df)} rows")
        print(f"{'Date':<12} {'Open':>10} {'High':>10} {'Low':>10} {'Close':>10} {'Volume':>14}")
        print("─" * 68)
        for _, row in df.tail(20).iterrows():
            vol = f"{int(row['volume']):,}" if pd.notna(row['volume']) else "N/A"
            print(f"{row['date']:<12} {row['open']:>10.2f} {row['high']:>10.2f} "
                  f"{row['low']:>10.2f} {row['close']:>10.2f} {vol:>14}")
        if len(df) > 20:
            print(f"\n(Showing last 20 of {len(df)} rows)")


def cmd_stats():
    import pandas as pd
    csv_size = os.path.getsize(CSV_PATH) / (1024 * 1024) if os.path.exists(CSV_PATH) else 0

    if not os.path.exists(CSV_PATH):
        print("No CSV file found. Run 'python main.py bulk' first.")
        return

    df = query_csv()
    print(f"\n{'─' * 50}")
    print(f"  CSV         : {CSV_PATH} ({csv_size:.1f} MB)")
    print(f"  Total rows  : {len(df):,}")
    print(f"  Tickers     : {df['ticker'].nunique()}")
    print(f"  Date range  : {df['date'].min()} → {df['date'].max()}")
    print(f"  Config      : {len(ALL_TICKERS)} tickers, start={START_DATE}")
    print(f"  Fields      : ticker, date, open, high, low, close, volume")
    print(f"{'─' * 50}\n")


def cmd_validate():
    if not os.path.exists(CSV_PATH):
        print("No CSV file found. Run 'python main.py bulk' first.")
        return

    results = validate_data()
    print_validation_report(results)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    command = sys.argv[1].lower()

    if command == "bulk":
        cmd_bulk()
    elif command == "update":
        cmd_update()
    elif command == "query":
        if len(sys.argv) < 3:
            print("Usage: python main.py query <TICKER>")
            return
        cmd_query(sys.argv[2])
    elif command == "stats":
        cmd_stats()
    elif command == "validate":
        cmd_validate()
    else:
        print(f"Unknown command: {command}")
        print(__doc__)


if __name__ == "__main__":
    main()
