"""
Configuration for the Stock Price Downloader.
Edit the variables below to customize behavior.
"""

import logging
import os

# ─────────────────────────────────────────────
# LOGGING SETUP
# ─────────────────────────────────────────────
LOG_LEVEL = logging.INFO
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# ─────────────────────────────────────────────
# HISTORICAL DATA START DATE
# ─────────────────────────────────────────────
# Fixed start date — all bulk downloads begin here.
# Yahoo Finance has data for most S&P 500 tickers back to at least 2000.
START_DATE = "2005-01-01"

# ─────────────────────────────────────────────
# COLUMNS TO STORE
# ─────────────────────────────────────────────
# yfinance returns Open, High, Low, Close, Volume with auto_adjust=True.
# All price columns are split- and dividend-adjusted (auto_adjust=True).
OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]

# ─────────────────────────────────────────────
# RATE LIMITING / EFFICIENCY SETTINGS
# ─────────────────────────────────────────────
# How many tickers to download in a single yfinance batch call.
BATCH_SIZE = 50

# Seconds to sleep between each batch to avoid throttling.
SLEEP_BETWEEN_BATCHES = 4  # seconds (for bulk downloads, 20 years of data)

# For incremental updates (much less data per call), we can be faster.
SLEEP_BETWEEN_BATCHES_UPDATE = 1  # seconds

# ─────────────────────────────────────────────
# RETRY / RESILIENCE SETTINGS
# ─────────────────────────────────────────────
# Max retry attempts per batch before breaking it into singles.
MAX_RETRIES = 3

# Base delay between retries (seconds). Actual delay = RETRY_DELAY * 2^attempt.
RETRY_DELAY = 10

# When a batch fails all retries, re-download each ticker individually
# in mini-batches of this size.
TICKER_FALLBACK_BATCH_SIZE = 5

# How many batches between intermediate CSV saves (crash protection).
# Set to 0 to disable intermediate saves (only save once at the end).
FLUSH_EVERY_N_BATCHES = 10

# ─────────────────────────────────────────────
# DATA VALIDATION THRESHOLDS
# ─────────────────────────────────────────────
# Minimum expected rows per ticker (flags tickers with suspiciously little data).
MIN_EXPECTED_ROWS_PER_TICKER = 100

# Max % of trading days that can be missing before a warning is raised.
MAX_MISSING_DAYS_PCT = 10

# ─────────────────────────────────────────────
# SPLIT-ADJUSTMENT GUARD
# ─────────────────────────────────────────────
# Incremental updates never refetch old rows, but Yahoo re-adjusts a ticker's
# whole history when it splits. Without this guard the CSV keeps two price
# scales stitched together at the split date, and the analysers read the seam
# as a real crash. See split_guard.py for how detection works.

# Run the guard automatically at the end of every smart_update().
AUTO_REPAIR_SPLITS = os.getenv("AUTO_REPAIR_SPLITS", "true").lower() != "false"

# How many recent bars per ticker the seam scan looks at. 1100 trading days
# (~4.4 years) comfortably covers the deepest report lookback, the 3-year
# stable-growth window. Older seams cannot change a published number, and
# verifying them would spend requests for nothing. Set to 0 to scan everything.
SPLIT_SCAN_LOOKBACK_ROWS = 1100

# How close a one-day jump must sit to a split ratio to be worth verifying.
# Generous on purpose: the seam day carries a real day of trading on top of
# the split, so the ratio is (1 + daily_return) / split_ratio, not the split
# ratio itself. False positives here cost one request; a false negative would
# leave a corrupted report.
SPLIT_SEAM_BAND = 0.12

# Stage 2 refetches the two bars either side of a seam and compares the fresh
# one-day ratio with the stored one. Same source, same adjustment basis, so a
# genuine move reproduces to within rounding; this is the slack allowed before
# calling the stored history stale. The smallest real split (3-for-2) shows up
# as a 33% disagreement, so there is a wide margin on either side.
SPLIT_VERIFY_TOLERANCE = 0.10

# Calendar days of padding either side of a seam when refetching it, so the
# two bars are still in range across weekends and holidays.
SPLIT_VERIFY_WINDOW_DAYS = 7

# Pause between per-ticker verification fetches, to stay under Yahoo's limits.
SPLIT_VERIFY_SLEEP = 0.4

# How long a "this seam is a genuine price move" verdict stays cached. Without
# an expiry, one bad API reply would suppress a real split forever.
SPLIT_CLEAN_CACHE_DAYS = 90

# Ceiling on automatic repairs per run. Each repair is a full re-download from
# START_DATE, so a detector gone wrong must not be able to trigger hundreds of
# them against a rate-limited host. Anything over the cap is quarantined
# instead: excluded from reports, and repaired on the next run.
MAX_AUTO_REPAIRS_PER_RUN = 25

# ─────────────────────────────────────────────
# OUTPUT PATHS
# ─────────────────────────────────────────────
# CSV data file. Defaults to the repo-relative path used by local runs; the
# hosted service overrides it with STOCK_CSV_PATH so downloads land on the
# Railway volume instead of inside the container image.
CSV_PATH = os.getenv("STOCK_CSV_PATH", "reports/stock_prices.csv")

# ─────────────────────────────────────────────
# TICKER LISTS — ORGANIZED BY CATEGORY
# ─────────────────────────────────────────────
# Add tickers to the appropriate category below.
# ALL_TICKERS (computed at the bottom) combines and deduplicates everything.

# ── S&P 500 / Individual Stocks ──────────────
STOCK_TICKERS = [
    "AAPL","ABBV","ABT","ACN","ADBE","ADI","ADM","ADP","ADSK","AEE",
    "AEP","AES","AFL","AIG","AIZ","AJG","AKAM","ALB","ALGN","ALL",
    "ALLE","AMAT","AMCR","AMD","AME","AMGN","AMP","AMT","AMZN","ANET",
    "ANSS","AON","AOS","APA","APD","APH","APTV","ARE","ATO","AVGO",
    "AVB","AVY","AWK","AXP","AZO","BA","BAC","BAX","BBWI","BBY",
    "BDX","BEN","BF-B","BG","BIIB","BIO","BK","BKNG","BKR","BLK",
    "BMY","BR","BRK-B","BRO","BSX","BWA","BXP","C","CAG","CAH",
    "CARR","CAT","CB","CBOE","CBRE","CCI","CCL","CDAY","CDNS","CDW",
    "CE","CEG","CF","CFG","CHD","CHRW","CHTR","CI","CINF","CL",
    "CLX","CMA","CMCSA","CME","CMG","CMI","CMS","CNC","CNP","COF",
    "COO","COP","COST","CPB","CPRT","CPT","CRL","CRM","CSCO","CSGP",
    "CSX","CTAS","CTRA","CTSH","CTVA","CVS","CVX","CZR","D","DAL",
    "DD","DE","DECK","DFS","DG","DGX","DHI","DHR","DIS","DLR",
    "DLTR","DOV","DOW","DPZ","DRI","DTE","DUK","DVA","DVN","DXCM",
    "EA","EBAY","ECL","ED","EFX","EIX","EL","EMN","EMR","ENPH",
    "EOG","EPAM","EQIX","EQR","EQT","ES","ESS","ETN","ETR","EVRG",
    "EW","EXC","EXPD","EXPE","EXR","F","FANG","FAST","FBHS","FCX",
    "FDS","FDX","FE","FFIV","FIS","FISV","FITB","FMC","FOX","FOXA",
    "FRT","FSLR","FTNT","FTV","GD","GE","GEHC","GEN","GILD","GIS",
    "GL","GLW","GM","GNRC","GOOG","GOOGL","GPC","GPN","GRMN","GS",
    "GWW","HAL","HAS","HBAN","HCA","HD","HOLX","HON","HPE","HPQ",
    "HRL","HSIC","HST","HSY","HUBB","HUM","HWM","IBM","ICE","IDXX",
    "IEX","IFF","ILMN","INCY","INTC","INTU","INVH","IP","IPG","IQV",
    "IR","IRM","ISRG","IT","ITW","IVZ","J","JBHT","JCI","JKHY",
    "JNJ","JNPR","JPM","K","KDP","KEY","KEYS","KHC","KIM","KLAC",
    "KMB","KMI","KMX","KO","KR","KVUE","L","LDOS","LEN","LH",
    "LHX","LIN","LKQ","LLY","LMT","LNT","LOW","LRCX","LULU","LUV",
    "LVS","LW","LYB","LYV","MA","MAA","MAR","MAS","MCD","MCHP",
    "MCK","MCO","MDLZ","MDT","MET","META","MGM","MHK","MKC","MKTX",
    "MLM","MMC","MMM","MNST","MO","MOH","MOS","MPC","MPWR","MRK",
    "MRNA","MRO","MS","MSCI","MSFT","MSI","MTB","MTCH","MTD","MU",
    "NCLH","NDAQ","NDSN","NEE","NEM","NFLX","NI","NKE","NOC","NOW",
    "NRG","NSC","NTAP","NTRS","NUE","NVDA","NVR","NWS","NWSA","NXPI",
    "O","ODFL","OGN","OKE","OMC","ON","ORCL","ORLY","OTIS","OXY",
    "PARA","PAYC","PAYX","PCAR","PCG","PEG","PEP","PFE","PFG","PG",
    "PGR","PH","PHM","PKG","PLD","PM","PNC","PNR","PNW","POOL",
    "PPG","PPL","PRU","PSA","PSX","PTC","PVH","PWR","PYPL","QCOM",
    "QRVO","RCL","RE","REG","REGN","RF","RHI","RJF","RL","RMD",
    "ROK","ROL","ROP","ROST","RSG","RTX","RVTY","SBAC","SBUX","SCHW",
    "SEE","SHW","SJM","SLB","SMCI","SNA","SNPS","SO","SPG","SPGI",
    "SRE","STE","STLD","STT","STX","STZ","SWK","SWKS","SYF","SYK",
    "SYY","T","TAP","TDG","TDY","TECH","TEL","TER","TFC","TFX",
    "TGT","TMO","TMUS","TPR","TRGP","TRMB","TROW","TRV","TSCO","TSLA",
    "TSN","TT","TTWO","TXN","TXT","TYL","UAL","UDR","UHS","ULTA",
    "UNH","UNP","UPS","URI","USB","V","VICI","VLO","VMC","VRSK",
    "VRSN","VRTX","VTR","VTRS","VZ","WAB","WAT","WBA","WBD","WDC",
    "WEC","WELL","WFC","WHR","WM","WMB","WMT","WRB","WRK","WST",
    "WTW","WY","WYNN","XEL","XOM","XRAY","XYL","YUM","ZBH","ZBRA",
    "ZION","ZTS",
]

# ── Equity ETFs ───────────────────────────────
ETF_EQUITY_TICKERS = [
    "SPY",    # S&P 500
    "QQQ",    # NASDAQ 100
    "IWM",    # Russell 2000
    "EFA",    # MSCI EAFE (Developed International)
    "EEM",    # MSCI Emerging Markets
    "EZU",    # Euro Stoxx 50
    "EWJ",    # Nikkei 225 / Japan
    "EWU",    # FTSE 100 / UK
    "XLF",    # Financials Sector
    "XLE",    # Energy Sector
]

# ── Fixed Income / Bond ETFs ──────────────────
ETF_BOND_TICKERS = [
    "SHY",    # US 2-Year Treasury
    "IEF",    # US 10-Year Treasury
    "TLT",    # US 30-Year Treasury
    "LQD",    # Investment Grade Corporate Bonds
    "HYG",    # High Yield Corporate Bonds
    "EMB",    # Emerging Market Debt
]

# ── Commodity ETFs ────────────────────────────
ETF_COMMODITY_TICKERS = [
    "GLD",    # Gold
    "USO",    # WTI Crude Oil
    "CPER",   # Copper
    "UNG",    # Natural Gas
    "DJP",    # Broad Commodity Index (Bloomberg Commodity)
]

# ── Currency ETFs ─────────────────────────────
ETF_CURRENCY_TICKERS = [
    "UUP",    # DXY (US Dollar Index)
    "FXE",    # EUR/USD
    "FXY",    # JPY/USD
    "FXB",    # GBP/USD
    "FXA",    # AUD/USD
]

# ── Volatility & Alternatives ─────────────────
ALTERNATIVE_TICKERS = [
    "VIXY",    # VIX (Short-Term Futures)
    "BTC-USD", # Bitcoin
    "VNQ",     # US REITs
    "TIP",     # TIPS (Inflation-Linked Bonds)
]

# ─────────────────────────────────────────────
# COMBINED TICKER LIST (auto-computed, deduplicated)
# ─────────────────────────────────────────────
# Order: Stocks first, then ETFs by type, then alternatives.
# Duplicates are removed (first occurrence wins).
def _deduplicate(tickers: list) -> list:
    """Deduplicate while preserving order."""
    seen = set()
    result = []
    for t in tickers:
        t_upper = t.upper()
        if t_upper not in seen:
            seen.add(t_upper)
            result.append(t)
    return result

ALL_TICKERS = _deduplicate(
    STOCK_TICKERS
    + ETF_EQUITY_TICKERS
    + ETF_BOND_TICKERS
    + ETF_COMMODITY_TICKERS
    + ETF_CURRENCY_TICKERS
    + ALTERNATIVE_TICKERS
)

# Backward compatibility alias
TOP_TICKERS = ALL_TICKERS
