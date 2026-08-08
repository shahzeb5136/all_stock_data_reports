#!/usr/bin/env python3
"""Upload the local price history to R2 so the hosted service can restore it.

Run this ONCE before the first Railway deploy.  Without it, a cold volume has
no history to build from, and the only alternative is re-downloading twenty
years of data for every ticker from Yahoo Finance — slow, and heavily
throttled from a datacenter IP.

After the first deploy the service maintains the volume incrementally.  Re-run
this occasionally (or call POST /api/admin/seed/backup) to refresh the seed so
a volume rebuild has less catching up to do.

Usage:
    python scripts/seed_upload.py                    # uses reports/stock_prices.csv
    python scripts/seed_upload.py path/to/prices.csv
    python scripts/seed_upload.py --download out.csv # pull the seed back down

Reads R2 credentials from .env or the environment:
    R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env")


class _Progress:
    """Print a single-line percentage as boto3 streams the file."""

    def __init__(self, total: int, label: str) -> None:
        self._total = total
        self._label = label
        self._seen = 0
        self._lock = threading.Lock()
        self._started = time.time()

    def __call__(self, chunk: int) -> None:
        with self._lock:
            self._seen += chunk
            pct = (self._seen / self._total * 100) if self._total else 0
            mb = self._seen / (1024 * 1024)
            total_mb = self._total / (1024 * 1024)
            elapsed = time.time() - self._started
            rate = mb / elapsed if elapsed > 0 else 0
            sys.stdout.write(
                f"\r  {self._label} {mb:7.1f} / {total_mb:.1f} MB  "
                f"({pct:5.1f}%)  {rate:5.1f} MB/s"
            )
            sys.stdout.flush()


def _check_env() -> None:
    missing = [
        k
        for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")
        if not os.getenv(k)
    ]
    if missing:
        print(f"Missing required environment variables: {', '.join(missing)}")
        print("Set them in .env or your shell, then re-run.")
        sys.exit(1)


def upload(csv_path: Path) -> None:
    from api.settings import SEED_CSV_R2_KEY
    from api.storage import _bucket, _client

    if not csv_path.exists():
        print(f"No such file: {csv_path}")
        sys.exit(1)

    size = csv_path.stat().st_size
    if size == 0:
        print(f"{csv_path} is empty — refusing to upload it as a seed.")
        sys.exit(1)

    print(f"Uploading {csv_path}")
    print(f"       to r2://{_bucket()}/{SEED_CSV_R2_KEY}")
    print(f"     size {size / (1024 * 1024):.1f} MB\n")

    _client().upload_file(
        str(csv_path),
        _bucket(),
        SEED_CSV_R2_KEY,
        ExtraArgs={"ContentType": "text/csv"},
        Callback=_Progress(size, "uploaded"),
    )
    print("\n\nSeed uploaded. The service will restore this on a cold volume,")
    print("then bring it up to date incrementally.")


def download(dest: Path) -> None:
    from api.settings import SEED_CSV_R2_KEY
    from api.storage import _bucket, _client, object_exists

    if not object_exists(SEED_CSV_R2_KEY):
        print(f"No seed found at r2://{_bucket()}/{SEED_CSV_R2_KEY}")
        sys.exit(1)

    head = _client().head_object(Bucket=_bucket(), Key=SEED_CSV_R2_KEY)
    size = head["ContentLength"]
    print(f"Downloading r2://{_bucket()}/{SEED_CSV_R2_KEY}")
    print(f"         to {dest}")
    print(f"       size {size / (1024 * 1024):.1f} MB\n")

    dest.parent.mkdir(parents=True, exist_ok=True)
    _client().download_file(
        _bucket(), SEED_CSV_R2_KEY, str(dest), Callback=_Progress(size, "downloaded")
    )
    print("\n\nDone.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "csv",
        nargs="?",
        default=str(REPO_ROOT / "reports" / "stock_prices.csv"),
        help="Path to the price CSV (default: reports/stock_prices.csv)",
    )
    parser.add_argument(
        "--download",
        metavar="DEST",
        help="Download the existing seed to DEST instead of uploading",
    )
    args = parser.parse_args()

    _check_env()

    if args.download:
        download(Path(args.download))
    else:
        upload(Path(args.csv))


if __name__ == "__main__":
    main()
