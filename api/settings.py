"""Environment-driven settings for the reports service.

Everything the service needs to know about *where* things live is resolved
here so the rest of the package never touches ``os.environ`` directly.

Note on ``STOCK_CSV_PATH``: the root ``config.py`` reads the same variable,
which is how ``downloader.py`` ends up writing to the Railway volume instead
of the repo-relative default used for local runs.
"""

from __future__ import annotations

import os
from pathlib import Path

# ── Filesystem ───────────────────────────────────────────────────────────────

# Railway volume mount point. Everything that must survive a redeploy lives here.
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))

# The OHLCV price history the three analysers read.
CSV_PATH = Path(os.getenv("STOCK_CSV_PATH", str(DATA_DIR / "stock_prices.csv")))

# Service-specific tables (packs, purchases). Credits live in Postgres.
SQLITE_PATH = DATA_DIR / "reports_service.db"

# Scratch space for a pack build before its PDFs are uploaded to R2.
PACK_WORK_DIR = DATA_DIR / "packs"

# ── Price data seeding ───────────────────────────────────────────────────────

# R2 object holding a snapshot of stock_prices.csv.  On a cold volume the
# service restores this and then does a normal incremental update, instead of
# re-downloading twenty years of history from Yahoo Finance.
SEED_CSV_R2_KEY = os.getenv("SEED_CSV_R2_KEY", "seed/stock_prices.csv")

# Permit a full historical download when no seed exists.  Off by default: a
# 20-year, 500-ticker bulk pull from a datacenter IP is exactly the thing
# Yahoo Finance throttles, and silently falling back to it would turn a
# missing seed into hours of rate-limited requests.
ALLOW_BULK_SEED = os.getenv("ALLOW_BULK_SEED", "false").lower() == "true"

# ── Pricing ──────────────────────────────────────────────────────────────────

# Credits burned per report pack. Kept configurable so the two products on the
# shared wallet can be repriced relative to each other without a migration.
PACK_CREDIT_COST = int(os.getenv("PACK_CREDIT_COST", "1"))

# ── Build schedule ───────────────────────────────────────────────────────────

# Hour (UTC) at which the daily refresh + rebuild runs. 22:00 UTC is ~6pm ET,
# comfortably after the US close so the day's bars are final.
BUILD_HOUR_UTC = int(os.getenv("BUILD_HOUR_UTC", "22"))

# How often the scheduler thread wakes to check whether it is time to build.
SCHEDULER_POLL_SECONDS = int(os.getenv("SCHEDULER_POLL_SECONDS", "300"))

# Hard ceiling on a single build. A full bulk seed plus three PDFs is normally
# well under this; the timeout only exists so a wedged yfinance call cannot
# block every subsequent build forever.
BUILD_TIMEOUT_SECONDS = int(os.getenv("BUILD_TIMEOUT_SECONDS", "7200"))

# Build a pack on boot if none is ready yet. Disable for local API-only work.
BUILD_ON_BOOT = os.getenv("BUILD_ON_BOOT", "true").lower() == "true"

# Run the scheduler at all. Turn off to serve the API without ever building —
# useful for local frontend work, and required if you ever scale to more than
# one replica, since exactly one process should own the daily build.
SCHEDULER_ENABLED = os.getenv("SCHEDULER_ENABLED", "true").lower() == "true"

# ── Downloads ────────────────────────────────────────────────────────────────

# Lifetime of the presigned R2 URLs handed to the browser.
DOWNLOAD_URL_TTL_SECONDS = int(os.getenv("DOWNLOAD_URL_TTL_SECONDS", "3600"))

# ── Web ──────────────────────────────────────────────────────────────────────

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

ADMIN_SECRET_KEY = os.getenv("ADMIN_SECRET_KEY", "")


def allowed_origins() -> list[str]:
    """CORS allow-list: the configured frontend plus local dev."""
    origins = {FRONTEND_URL, "http://localhost:3000"}
    extra = os.getenv("EXTRA_CORS_ORIGINS", "")
    origins.update(o.strip() for o in extra.split(",") if o.strip())
    return sorted(origins)


def ensure_dirs() -> None:
    """Create the volume directories the service writes to."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PACK_WORK_DIR.mkdir(parents=True, exist_ok=True)
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
