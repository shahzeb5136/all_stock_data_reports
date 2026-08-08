# Stock Price Downloader — OHLCV Edition

Downloads daily **Open, High, Low, Close, and Volume** (adjusted) for your chosen tickers (300+) from Yahoo Finance, stores them in SQLite + CSV.

**Schema:** `ticker | date | open | high | low | close | volume`
**History:** From **2005-01-01** to today.

## Quick Start

```bash
pip install -r requirements.txt

# 1. Edit config.py — paste your tickers into TOP_TICKERS
# 2. Initial full download (2005 → today):
python main.py bulk

# 3. Every day after that (only fetches new data):
python main.py update
```

## Commands

| Command | What it does |
|---|---|
| `python main.py bulk` | Full historical download from 2005 (initial load) |
| `python main.py update` | Incremental daily update (fast) |
| `python main.py export` | Re-export DB → CSV |
| `python main.py query AAPL` | Print data for one ticker (last 20 rows) |
| `python main.py stats` | Show DB summary |

## Data Fields

All price fields are **split- and dividend-adjusted** (`auto_adjust=True` in yfinance):

| Column | Type | Description |
|---|---|---|
| `ticker` | TEXT | Stock symbol (e.g. AAPL) |
| `date` | TEXT | Trading date (YYYY-MM-DD) |
| `open` | REAL | Adjusted opening price |
| `high` | REAL | Adjusted daily high |
| `low` | REAL | Adjusted daily low |
| `close` | REAL | Adjusted closing price |
| `volume` | INTEGER | Number of shares traded |

## Configuration (config.py)

| Variable | Default | Description |
|---|---|---|
| `TOP_TICKERS` | `[...]` | Your list of tickers (300+ supported) |
| `START_DATE` | `2005-01-01` | Earliest date to fetch |
| `BATCH_SIZE` | `50` | Tickers per yfinance call |
| `SLEEP_BETWEEN_BATCHES` | `4` | Seconds between batches (bulk) |
| `SLEEP_BETWEEN_BATCHES_UPDATE` | `1` | Seconds between batches (daily) |

## How Rate Limiting Works

- **Batch downloads**: 300 tickers = 6 HTTP calls (batches of 50) instead of 300 individual calls.
- **Conservative sleep**: 4 seconds between batches for the longer 20-year bulk download.
- **Daily updates are fast**: Groups tickers by their last-known date and fetches only missing days.

## Migration from Old Schema

If you previously used the old version (which stored only `close`), the tool automatically migrates your database. Run `python main.py bulk` afterward to backfill the open/high/low/volume columns.

## Output

- `stock_prices.db` — SQLite database (primary store)
- `stock_prices.csv` — CSV export (ticker, date, open, high, low, close, volume)

## Estimated Times

| Scenario | Tickers | Time |
|---|---|---|
| Bulk load (2005–today) | 300 | ~3-8 minutes |
| Daily update | 300 | ~10-30 seconds |
