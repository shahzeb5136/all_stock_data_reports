#!/usr/bin/env python3
"""
Stable Growth Stock Analyzer
=============================
Reads a CSV with columns (ticker, date, price), finds stocks with the
smoothest upward trajectories, and generates a professional PDF report
of the top 20 ranked by a composite Stability Score.

Usage:
    python stable_growth_report.py                         # auto-find CSV
    python stable_growth_report.py /path/to/stock_prices.csv
"""

import pandas as pd
import numpy as np
from scipy import stats
from datetime import datetime, timedelta
import warnings
import os
import sys

warnings.filterwarnings("ignore")

# ──────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────────────────────────────

BENCHMARK_CANDIDATES = ["^GSPC", "SPY"]

PERIODS = {
    "3Y": 3 * 252,
    "2Y": 2 * 252,
    "1Y": 252,
    "6M": 126,
}

TOP_N = 20


# ──────────────────────────────────────────────────────────────────────
# DATA LOADING
# ──────────────────────────────────────────────────────────────────────

def _quarantined_tickers(csv_path):
    """
    Tickers flagged by the downloader as sitting on a stale split adjustment.

    Imported defensively, and with the repo root pushed onto sys.path, so a
    direct `python reports/stable_growth_report.py` still runs even though only
    reports/ is on the path then.
    """
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    try:
        from split_guard import load_quarantine
        return load_quarantine(csv_path)
    except Exception:
        return set()


def load_csv(filepath):
    print(f"📥 Loading data from {filepath}...")
    with open(filepath, "r") as f:
        first_line = f.readline()
    sep = "\t" if "\t" in first_line else ","

    df = pd.read_csv(filepath, sep=sep)
    df.columns = [c.strip().lower() for c in df.columns]
    # Support both old 'price' column and new OHLCV 'close' column
    if "price" not in df.columns and "close" in df.columns:
        df = df.rename(columns={"close": "price"})
    assert {"ticker", "date", "price"}.issubset(df.columns), \
        f"CSV must have columns: ticker, date, price (or close). Found: {list(df.columns)}"

    df["date"] = pd.to_datetime(df["date"], format="mixed", dayfirst=False)
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df = df.dropna(subset=["price"])

    prices = df.pivot_table(index="date", columns="ticker", values="price", aggfunc="last")
    prices = prices.sort_index().ffill()

    # Drop anything the downloader could not lift off a stale split adjustment.
    # Here the damage is a silent false negative rather than a bad pick: one
    # synthetic -50% day wrecks the volatility, Sharpe and drawdown terms, so a
    # genuinely stable compounder would simply vanish from the ranking.
    quarantined = _quarantined_tickers(filepath) & set(prices.columns)
    if quarantined:
        print(f"[!] Excluding {len(quarantined)} ticker(s) with a stale split "
              f"adjustment: {', '.join(sorted(quarantined))}")
        prices = prices.drop(columns=sorted(quarantined))

    print(f"✅ Loaded {prices.shape[1]} tickers, {prices.shape[0]} trading days")
    print(f"   Date range: {prices.index[0].strftime('%Y-%m-%d')} → {prices.index[-1].strftime('%Y-%m-%d')}")
    return prices


def find_benchmark(prices):
    for c in BENCHMARK_CANDIDATES:
        if c in prices.columns:
            print(f"📌 Benchmark found: {c}")
            return c
    print("⚠️  No S&P 500 benchmark (^GSPC or SPY) found in data.")
    print("   Report will show absolute metrics without market comparison.")
    return None


# ──────────────────────────────────────────────────────────────────────
# YAHOO FINANCE FUNDAMENTALS (optional)
# ──────────────────────────────────────────────────────────────────────

def fetch_fundamentals(ticker):
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.info
        return {
            "sector": info.get("sector", "N/A"),
            "industry": info.get("industry", "N/A"),
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "peg_ratio": info.get("pegRatio"),
            "dividend_yield": info.get("dividendYield"),
            "profit_margin": info.get("profitMargins"),
            "roe": info.get("returnOnEquity"),
            "revenue_growth": info.get("revenueGrowth"),
            "earnings_growth": info.get("earningsGrowth"),
            "debt_to_equity": info.get("debtToEquity"),
            "current_ratio": info.get("currentRatio"),
            "name": info.get("shortName", ticker),
            "52w_high": info.get("fiftyTwoWeekHigh"),
            "52w_low": info.get("fiftyTwoWeekLow"),
            "current_price": info.get("currentPrice", info.get("regularMarketPrice")),
        }
    except Exception:
        return {"sector": "N/A", "industry": "N/A", "name": ticker,
                "market_cap": None, "pe_ratio": None, "forward_pe": None,
                "peg_ratio": None, "dividend_yield": None, "profit_margin": None,
                "roe": None, "revenue_growth": None, "earnings_growth": None,
                "debt_to_equity": None, "current_ratio": None,
                "52w_high": None, "52w_low": None, "current_price": None}


# ──────────────────────────────────────────────────────────────────────
# CORE ANALYSIS
# ──────────────────────────────────────────────────────────────────────

def compute_metrics(stock_series, bench_series, period_label, n_days):
    end_idx = len(stock_series)
    start_idx = max(0, end_idx - n_days)

    stock = stock_series.iloc[start_idx:end_idx].dropna()
    if len(stock) < 60:
        return None

    if bench_series is not None:
        bench = bench_series.iloc[start_idx:end_idx].dropna()
        common = stock.index.intersection(bench.index)
        if len(common) < 60:
            return None
        stock = stock.loc[common]
        bench = bench.loc[common]
    else:
        bench = None

    trading_days = len(stock)
    years = trading_days / 252

    stock_total_ret = (stock.iloc[-1] / stock.iloc[0]) - 1
    stock_ann_ret = (1 + stock_total_ret) ** (1 / max(years, 0.01)) - 1

    bench_total_ret = 0.0
    bench_ann_ret = 0.0
    if bench is not None:
        bench_total_ret = (bench.iloc[-1] / bench.iloc[0]) - 1
        bench_ann_ret = (1 + bench_total_ret) ** (1 / max(years, 0.01)) - 1

    daily_ret = stock.pct_change().dropna()
    if len(daily_ret) < 30:
        return None

    # R-squared
    log_p = np.log(stock.values)
    x = np.arange(len(log_p))
    slope, intercept, r_val, p_val, std_err = stats.linregress(x, log_p)
    r_squared = r_val ** 2

    # Volatility
    ann_vol = daily_ret.std() * np.sqrt(252)
    monthly = stock.resample("ME").last().dropna()
    monthly_ret = monthly.pct_change().dropna()
    cv_monthly = abs(monthly_ret.std() / monthly_ret.mean()) if monthly_ret.mean() != 0 else 999
    cv_monthly = min(cv_monthly, 999)

    # Max Drawdown
    cummax = stock.cummax()
    drawdown = (stock - cummax) / cummax
    max_dd = drawdown.min()

    # Sharpe (rf = 4.5%)
    rf_daily = 0.045 / 252
    excess = daily_ret - rf_daily
    sharpe = (excess.mean() / excess.std()) * np.sqrt(252) if excess.std() > 0 else 0

    # Sortino
    down = excess[excess < 0]
    down_std = down.std() * np.sqrt(252) if len(down) > 0 else 1
    sortino = (stock_ann_ret - 0.045) / down_std if down_std > 0 else 0

    # Beta & Alpha
    beta = np.nan
    alpha = np.nan
    if bench is not None:
        bench_daily_ret = bench.pct_change().dropna()
        common_r = daily_ret.index.intersection(bench_daily_ret.index)
        if len(common_r) > 30:
            sr = daily_ret.loc[common_r].values
            br = bench_daily_ret.loc[common_r].values
            cov = np.cov(sr, br)
            if cov[1, 1] > 0:
                beta = cov[0, 1] / cov[1, 1]
                alpha = stock_ann_ret - (0.045 + beta * (bench_ann_ret - 0.045))

    ulcer = np.sqrt((drawdown ** 2).mean())
    calmar = stock_ann_ret / abs(max_dd) if max_dd != 0 else 0

    return {
        "period": period_label,
        "total_return": stock_total_ret,
        "ann_return": stock_ann_ret,
        "bench_total_return": bench_total_ret,
        "bench_ann_return": bench_ann_ret,
        "excess_return": stock_total_ret - bench_total_ret,
        "r_squared": r_squared,
        "ann_volatility": ann_vol,
        "cv_monthly": cv_monthly,
        "max_drawdown": max_dd,
        "sharpe": sharpe,
        "sortino": sortino,
        "beta": beta,
        "alpha": alpha,
        "ulcer_index": ulcer,
        "calmar": calmar,
    }


def compute_stability_score(metrics_by_period):
    primary = None
    for p in ["3Y", "2Y", "1Y", "6M"]:
        if p in metrics_by_period:
            primary = metrics_by_period[p]
            break
    if primary is None:
        return -999
    if primary["ann_return"] <= 0:
        return -999

    r2   = primary["r_squared"]
    ret  = min(primary["ann_return"] / 0.50, 1.0)
    vol  = max(0, 1 - primary["ann_volatility"] / 0.60)
    dd   = max(0, 1 - abs(primary["max_drawdown"]) / 0.50)
    shp  = min(max(primary["sharpe"], 0) / 3.0, 1.0)

    pos = sum(1 for p in PERIODS if p in metrics_by_period and metrics_by_period[p]["total_return"] > 0)
    tot = sum(1 for p in PERIODS if p in metrics_by_period)
    cons = pos / tot if tot > 0 else 0

    return 0.35*r2 + 0.20*ret + 0.15*vol + 0.15*dd + 0.10*shp + 0.05*cons


def analyze_all(prices, benchmark_col):
    bench = prices[benchmark_col] if benchmark_col else None
    tickers = [c for c in prices.columns if c != benchmark_col]
    results = []

    total = len(tickers)
    for i, ticker in enumerate(tickers):
        s = prices[ticker].dropna()
        if len(s) < 126:
            continue

        metrics_by_period = {}
        for label, n_days in PERIODS.items():
            m = compute_metrics(s, bench, label, n_days)
            if m is not None:
                metrics_by_period[label] = m

        if not metrics_by_period:
            continue

        score = compute_stability_score(metrics_by_period)
        results.append({"ticker": ticker, "stability_score": score, "metrics": metrics_by_period})

        if (i + 1) % 50 == 0:
            print(f"   Analyzed {i+1}/{total}...")

    results.sort(key=lambda x: x["stability_score"], reverse=True)
    qualified = [r for r in results if r["stability_score"] > 0]
    print(f"✅ Analysis complete. {len(qualified)}/{total} stocks have positive stable growth.")
    return qualified


# ──────────────────────────────────────────────────────────────────────
# CHARTS
# ──────────────────────────────────────────────────────────────────────

def generate_charts(top_results, prices, benchmark_col):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.dates import DateFormatter

    chart_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "charts")
    os.makedirs(chart_dir, exist_ok=True)

    bench = prices[benchmark_col] if benchmark_col else None
    end_date = prices.index[-1]
    start_3y = end_date - timedelta(days=3*365)

    # ── Overview ──
    fig, ax = plt.subplots(figsize=(12, 6))
    if bench is not None:
        bp = bench.loc[bench.index >= start_3y].dropna()
        if len(bp) > 1:
            bn = bp / bp.iloc[0] * 100
            ax.plot(bn.index, bn.values, color="#888", linewidth=2.5,
                    label="S&P 500", linestyle="--", zorder=5)

    colors = ["#1a73e8","#e8710a","#0d652d","#c5221f","#9334e6",
              "#185abc","#e37400","#137333","#a50e0e","#7627bb"]
    for i, r in enumerate(top_results[:10]):
        tk = r["ticker"]
        s = prices[tk].loc[prices[tk].index >= start_3y].dropna()
        if len(s) < 10: continue
        sn = s / s.iloc[0] * 100
        ax.plot(sn.index, sn.values, color=colors[i%10], linewidth=1.3, label=tk, alpha=0.85)

    ax.set_title("Top 10 Stable Growers vs S&P 500 (3-Year, Normalized to 100)",
                 fontsize=14, fontweight="bold", pad=12)
    ax.set_ylabel("Normalized Price (Start = 100)")
    ax.legend(loc="upper left", fontsize=8, ncol=2, framealpha=0.9)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(DateFormatter("%b %Y"))
    fig.autofmt_xdate(); fig.tight_layout()
    overview_path = os.path.join(chart_dir, "overview.png")
    fig.savefig(overview_path, dpi=160, bbox_inches="tight"); plt.close(fig)

    # ── Individual ──
    individual_paths = []
    for r in top_results:
        tk = r["ticker"]
        s = prices[tk].loc[prices[tk].index >= start_3y].dropna()
        if len(s) < 10:
            individual_paths.append(None); continue

        fig, ax1 = plt.subplots(figsize=(6.5, 2.8))
        sn = s / s.iloc[0] * 100
        ax1.plot(sn.index, sn.values, color="#1a73e8", linewidth=1.8, label=tk)

        if bench is not None:
            bp = bench.loc[bench.index >= start_3y].dropna()
            common = sn.index.intersection(bp.index)
            if len(common) > 1:
                bn = bp.loc[common] / bp.loc[common].iloc[0] * 100
                sn_a = sn.loc[common]
                ax1.plot(bn.index, bn.values, color="#aaa", linewidth=1.0, label="S&P 500", linestyle="--")
                ax1.fill_between(bn.index, sn_a.values, bn.values,
                                 where=(sn_a.values >= bn.values), color="#1a73e8", alpha=0.06)

        best_m = None
        for p in ["3Y","2Y","1Y","6M"]:
            if p in r["metrics"]:
                best_m = r["metrics"][p]; plbl = p; break
        if best_m:
            ax1.text(0.02, 0.95,
                     f"R\u00b2={best_m['r_squared']:.3f}   {plbl} Return: {best_m['total_return']*100:+.1f}%",
                     transform=ax1.transAxes, fontsize=7.5, verticalalignment='top',
                     bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.85, edgecolor='#ddd'))

        ax1.set_title(f"{tk} vs S&P 500 (Normalized)", fontsize=10, fontweight="bold")
        ax1.legend(fontsize=7, loc="lower right")
        ax1.grid(True, alpha=0.2)
        ax1.xaxis.set_major_formatter(DateFormatter("%b '%y"))
        fig.autofmt_xdate(); fig.tight_layout()
        path = os.path.join(chart_dir, f"{tk.replace('-','_').replace('^','')}.png")
        fig.savefig(path, dpi=140, bbox_inches="tight"); plt.close(fig)
        individual_paths.append(path)

    return overview_path, individual_paths


# ──────────────────────────────────────────────────────────────────────
# PDF REPORT
# ──────────────────────────────────────────────────────────────────────

def generate_pdf(top_results, overview_chart, individual_charts, has_benchmark, output_path):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib.colors import HexColor, white
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak
    )

    W, H = letter
    doc = SimpleDocTemplate(output_path, pagesize=letter,
        leftMargin=0.55*inch, rightMargin=0.55*inch,
        topMargin=0.55*inch, bottomMargin=0.55*inch)

    styles = getSampleStyleSheet()
    title_s = ParagraphStyle("T", parent=styles["Title"], fontSize=24, spaceAfter=4,
                             textColor=HexColor("#0d1b2a"), fontName="Helvetica-Bold")
    sub_s = ParagraphStyle("Sub", parent=styles["Normal"], fontSize=11,
                           textColor=HexColor("#555"), spaceAfter=18, leading=15)
    h2_s = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=15,
                          textColor=HexColor("#0d1b2a"), spaceBefore=14, spaceAfter=8,
                          fontName="Helvetica-Bold")
    h3_s = ParagraphStyle("H3", parent=styles["Heading3"], fontSize=11,
                          textColor=HexColor("#1b2838"), spaceBefore=10, spaceAfter=4,
                          fontName="Helvetica-Bold")
    body_s = ParagraphStyle("B", parent=styles["Normal"], fontSize=9, leading=13,
                            textColor=HexColor("#333"))
    small_s = ParagraphStyle("Sm", parent=styles["Normal"], fontSize=7.5, leading=10,
                             textColor=HexColor("#666"))

    story = []

    # ═══ COVER ═══
    story.append(Spacer(1, 1.2*inch))
    story.append(Paragraph("Stable Growth Stock Report", title_s))
    story.append(Spacer(1, 0.1*inch))

    periods_available = set()
    for r in top_results:
        periods_available.update(r["metrics"].keys())
    period_str = ", ".join(sorted(periods_available, key=lambda x: {"3Y":0,"2Y":1,"1Y":2,"6M":3}.get(x,9)))

    story.append(Paragraph(
        f"Top {len(top_results)} Stocks Ranked by Stability &amp; Consistent Growth<br/>"
        f"Report Date: {datetime.today().strftime('%B %d, %Y')}<br/>"
        f"Analysis Periods: {period_str}", sub_s))

    story.append(Paragraph("Methodology", h2_s))
    story.append(Paragraph(
        "This report identifies stocks with the smoothest, most consistent upward price "
        "trajectories. The <b>Stability Score</b> is a weighted composite: "
        "<b>R-squared</b> (35%) — linearity of log-price growth, "
        "<b>Annualized Return</b> (20%), "
        "<b>Low Volatility</b> (15%), "
        "<b>Small Max Drawdown</b> (15%), "
        "<b>Sharpe Ratio</b> (10%), "
        "<b>Cross-Period Consistency</b> (5%). "
        "Only stocks with positive growth over the longest available period qualify."
        + (" All returns are compared against the S&amp;P 500." if has_benchmark else ""), body_s))
    story.append(Spacer(1, 0.12*inch))

    story.append(Paragraph("Key Metrics", h2_s))
    for label, desc in [
        ("R-squared (R<super>2</super>)", "How closely price follows a smooth exponential curve (1.0 = perfectly linear log-growth)."),
        ("Annualized Volatility", "Std dev of daily returns, annualized. Lower = smoother ride."),
        ("Max Drawdown", "Largest peak-to-trough decline. Closer to 0% = less painful."),
        ("Sharpe Ratio", "Risk-adjusted return (excess return / volatility). Higher = better."),
        ("Sortino Ratio", "Like Sharpe but penalizes only downside moves. Higher = better."),
        ("Ulcer Index", "Depth + duration of drawdowns combined. Lower = less pain."),
        ("Calmar Ratio", "Annualized return / max drawdown. Higher = better risk/reward."),
        ("Beta", "Sensitivity to S&amp;P 500. Below 1 = less volatile than market."),
        ("Alpha", "Return beyond what beta-adjusted market exposure would explain."),
    ]:
        story.append(Paragraph(f"<b>{label}</b> — {desc}", small_s))
        story.append(Spacer(1, 2))

    # ═══ OVERVIEW CHART ═══
    story.append(PageBreak())
    story.append(Paragraph("Performance Overview", h2_s))
    if overview_chart and os.path.exists(overview_chart):
        story.append(Image(overview_chart, width=7.0*inch, height=3.5*inch))
    story.append(Spacer(1, 0.2*inch))

    # ═══ SUMMARY TABLE ═══
    story.append(Paragraph(f"Rankings — Top {len(top_results)} Stable Growth Stocks", h2_s))

    def best(r):
        for p in ["3Y","2Y","1Y","6M"]:
            if p in r["metrics"]: return r["metrics"][p], p
        return None, None

    if has_benchmark:
        hdr = ["#","Ticker","Company","Sector","Score","Return","S&P","Excess",
               "R<super>2</super>","Vol","MaxDD","Sharpe"]
    else:
        hdr = ["#","Ticker","Company","Sector","Score","Return","Period",
               "R<super>2</super>","Vol","MaxDD","Sharpe"]

    tdata = [hdr]
    for i, r in enumerate(top_results):
        m, plbl = best(r)
        if m is None: continue
        f = r.get("fundamentals", {})
        name = f.get("name", r["ticker"])[:20]
        sector = f.get("sector", "N/A")[:13]
        excess = m["total_return"] - m["bench_total_return"]
        if has_benchmark:
            tdata.append([str(i+1), r["ticker"], name, sector,
                f"{r['stability_score']:.3f}", f"{m['total_return']*100:+.1f}%",
                f"{m['bench_total_return']*100:+.1f}%", f"{excess*100:+.1f}%",
                f"{m['r_squared']:.3f}", f"{m['ann_volatility']*100:.1f}%",
                f"{m['max_drawdown']*100:.1f}%", f"{m['sharpe']:.2f}"])
        else:
            tdata.append([str(i+1), r["ticker"], name, sector,
                f"{r['stability_score']:.3f}", f"{m['total_return']*100:+.1f}%", plbl,
                f"{m['r_squared']:.3f}", f"{m['ann_volatility']*100:.1f}%",
                f"{m['max_drawdown']*100:.1f}%", f"{m['sharpe']:.2f}"])

    for ci, cell in enumerate(tdata[0]):
        if "<super>" in str(cell):
            tdata[0][ci] = Paragraph(cell, ParagraphStyle("hc", fontSize=7,
                                     fontName="Helvetica-Bold", textColor=white))

    if has_benchmark:
        cw = [0.25*inch,0.5*inch,1.25*inch,0.82*inch,0.45*inch,
              0.55*inch,0.5*inch,0.55*inch,0.45*inch,0.42*inch,0.5*inch,0.5*inch]
    else:
        cw = [0.25*inch,0.55*inch,1.4*inch,0.9*inch,0.5*inch,
              0.6*inch,0.45*inch,0.5*inch,0.5*inch,0.55*inch,0.55*inch]

    t = Table(tdata, colWidths=cw, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),HexColor("#0d1b2a")),
        ("TEXTCOLOR",(0,0),(-1,0),white),
        ("FONTSIZE",(0,0),(-1,0),7), ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("FONTSIZE",(0,1),(-1,-1),6.8), ("FONTNAME",(0,1),(-1,-1),"Helvetica"),
        ("ALIGN",(0,0),(0,-1),"CENTER"), ("ALIGN",(4,0),(-1,-1),"CENTER"),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[white,HexColor("#f4f6f9")]),
        ("GRID",(0,0),(-1,-1),0.4,HexColor("#d0d5dd")),
        ("TOPPADDING",(0,0),(-1,-1),3), ("BOTTOMPADDING",(0,0),(-1,-1),3),
        ("LEFTPADDING",(0,0),(-1,-1),3), ("RIGHTPADDING",(0,0),(-1,-1),3),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ]))
    story.append(t)

    # ═══ INDIVIDUAL PAGES ═══
    for idx, r in enumerate(top_results):
        story.append(PageBreak())
        tk = r["ticker"]
        f = r.get("fundamentals", {})
        name = f.get("name", tk)
        sector = f.get("sector", "N/A")
        industry = f.get("industry", "N/A")

        story.append(Paragraph(
            f"<font color='#1a73e8'>#{idx+1}</font> &nbsp; <b>{tk}</b> — {name}",
            ParagraphStyle("ST", parent=h2_s, fontSize=16, spaceAfter=2)))
        story.append(Paragraph(f"{sector} &bull; {industry}", small_s))
        story.append(Spacer(1, 0.08*inch))

        cp = individual_charts[idx] if idx < len(individual_charts) else None
        if cp and os.path.exists(cp):
            story.append(Image(cp, width=5.8*inch, height=2.5*inch))
            story.append(Spacer(1, 0.08*inch))

        # Performance table
        story.append(Paragraph("Performance Across Periods" + (" vs S&amp;P 500" if has_benchmark else ""), h3_s))
        if has_benchmark:
            phdr = ["Period","Stock Return","S&P 500","Excess","Ann. Vol","Max DD","Sharpe","Sortino"]
        else:
            phdr = ["Period","Total Return","Ann. Return","Ann. Vol","Max DD","Sharpe","Sortino"]
        pdata = [phdr]
        for p in ["3Y","2Y","1Y","6M"]:
            m = r["metrics"].get(p)
            if m is None: continue
            if has_benchmark:
                pdata.append([p, f"{m['total_return']*100:+.1f}%",
                    f"{m['bench_total_return']*100:+.1f}%", f"{m['excess_return']*100:+.1f}%",
                    f"{m['ann_volatility']*100:.1f}%", f"{m['max_drawdown']*100:.1f}%",
                    f"{m['sharpe']:.2f}", f"{m['sortino']:.2f}"])
            else:
                pdata.append([p, f"{m['total_return']*100:+.1f}%",
                    f"{m['ann_return']*100:.1f}%", f"{m['ann_volatility']*100:.1f}%",
                    f"{m['max_drawdown']*100:.1f}%", f"{m['sharpe']:.2f}", f"{m['sortino']:.2f}"])

        if has_benchmark:
            pw = [0.45*inch,0.8*inch,0.7*inch,0.65*inch,0.7*inch,0.65*inch,0.6*inch,0.6*inch]
        else:
            pw = [0.45*inch,0.8*inch,0.8*inch,0.7*inch,0.7*inch,0.65*inch,0.65*inch]
        pt = Table(pdata, colWidths=pw, repeatRows=1)
        pt.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),HexColor("#1b4965")),
            ("TEXTCOLOR",(0,0),(-1,0),white),
            ("FONTSIZE",(0,0),(-1,-1),7.5), ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
            ("ALIGN",(1,0),(-1,-1),"CENTER"),
            ("GRID",(0,0),(-1,-1),0.3,HexColor("#d0d5dd")),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[white,HexColor("#f4f6f9")]),
            ("TOPPADDING",(0,0),(-1,-1),3), ("BOTTOMPADDING",(0,0),(-1,-1),3),
        ]))
        story.append(pt)
        story.append(Spacer(1, 0.12*inch))

        # Risk metrics
        m_best, _ = best(r)
        story.append(Paragraph("Stability &amp; Risk Metrics", h3_s))

        def fmt(val, pct=False):
            if val is None or (isinstance(val, float) and np.isnan(val)): return "N/A"
            return f"{val*100:.2f}%" if pct else f"{val:.4f}"

        rdata = [
            ["Metric","Value","Metric","Value"],
            ["Stability Score", f"{r['stability_score']:.4f}", "R-squared", fmt(m_best["r_squared"])],
            ["Beta", fmt(m_best["beta"]), "Alpha (ann.)", fmt(m_best["alpha"], pct=True)],
            ["Ulcer Index", fmt(m_best["ulcer_index"]), "Calmar Ratio", fmt(m_best["calmar"])],
            ["CV Monthly Ret", fmt(m_best["cv_monthly"]), "Ann. Return", fmt(m_best["ann_return"], pct=True)],
        ]
        rw = [1.15*inch, 0.95*inch, 1.15*inch, 0.95*inch]
        rt = Table(rdata, colWidths=rw, repeatRows=1)
        rt.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),HexColor("#2c3e50")),
            ("TEXTCOLOR",(0,0),(-1,0),white),
            ("FONTSIZE",(0,0),(-1,-1),7.5),
            ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
            ("FONTNAME",(0,1),(0,-1),"Helvetica-Bold"),
            ("FONTNAME",(2,1),(2,-1),"Helvetica-Bold"),
            ("GRID",(0,0),(-1,-1),0.3,HexColor("#d0d5dd")),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[white,HexColor("#f4f6f9")]),
            ("TOPPADDING",(0,0),(-1,-1),3), ("BOTTOMPADDING",(0,0),(-1,-1),3),
        ]))
        story.append(rt)
        story.append(Spacer(1, 0.12*inch))

        # Fundamentals
        story.append(Paragraph("Fundamentals (Yahoo Finance)", h3_s))
        def fmtf(val, pct=False, dollar=False, ratio=False):
            if val is None: return "N/A"
            if dollar:
                if val >= 1e12: return f"${val/1e12:.2f}T"
                if val >= 1e9:  return f"${val/1e9:.1f}B"
                if val >= 1e6:  return f"${val/1e6:.0f}M"
                return f"${val:,.0f}"
            if pct: return f"{val*100:.1f}%"
            if ratio: return f"{val:.2f}"
            return str(val)

        fdata = [
            ["Metric","Value","Metric","Value"],
            ["Market Cap", fmtf(f.get("market_cap"),dollar=True), "P/E Ratio", fmtf(f.get("pe_ratio"),ratio=True)],
            ["Forward P/E", fmtf(f.get("forward_pe"),ratio=True), "PEG Ratio", fmtf(f.get("peg_ratio"),ratio=True)],
            ["Div. Yield", fmtf(f.get("dividend_yield"),pct=True), "Profit Margin", fmtf(f.get("profit_margin"),pct=True)],
            ["ROE", fmtf(f.get("roe"),pct=True), "Revenue Growth", fmtf(f.get("revenue_growth"),pct=True)],
            ["Debt/Equity", fmtf(f.get("debt_to_equity"),ratio=True), "Current Ratio", fmtf(f.get("current_ratio"),ratio=True)],
        ]
        ft = Table(fdata, colWidths=rw, repeatRows=1)
        ft.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),HexColor("#1e7e34")),
            ("TEXTCOLOR",(0,0),(-1,0),white),
            ("FONTSIZE",(0,0),(-1,-1),7.5),
            ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
            ("FONTNAME",(0,1),(0,-1),"Helvetica-Bold"),
            ("FONTNAME",(2,1),(2,-1),"Helvetica-Bold"),
            ("GRID",(0,0),(-1,-1),0.3,HexColor("#d0d5dd")),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[white,HexColor("#f4f6f9")]),
            ("TOPPADDING",(0,0),(-1,-1),3), ("BOTTOMPADDING",(0,0),(-1,-1),3),
        ]))
        story.append(ft)

        hi = f.get("52w_high"); lo = f.get("52w_low"); cur = f.get("current_price")
        if hi and lo and cur:
            pct_hi = (cur - hi) / hi * 100
            story.append(Spacer(1, 0.06*inch))
            story.append(Paragraph(
                f"52-Week Range: ${lo:.2f} — ${hi:.2f} &nbsp;|&nbsp; "
                f"Current: ${cur:.2f} ({pct_hi:+.1f}% from 52w high)", small_s))

    # ═══ DISCLAIMER ═══
    story.append(PageBreak())
    story.append(Paragraph("Disclaimer", h2_s))
    story.append(Paragraph(
        "This report is for informational and educational purposes only. "
        "It does not constitute financial advice or a recommendation to buy or sell securities. "
        "Past performance does not guarantee future results. "
        "Always consult a qualified financial advisor before making investment decisions.", body_s))

    print(f"📄 Building PDF...")
    doc.build(story)
    print(f"✅ Report saved: {output_path}")


# ──────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) > 1:
        csv_path = sys.argv[1]
    else:
        _script_dir = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(_script_dir, "stock_prices.csv"),
            "stock_prices.csv",
        ]
        csv_path = None
        for c in candidates:
            if os.path.exists(c):
                csv_path = c; break
        if csv_path is None:
            upload_dir = "/mnt/user-data/uploads"
            if os.path.isdir(upload_dir):
                for f in os.listdir(upload_dir):
                    if f.lower().endswith((".csv", ".tsv", ".txt")):
                        csv_path = os.path.join(upload_dir, f); break
        if csv_path is None:
            print("❌ No CSV file found. Provide path as argument:")
            print("   python stable_growth_report.py /path/to/stock_prices.csv")
            sys.exit(1)

    print("=" * 60)
    print("  STABLE GROWTH STOCK ANALYZER")
    print("=" * 60)

    prices = load_csv(csv_path)
    benchmark_col = find_benchmark(prices)
    results = analyze_all(prices, benchmark_col)

    if not results:
        print("❌ No qualifying stocks found.")
        sys.exit(1)

    top = results[:TOP_N]
    print(f"\n🏆 Top {len(top)} Stable Growers:")
    for i, r in enumerate(top):
        mp = None
        for p in ["3Y","2Y","1Y","6M"]:
            if p in r["metrics"]: mp = r["metrics"][p]; break
        print(f"  {i+1:2d}. {r['ticker']:6s}  Score={r['stability_score']:.4f}  "
              f"R2={mp['r_squared']:.3f}  Ret={mp['total_return']*100:+.1f}%  "
              f"Vol={mp['ann_volatility']*100:.1f}%  DD={mp['max_drawdown']*100:.1f}%")

    # Fundamentals
    print(f"\n📊 Fetching fundamentals from Yahoo Finance...")
    yf_ok = False
    try:
        import yfinance; yf_ok = True
    except ImportError:
        print("   yfinance not available — fundamentals will show N/A.")

    for i, r in enumerate(top):
        tk = r["ticker"]
        r["fundamentals"] = fetch_fundamentals(tk) if yf_ok else \
            {"name": tk, "sector": "N/A", "industry": "N/A"}
        last_year = prices[tk].iloc[-252:].dropna()
        if len(last_year) > 0:
            r["fundamentals"]["52w_high"] = float(last_year.max())
            r["fundamentals"]["52w_low"] = float(last_year.min())
            r["fundamentals"]["current_price"] = float(last_year.iloc[-1])
        if yf_ok and (i+1) % 5 == 0:
            print(f"   Fetched {i+1}/{len(top)}...")

    print("\n📈 Generating charts...")
    overview_chart, individual_charts = generate_charts(top, prices, benchmark_col)

    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zz_stable_growth_report.pdf")
    generate_pdf(top, overview_chart, individual_charts,
                 benchmark_col is not None, output_path)
    return output_path


if __name__ == "__main__":
    main()
