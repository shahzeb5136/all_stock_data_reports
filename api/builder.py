"""Drives the three report generators against a price snapshot.

The analysers in ``reports/`` are left untouched — this module imports them
and calls their existing functions, so local ``python reports/x.py`` runs and
the hosted service always produce the same PDFs from the same code.

Two details are inherited from how those scripts expect to be run:

* ``dip_analyzer`` does ``from company_data import COMPANY_DATA``, a
  top-level import, so ``reports/`` must be on ``sys.path`` rather than
  imported as a package.
* Chart PNGs are written to a ``charts/`` directory beside the scripts.
  They are intermediate artifacts consumed by the PDF build, so the
  directory is swept clean before each run.

This module is intended to run inside the build subprocess (see
``api.build_pack``) — it holds the full price history in memory and should
not share a process with the API.
"""

from __future__ import annotations

import gc
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = REPO_ROOT / "reports"

# Catalogue of what a pack contains. ``slug`` is the stable identifier the
# frontend keys off; title and description are display copy.
REPORT_CATALOGUE: List[Dict[str, str]] = [
    {
        "slug": "dip",
        "title": "Dip Opportunities",
        "description": (
            "The 20 strongest pullbacks across the tracked universe, scored on drawdown "
            "from the 30-day high, 30-day return, how abnormal that move is against each "
            "stock's own history, and distance below the 60-day average. Filtered to "
            "exclude names in sustained long-term downtrends."
        ),
    },
    {
        "slug": "surge",
        "title": "Momentum Surges",
        "description": (
            "The 20 strongest recent breakouts, scored on rally from the 30-day low, "
            "30-day return, z-score against each stock's own history, and distance above "
            "the 60-day average. Extreme multi-year runners are filtered out so genuine "
            "new momentum surfaces."
        ),
    },
    {
        "slug": "stable_growth",
        "title": "Stable Growth Leaders",
        "description": (
            "The 20 smoothest upward trajectories, ranked by a composite stability score "
            "built from trend fit, volatility, and drawdown across 6-month, 1-, 2- and "
            "3-year windows, benchmarked against the S&P 500 where available."
        ),
    },
]

_CATALOGUE_BY_SLUG = {r["slug"]: r for r in REPORT_CATALOGUE}


def _ensure_import_path() -> None:
    """Put the repo root and reports/ on sys.path, as direct execution does."""
    for path in (str(REPO_ROOT), str(REPORTS_DIR)):
        if path not in sys.path:
            sys.path.insert(0, path)


def _sweep_chart_dirs() -> None:
    """Remove stale chart PNGs so a failed run cannot leak into the next PDF."""
    for chart_dir in {REPORTS_DIR / "charts", Path.cwd() / "charts"}:
        if not chart_dir.is_dir():
            continue
        for png in chart_dir.glob("*.png"):
            try:
                png.unlink()
            except OSError as exc:
                logger.warning("Could not remove stale chart %s: %s", png, exc)


def _filename(slug: str, snapshot_date: str) -> str:
    return f"{slug}_report_{snapshot_date}.pdf"


def _record(slug: str, path: Path) -> Dict[str, Any]:
    meta = _CATALOGUE_BY_SLUG[slug]
    return {
        "slug": slug,
        "title": meta["title"],
        "description": meta["description"],
        "filename": path.name,
        "path": str(path),
        "bytes": path.stat().st_size,
    }


def build_all(csv_path: Path, out_dir: Path, snapshot_date: str) -> Dict[str, Any]:
    """Build all three PDFs into ``out_dir``.

    Returns a manifest describing the snapshot and the files produced.
    Raises if any single report fails — a pack is all-or-nothing, since the
    user is charged one credit for the complete set.
    """
    _ensure_import_path()
    _sweep_chart_dirs()
    out_dir.mkdir(parents=True, exist_ok=True)

    import dip_analyzer
    import surge_analyzer
    import stable_growth_report as growth

    reports: List[Dict[str, Any]] = []

    # ── Dip + Surge share one load of the raw OHLCV frame ────────────────────
    logger.info("Loading price history from %s", csv_path)
    df = dip_analyzer.load_data(str(csv_path))
    data_through = str(df["date"].max().date())
    ticker_count = int(df["ticker"].nunique())
    logger.info(
        "Loaded %s rows, %s tickers, through %s", f"{len(df):,}", ticker_count, data_through
    )

    # ── 1/3 Dip ──────────────────────────────────────────────────────────────
    logger.info("Building dip report")
    dip_ranked = dip_analyzer.analyze_dips(df, lookback=22)
    dip_top = dip_analyzer.filter_long_term_downtrends(dip_ranked, top_n=20)
    dip_info = dip_analyzer.fetch_company_info(dip_top["ticker"].tolist())
    dip_path = out_dir / _filename("dip", snapshot_date)
    dip_analyzer.generate_pdf(dip_top, dip_info, df, str(dip_path))
    reports.append(_record("dip", dip_path))

    # ── 2/3 Surge ────────────────────────────────────────────────────────────
    logger.info("Building surge report")
    surge_ranked = surge_analyzer.analyze_surges(df, lookback=22)
    surge_top = surge_analyzer.filter_extreme_runners(surge_ranked, top_n=20)
    surge_info = surge_analyzer.fetch_company_info(surge_top["ticker"].tolist())
    surge_path = out_dir / _filename("surge", snapshot_date)
    surge_analyzer.generate_pdf(surge_top, surge_info, df, str(surge_path))
    reports.append(_record("surge", surge_path))

    # Release the raw frame before the growth report builds its own pivot.
    del df, dip_ranked, dip_top, surge_ranked, surge_top
    gc.collect()

    # ── 3/3 Stable growth ────────────────────────────────────────────────────
    # Mirrors stable_growth_report.main(), minus its hardcoded output path.
    logger.info("Building stable growth report")
    prices = growth.load_csv(str(csv_path))
    benchmark = growth.find_benchmark(prices)
    ranked = growth.analyze_all(prices, benchmark)
    if not ranked:
        raise RuntimeError("Stable growth analysis returned no qualifying stocks")

    top = ranked[: growth.TOP_N]
    for result in top:
        ticker = result["ticker"]
        result["fundamentals"] = growth.fetch_fundamentals(ticker)
        last_year = prices[ticker].iloc[-252:].dropna()
        if len(last_year) > 0:
            result["fundamentals"]["52w_high"] = float(last_year.max())
            result["fundamentals"]["52w_low"] = float(last_year.min())
            result["fundamentals"]["current_price"] = float(last_year.iloc[-1])

    overview_chart, individual_charts = growth.generate_charts(top, prices, benchmark)
    growth_path = out_dir / _filename("stable_growth", snapshot_date)
    growth.generate_pdf(
        top, overview_chart, individual_charts, benchmark is not None, str(growth_path)
    )
    reports.append(_record("stable_growth", growth_path))

    del prices, ranked, top
    gc.collect()

    return {
        "snapshot_date": snapshot_date,
        "data_through": data_through,
        "ticker_count": ticker_count,
        "reports": reports,
    }
