"""Subprocess entrypoint that refreshes prices and builds one report pack.

Run as::

    python -m api.build_pack --out-dir /data/packs/<pack_id> --snapshot-date 2026-08-08

Building in a separate process is deliberate: the analysers hold the entire
price history in pandas (well over a gigabyte on a full universe), and a
crash or an OOM here must not be able to take the API down with it.  The
parent reads the manifest from stdout and owns all uploads and DB writes.

Progress goes to stderr; stdout carries exactly one machine-readable line.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import traceback
from pathlib import Path

# Emitted on stdout so the parent can find the manifest amid library logging.
MANIFEST_SENTINEL = "__PACK_MANIFEST__"

logger = logging.getLogger("build_pack")


def refresh_prices(csv_path: Path) -> None:
    """Bring the local price CSV up to date.

    A missing CSV means this is a cold volume, so it does the full history
    load; otherwise it fetches only the days each ticker is missing.
    """
    # Imported here so a --skip-refresh build never pays the yfinance import.
    from downloader import bulk_download, smart_update

    if not csv_path.exists() or csv_path.stat().st_size == 0:
        logger.info("No price CSV at %s — running full historical download", csv_path)
        summary = bulk_download()
        logger.info("Bulk download complete: %s", summary)
        return

    logger.info("Updating price CSV at %s", csv_path)
    summary = smart_update()
    logger.info("Incremental update complete: %s", summary)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build one stock report pack.")
    parser.add_argument("--out-dir", required=True, help="Directory to write the PDFs into")
    parser.add_argument("--snapshot-date", required=True, help="Pack snapshot date (YYYY-MM-DD)")
    parser.add_argument(
        "--skip-refresh",
        action="store_true",
        help="Build from the price CSV as-is, without contacting Yahoo Finance",
    )
    args = parser.parse_args()

    # The report scripts print emoji. When stdout is a pipe (which is exactly
    # how the scheduler runs this) Python picks the platform's default codec
    # instead of UTF-8, and those prints raise UnicodeEncodeError. Force UTF-8
    # on both streams so progress output can never abort a build.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    from api.builder import build_all
    from api.settings import CSV_PATH, ensure_dirs

    ensure_dirs()

    try:
        if args.skip_refresh:
            logger.info("Skipping price refresh (--skip-refresh)")
        else:
            refresh_prices(CSV_PATH)

        if not CSV_PATH.exists():
            raise FileNotFoundError(f"Price CSV missing after refresh: {CSV_PATH}")

        manifest = build_all(
            csv_path=CSV_PATH,
            out_dir=Path(args.out_dir),
            snapshot_date=args.snapshot_date,
        )
    except Exception:
        traceback.print_exc(file=sys.stderr)
        return 1

    print(MANIFEST_SENTINEL + json.dumps(manifest), flush=True)
    logger.info("Pack build finished: %s reports", len(manifest["reports"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
