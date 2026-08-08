import os, sys

#  WRITE YOUR QUERIES HERE

QUERY = """
SELECT * FROM stock_prices LIMIT 10
"""

# Add QUERY1, QUERY2, ... for multiple queries (QUERY is ignored if any QUERYn exist)

QUERY1 = """
SELECT * FROM stock_prices LIMIT 10
"""
QUERY2 = """
SELECT 
    ticker, 
    MIN(date) AS min_date
FROM stock_prices
WHERE ticker IN (
    -- Equities (10)
    'SPY',   -- S&P 500
    'QQQ',   -- NASDAQ 100
    'IWM',   -- Russell 2000
    'EFA',   -- MSCI EAFE (Developed International)
    'EEM',   -- MSCI Emerging Markets
    'EZU',   -- Euro Stoxx 50
    'EWJ',   -- Nikkei 225 / Japan
    'EWU',   -- FTSE 100 / UK
    'XLF',   -- Financials Sector
    'XLE',   -- Energy Sector

    -- Fixed Income (6)
    'SHY',   -- US 2-Year Treasury
    'IEF',   -- US 10-Year Treasury
    'TLT',   -- US 30-Year Treasury
    'LQD',   -- Investment Grade Corporate Bonds
    'HYG',   -- High Yield Corporate Bonds
    'EMB',   -- Emerging Market Debt

    -- Commodities (5)
    'GLD',   -- Gold
    'USO',   -- WTI Crude Oil
    'UNG',   -- Natural Gas
    'DJP',   -- Broad Commodity Index

    -- Currencies (5)
    'UUP',   -- DXY (US Dollar Index)
    'FXE',   -- EUR/USD
    'FXY',   -- JPY/USD
    'FXB',   -- GBP/USD
    'FXA',   -- AUD/USD

    -- Volatility & Alternatives (4)
    'VNQ',   -- US REITs
    'TIP'    -- TIPS
)
GROUP BY ticker
"""

# =============================================================================

try:
    import duckdb
except ImportError:
    print("Installing duckdb...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "duckdb"])
    import duckdb

# ── Load CSV ──────────────────────────────────────────────────────────────────
CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stock_prices.csv")
if not os.path.exists(CSV_PATH):
    sys.exit(f"ERROR: stock_prices.csv not found at {CSV_PATH}")

print("Loading stock_prices.csv ...")
con = duckdb.connect()
con.execute(f"CREATE TABLE stock_prices AS SELECT * FROM read_csv_auto('{CSV_PATH.replace(chr(92), '/')}', header=true)")
print(f"[OK] {con.execute('SELECT COUNT(*) FROM stock_prices').fetchone()[0]:,} rows loaded\n")

# ── Collect queries ───────────────────────────────────────────────────────────
import __main__ as _m

numbered = sorted(
    [(k, v) for k, v in vars(_m).items() if k.startswith("QUERY") and k != "QUERY" and isinstance(v, str)],
    key=lambda x: x[0]
)
queries = [(k, v) for k, v in numbered] if numbered else [("QUERY", QUERY)]

# ── Run each query ────────────────────────────────────────────────────────────
def run_query(label, sql):
    sql = sql.strip()
    if not sql:
        print(f"[{label}] (empty — skipped)\n")
        return

    print(f"{'─' * 60}")
    print(f"  {label}")
    print(f"{'─' * 60}")

    try:
        result = con.execute(sql)
        rows   = result.fetchall()
        cols   = [d[0] for d in result.description] if result.description else []

        if not rows:
            print("  (no rows returned)")
        else:
            widths = [len(c) for c in cols]
            for row in rows:
                for i, v in enumerate(row):
                    widths[i] = max(widths[i], len(str(v)))

            print("  " + "  ".join(c.ljust(widths[i]) for i, c in enumerate(cols)))
            print("  " + "  ".join("-" * w for w in widths))
            for row in rows:
                print("  " + "  ".join(str(v).ljust(widths[i]) for i, v in enumerate(row)))
            print(f"\n  ({len(rows):,} rows)")

    except Exception as e:
        print(f"  ERROR: {e}")

    print()

for label, sql in queries:
    run_query(label, sql)
