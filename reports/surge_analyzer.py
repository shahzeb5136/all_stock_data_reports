"""
Stock Surge Analyzer
====================
Reads stock_prices.csv (ticker, date, price), identifies the top 20 tickers
that have surged the most recently, fetches basic company info, and produces
a polished PDF report.

Methodology
-----------
For each ticker we compute several surge metrics over the trailing ~22 trading days:
  1. Rally from 30-day low: (recent_price - 30d_low) / 30d_low
  2. 30-day simple return: (recent_price - price_30d_ago) / price_30d_ago
  3. Z-score of the 30-day return vs the ticker's own rolling 30-day return
     distribution (measures how abnormal the surge is relative to the stock's
     own historical behaviour).
  4. Percentage above the 60-day moving average.

These are combined into a composite "surge score" that ranks tickers.

Long-Term Trend Filter
----------------------
After scoring, stocks are filtered to exclude those that were already in a
sustained long-term uptrend (to surface breakout/momentum surges rather than
stocks that have simply been climbing steadily). Only stocks where at least
one of the 1-year or 1.5-year returns is below +100% are kept, preventing
extreme multi-year runners from dominating the list.
"""

import os
import sys
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings("ignore")

# ── 1. LOAD & PREPARE DATA ─────────────────────────────────────────────────

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Tickers the downloader could not lift off a stale split adjustment. This
# report is the more exposed of the two: an unrepaired 1-for-10 reverse split
# reads as a +900% one-day gain, which outranks every genuine breakout — and
# reverse splits cluster in exactly the distressed names you least want here.
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
try:
    from split_guard import load_quarantine
except Exception:
    def load_quarantine(csv_path=None):
        return set()


def load_data(path=None):
    if path is None:
        path = os.path.join(_SCRIPT_DIR, "stock_prices.csv")
    df = pd.read_csv(path, parse_dates=["date"])

    quarantined = load_quarantine(path) & set(df["ticker"].unique())
    if quarantined:
        print(f"  [!] Excluding {len(quarantined)} ticker(s) with a stale split "
              f"adjustment: {', '.join(sorted(quarantined))}")
        df = df[~df["ticker"].isin(quarantined)]

    df.sort_values(["ticker", "date"], inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df

def analyze_surges(df, lookback=22):
    """
    For each ticker compute surge metrics over the last `lookback` trading days,
    plus long-term return metrics (1-year, 1.5-year).
    Returns a DataFrame ranked by composite surge score (most positive = biggest surge).
    """
    results = []
    latest_date = df["date"].max()

    TRADING_DAYS_1Y = 252
    TRADING_DAYS_1_5Y = 378

    for ticker, grp in df.groupby("ticker"):
        grp = grp.sort_values("date").reset_index(drop=True)
        if len(grp) < lookback + 30:
            continue  # not enough history

        recent = grp.tail(lookback)
        current_price = grp["close"].iloc[-1]

        # 1. Rally from 30-day low
        low_30d = recent["close"].min()
        rally_from_low = (current_price - low_30d) / low_30d

        # 2. 30-day simple return
        price_30d_ago = grp["close"].iloc[-(lookback + 1)]
        return_30d = (current_price - price_30d_ago) / price_30d_ago

        # 3. Z-score of 30d return vs historical rolling 30d returns
        grp["ret_30d"] = grp["close"].pct_change(lookback)
        hist_returns = grp["ret_30d"].dropna()
        if len(hist_returns) > 10:
            mu = hist_returns.mean()
            sigma = hist_returns.std()
            z_score = (return_30d - mu) / sigma if sigma > 0 else 0
        else:
            z_score = 0

        # 4. % above 60-day moving average
        grp["ma60"] = grp["close"].rolling(60).mean()
        ma60_val = grp["ma60"].iloc[-1]
        pct_above_ma60 = (current_price - ma60_val) / ma60_val if pd.notna(ma60_val) else 0

        # 5. Composite score (all components are positive for surges — more positive = bigger surge)
        composite = (
            0.30 * rally_from_low +
            0.30 * return_30d +
            0.15 * (z_score / 10) +      # scaled down since z-scores can be large
            0.25 * pct_above_ma60
        )

        # 6. Long-term returns (1-year and 1.5-year)
        if len(grp) > TRADING_DAYS_1Y:
            price_1y_ago = grp["close"].iloc[-(TRADING_DAYS_1Y + 1)]
            return_1y = (current_price - price_1y_ago) / price_1y_ago
        else:
            return_1y = np.nan

        if len(grp) > TRADING_DAYS_1_5Y:
            price_1_5y_ago = grp["close"].iloc[-(TRADING_DAYS_1_5Y + 1)]
            return_1_5y = (current_price - price_1_5y_ago) / price_1_5y_ago
        else:
            return_1_5y = np.nan

        results.append({
            "ticker": ticker,
            "current_price": round(current_price, 2),
            "price_30d_ago": round(price_30d_ago, 2),
            "low_30d": round(low_30d, 2),
            "return_30d_pct": round(return_30d * 100, 2),
            "rally_from_low_pct": round(rally_from_low * 100, 2),
            "z_score": round(z_score, 2),
            "pct_above_ma60": round(pct_above_ma60 * 100, 2),
            "composite_surge_score": round(composite * 100, 4),
            "return_1y_pct": round(return_1y * 100, 2) if pd.notna(return_1y) else np.nan,
            "return_1_5y_pct": round(return_1_5y * 100, 2) if pd.notna(return_1_5y) else np.nan,
            "latest_date": latest_date,
        })

    results_df = pd.DataFrame(results)
    results_df.sort_values("composite_surge_score", ascending=False, inplace=True)
    results_df.reset_index(drop=True, inplace=True)
    return results_df


def filter_extreme_runners(surge_df, top_n=20):
    """
    Filter out stocks that are extreme multi-year runners (to keep focus on
    recent breakout surges rather than stocks that have been climbing for years).
    Keeps stocks where AT LEAST ONE of:
      - 1-year return is below +100%, OR
      - 1.5-year return is below +100%, OR
      - data is not available for either period (benefit of the doubt).
    Returns the top `top_n` stocks after filtering.
    """
    # Take a bigger initial pool so we can filter down to top_n
    pool = surge_df.head(top_n * 3).copy()

    def passes_filter(row):
        r1y = row["return_1y_pct"]
        r1_5y = row["return_1_5y_pct"]
        # If both are available and both above +100% → extreme runner → exclude
        if pd.notna(r1y) and pd.notna(r1_5y):
            return r1y < 100 or r1_5y < 100
        # If only one is available, check that one
        if pd.notna(r1y):
            return r1y < 100
        if pd.notna(r1_5y):
            return r1_5y < 100
        # If neither is available, give benefit of the doubt
        return True

    filtered = pool[pool.apply(passes_filter, axis=1)].copy()
    filtered = filtered.head(top_n).reset_index(drop=True)

    removed_count = len(pool) - len(pool[pool.apply(passes_filter, axis=1)])
    print(f"  Extreme-runner filter: removed {removed_count} stocks already up >100% long-term")
    print(f"  Remaining after filter: {len(filtered)} stocks")

    return filtered

# ── 2. FETCH COMPANY INFO (yfinance) ───────────────────────────────────────

def fetch_company_info(tickers):
    """
    Fetch basic company info for a list of tickers.
    Tries yfinance first; falls back to hardcoded data if unavailable.
    Returns a dict: ticker -> info_dict
    """
    # Try yfinance first
    info_map = {}
    yf_available = False
    try:
        import yfinance as yf
        test = yf.Ticker("AAPL")
        _ = test.info.get("longName")
        yf_available = True
        print("  Using live data from Yahoo Finance")
    except Exception:
        print("  Yahoo Finance unavailable, using built-in company database")

    if yf_available:
        for t in tickers:
            try:
                stock = yf.Ticker(t)
                info = stock.info
                info_map[t] = {
                    "name": info.get("longName") or info.get("shortName", t),
                    "sector": info.get("sector", "N/A"),
                    "industry": info.get("industry", "N/A"),
                    "market_cap": info.get("marketCap", None),
                    "pe_ratio": info.get("trailingPE", None),
                    "forward_pe": info.get("forwardPE", None),
                    "avg_volume": info.get("averageVolume", None),
                    "52w_high": info.get("fiftyTwoWeekHigh", None),
                    "52w_low": info.get("fiftyTwoWeekLow", None),
                    "description": info.get("longBusinessSummary", "No description available."),
                }
            except Exception:
                pass
    
    # Fallback to hardcoded data for any missing tickers
    from company_data import COMPANY_DATA
    for t in tickers:
        if t not in info_map:
            if t in COMPANY_DATA:
                info_map[t] = COMPANY_DATA[t]
            else:
                info_map[t] = {
                    "name": t, "sector": "N/A", "industry": "N/A",
                    "market_cap": None, "pe_ratio": None, "forward_pe": None,
                    "avg_volume": None, "52w_high": None, "52w_low": None,
                    "description": "Company information unavailable.",
                }
    return info_map

# ── 3. GENERATE PDF REPORT ─────────────────────────────────────────────────

def format_large_number(n):
    if n is None:
        return "N/A"
    if n >= 1e12:
        return f"${n/1e12:.2f}T"
    elif n >= 1e9:
        return f"${n/1e9:.2f}B"
    elif n >= 1e6:
        return f"${n/1e6:.1f}M"
    else:
        return f"${n:,.0f}"

def format_volume(n):
    if n is None:
        return "N/A"
    if n >= 1e6:
        return f"{n/1e6:.1f}M"
    elif n >= 1e3:
        return f"{n/1e3:.0f}K"
    return str(n)

def generate_mini_charts(df, tickers, output_dir="charts"):
    """
    Generate price charts for each ticker showing:
      - Last 90 trading days
      - Last 1 year (~252 trading days)
      - Last 2 years (~504 trading days)
    Returns a dict: ticker -> {"90d": path, "1y": path, "2y": path}
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import os

    output_dir = os.path.join(_SCRIPT_DIR, output_dir)
    os.makedirs(output_dir, exist_ok=True)

    CHART_CONFIGS = [
        {"key": "90d",  "days": 90,  "title": "Last 90 Trading Days",  "ma": 20,  "date_fmt": "%b",   "locator": mdates.MonthLocator()},
        {"key": "1y",   "days": 252, "title": "Last 1 Year",           "ma": 50,  "date_fmt": "%b %y", "locator": mdates.MonthLocator(interval=2)},
        {"key": "2y",   "days": 504, "title": "Last 2 Years",          "ma": 100, "date_fmt": "%b %y", "locator": mdates.MonthLocator(interval=3)},
    ]

    chart_paths = {}
    for ticker in tickers:
        ticker_data = df[df["ticker"] == ticker].sort_values("date")
        if ticker_data.empty:
            continue

        ticker_charts = {}
        for cfg in CHART_CONFIGS:
            grp = ticker_data.tail(cfg["days"])
            if len(grp) < 20:
                continue

            fig, ax = plt.subplots(figsize=(5.5, 1.8))
            dates = grp["date"]
            prices = grp["close"]

            # Color the line: green if up overall, red if down
            color = "#2e7d32" if prices.iloc[-1] > prices.iloc[0] else "#d32f2f"
            ax.plot(dates, prices, color=color, linewidth=1.5, label="Price")
            ax.fill_between(dates, prices, prices.min() * 0.98, alpha=0.08, color=color)

            # Moving average overlay
            ma_period = cfg["ma"]
            if len(grp) >= ma_period:
                ma = prices.rolling(ma_period).mean()
                ax.plot(dates, ma, color="#ff9800", linewidth=1.0, alpha=0.8,
                        linestyle="--", label=f"{ma_period}-day MA")

            # Mark the 30-day-ago point on the 90d chart
            if cfg["key"] == "90d" and len(grp) > 22:
                ax.axvline(x=dates.iloc[-22], color="#999999", linestyle="--",
                           linewidth=0.7, alpha=0.6)

            ax.set_xlim(dates.iloc[0], dates.iloc[-1])
            ax.xaxis.set_major_formatter(mdates.DateFormatter(cfg["date_fmt"]))
            ax.xaxis.set_major_locator(cfg["locator"])
            ax.tick_params(axis="both", labelsize=7, length=2)
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            ax.spines["left"].set_linewidth(0.5)
            ax.spines["bottom"].set_linewidth(0.5)
            ax.set_ylabel("Price ($)", fontsize=7)
            ax.set_title(f"{ticker} — {cfg['title']}", fontsize=8, fontweight="bold", pad=4)
            ax.legend(fontsize=6, loc="upper left", framealpha=0.7)

            path = os.path.join(output_dir, f"{ticker}_{cfg['key']}_surge.png")
            fig.savefig(path, dpi=150, bbox_inches="tight", pad_inches=0.05)
            plt.close(fig)
            ticker_charts[cfg["key"]] = path

        chart_paths[ticker] = ticker_charts

    return chart_paths

def generate_pdf(top20_df, company_info, price_df, output_path="zz_surge_report.pdf"):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.colors import HexColor
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        PageBreak, HRFlowable, Image
    )
    from reportlab.lib import colors
    import os

    output_path = os.path.join(_SCRIPT_DIR, output_path)

    # Generate mini charts (90d, 1y, 2y)
    chart_paths = generate_mini_charts(price_df, top20_df["ticker"].tolist())

    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=0.75*inch,
        rightMargin=0.75*inch,
        topMargin=0.6*inch,
        bottomMargin=0.6*inch,
    )

    styles = getSampleStyleSheet()

    # Custom styles — using green/teal theme for surges
    title_style = ParagraphStyle(
        "ReportTitle", parent=styles["Title"],
        fontSize=22, spaceAfter=4, textColor=HexColor("#0a3d2e"),
        fontName="Helvetica-Bold",
    )
    subtitle_style = ParagraphStyle(
        "Subtitle", parent=styles["Normal"],
        fontSize=11, textColor=HexColor("#555555"),
        spaceAfter=20, fontName="Helvetica",
    )
    ticker_header_style = ParagraphStyle(
        "TickerHeader", parent=styles["Heading1"],
        fontSize=16, textColor=HexColor("#0a5c36"),
        spaceBefore=6, spaceAfter=2, fontName="Helvetica-Bold",
    )
    company_name_style = ParagraphStyle(
        "CompanyName", parent=styles["Normal"],
        fontSize=11, textColor=HexColor("#555555"),
        spaceAfter=8, fontName="Helvetica-Oblique",
    )
    section_label = ParagraphStyle(
        "SectionLabel", parent=styles["Normal"],
        fontSize=10, textColor=HexColor("#0a5c36"),
        spaceBefore=10, spaceAfter=4, fontName="Helvetica-Bold",
    )
    body_style = ParagraphStyle(
        "BodyText2", parent=styles["Normal"],
        fontSize=9.5, leading=13, textColor=HexColor("#333333"),
        spaceAfter=6, fontName="Helvetica",
    )
    small_style = ParagraphStyle(
        "SmallText", parent=styles["Normal"],
        fontSize=8.5, leading=11, textColor=HexColor("#666666"),
        fontName="Helvetica",
    )

    story = []

    # ── COVER / SUMMARY PAGE ──
    story.append(Spacer(1, 40))
    story.append(Paragraph("Stock Surge Report", title_style))
    story.append(Paragraph(
        f"Top {len(top20_df)} Biggest Recent Surges &mdash; Generated {top20_df['latest_date'].iloc[0].strftime('%B %d, %Y')}",
        subtitle_style
    ))
    story.append(HRFlowable(width="100%", thickness=1, color=HexColor("#0a5c36")))
    story.append(Spacer(1, 12))

    # Methodology blurb
    story.append(Paragraph("Methodology", section_label))
    story.append(Paragraph(
        "This report identifies stocks with the largest recent price surges using a composite score "
        "that blends four metrics: (1) rally from the trailing 30-day low, (2) 30-day simple return, "
        "(3) z-score of that return relative to the stock's own historical volatility, and "
        "(4) percentage above the 60-day moving average. "
        "<br/><br/>"
        "<b>Extreme-Runner Filter:</b> Stocks that have been in extreme multi-year uptrends "
        "(both 1-year and 1.5-year returns above +100%) are excluded to keep the focus on "
        "recent breakout surges rather than stocks that have simply been climbing for years. "
        "A higher composite score indicates a stronger, more statistically unusual surge. "
        "This is intended as a screening tool &mdash; further fundamental and technical analysis "
        "is recommended before making investment decisions.",
        body_style
    ))
    story.append(Spacer(1, 14))

    # Summary table
    story.append(Paragraph("Summary Table", section_label))
    summary_data = [["#", "Ticker", "Price", "30d Ret", "Rally", "1Y Ret", "1.5Y Ret", "Score"]]
    for i, row in top20_df.iterrows():
        r1y = f"{row['return_1y_pct']:.1f}%" if pd.notna(row.get('return_1y_pct')) else "N/A"
        r1_5y = f"{row['return_1_5y_pct']:.1f}%" if pd.notna(row.get('return_1_5y_pct')) else "N/A"
        summary_data.append([
            str(i + 1),
            row["ticker"],
            f"${row['current_price']:.2f}",
            f"+{row['return_30d_pct']:.1f}%" if row['return_30d_pct'] > 0 else f"{row['return_30d_pct']:.1f}%",
            f"+{row['rally_from_low_pct']:.1f}%",
            r1y,
            r1_5y,
            f"{row['composite_surge_score']:.2f}",
        ])

    t = Table(summary_data, colWidths=[24, 48, 68, 62, 70, 62, 62, 52])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#0a5c36")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor("#f0f8f0"), colors.white]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(t)
    story.append(PageBreak())

    # ── INDIVIDUAL TICKER PAGES ──
    for idx, row in top20_df.iterrows():
        ticker = row["ticker"]
        info = company_info.get(ticker, {})

        # Header
        story.append(Paragraph(
            f"#{idx+1} &mdash; {ticker}",
            ticker_header_style
        ))
        story.append(Paragraph(
            f"{info.get('name', ticker)}  |  {info.get('sector', 'N/A')}  |  {info.get('industry', 'N/A')}",
            company_name_style
        ))
        story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#cccccc")))
        story.append(Spacer(1, 8))

        # Key metrics table
        pe_display = f"{info['pe_ratio']:.1f}" if info.get("pe_ratio") else "N/A"
        fwd_pe_display = f"{info['forward_pe']:.1f}" if info.get("forward_pe") else "N/A"
        w52h = f"${info['52w_high']:.2f}" if info.get("52w_high") else "N/A"
        w52l = f"${info['52w_low']:.2f}" if info.get("52w_low") else "N/A"
        r1y_display = f"{row['return_1y_pct']:.1f}%" if pd.notna(row.get('return_1y_pct')) else "N/A"
        r1_5y_display = f"{row['return_1_5y_pct']:.1f}%" if pd.notna(row.get('return_1_5y_pct')) else "N/A"

        metrics_data = [
            ["Current Price", "30-Day Return", "Rally (from 30d Low)", "Surge Score"],
            [f"${row['current_price']:.2f}",
             f"+{row['return_30d_pct']:.1f}%" if row['return_30d_pct'] > 0 else f"{row['return_30d_pct']:.1f}%",
             f"+{row['rally_from_low_pct']:.1f}%", f"{row['composite_surge_score']:.2f}"],
            ["1-Year Return", "1.5-Year Return", "Z-Score", "% Above 60d MA"],
            [r1y_display, r1_5y_display, f"{row['z_score']:.2f}", f"+{row['pct_above_ma60']:.1f}%"],
            ["Market Cap", "P/E Ratio (TTM)", "Forward P/E", "Avg Volume"],
            [format_large_number(info.get("market_cap")), pe_display,
             fwd_pe_display, format_volume(info.get("avg_volume"))],
            ["52-Week High", "52-Week Low", "", ""],
            [w52h, w52l, "", ""],
        ]

        mt = Table(metrics_data, colWidths=[120, 120, 120, 120])
        mt.setStyle(TableStyle([
            # Header rows (rows 0, 2, 4, 6)
            ("BACKGROUND", (0, 0), (-1, 0), HexColor("#e0f2e9")),
            ("BACKGROUND", (0, 2), (-1, 2), HexColor("#e0f2e9")),
            ("BACKGROUND", (0, 4), (-1, 4), HexColor("#e0f2e9")),
            ("BACKGROUND", (0, 6), (-1, 6), HexColor("#e0f2e9")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
            ("FONTNAME", (0, 4), (-1, 4), "Helvetica-Bold"),
            ("FONTNAME", (0, 6), (-1, 6), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#dddddd")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(mt)
        story.append(Spacer(1, 8))

        # Price charts — 90-day, 1-year, 2-year
        ticker_charts = chart_paths.get(ticker, {})
        for chart_key in ["90d", "1y", "2y"]:
            chart_path = ticker_charts.get(chart_key)
            if chart_path and os.path.exists(chart_path):
                img = Image(chart_path, width=5.2*inch, height=1.7*inch)
                story.append(img)
                story.append(Spacer(1, 4))

        # Company description
        story.append(Paragraph("About the Company", section_label))
        desc = info.get("description", "No description available.")
        # Truncate very long descriptions
        if len(desc) > 800:
            desc = desc[:797] + "..."
        story.append(Paragraph(desc, body_style))

        story.append(Spacer(1, 6))
        story.append(Paragraph(
            "<i>This is a screening report only. Please conduct your own due diligence before investing.</i>",
            small_style
        ))

        # Page break between tickers (except the last one)
        if idx < len(top20_df) - 1:
            story.append(PageBreak())

    # Build
    doc.build(story)
    print(f"\nPDF report saved to: {output_path}")

# ── MAIN ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  STOCK SURGE ANALYZER")
    print("  (with Extreme-Runner Filter)")
    print("=" * 60)

    # Step 1: Load data
    print("\n[1/5] Loading stock_prices.csv...")
    df = load_data()
    print(f"  Loaded {len(df):,} rows, {df['ticker'].nunique()} tickers")
    print(f"  Date range: {df['date'].min().date()} to {df['date'].max().date()}")

    # Step 2: Analyze surges
    print("\n[2/5] Analyzing surges (composite scoring + long-term returns)...")
    results = analyze_surges(df, lookback=22)
    print(f"  Analyzed {len(results)} tickers")

    # Step 3: Filter out extreme runners
    print("\n[3/5] Filtering out extreme multi-year runners...")
    top20 = filter_extreme_runners(results, top_n=20)

    print(f"\n  Top {len(top20)} surges (excluding extreme runners):")
    for i, row in top20.iterrows():
        r1y = f"{row['return_1y_pct']:>7.1f}%" if pd.notna(row['return_1y_pct']) else "    N/A"
        r1_5y = f"{row['return_1_5y_pct']:>7.1f}%" if pd.notna(row['return_1_5y_pct']) else "    N/A"
        print(f"    {i+1:>2}. {row['ticker']:<6} | 30d: +{row['return_30d_pct']:>7.1f}% | "
              f"1Y: {r1y} | 1.5Y: {r1_5y} | score: {row['composite_surge_score']:.2f}")

    # Step 4: Fetch company info
    print("\n[4/5] Fetching company info from Yahoo Finance...")
    ticker_list = top20["ticker"].tolist()
    company_info = fetch_company_info(ticker_list)
    print(f"  Fetched info for {len(company_info)} companies")

    # Step 5: Generate PDF
    print("\n[5/5] Generating PDF report (with 90-day, 1-year, and 2-year charts)...")
    output_path = "zz_surge_report.pdf"
    generate_pdf(top20, company_info, df, output_path)

    print("\n" + "=" * 60)
    print("  DONE!")
    print("=" * 60)
