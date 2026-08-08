# Stock Reports Service — Backend

Turns the three analysers in `reports/` into a paid service: one credit buys
the current **report pack** — all three PDFs built from the same nightly price
snapshot.

| Report | Slug | What it ranks |
|---|---|---|
| Dip Opportunities | `dip` | 20 strongest pullbacks in otherwise healthy stocks |
| Momentum Surges | `surge` | 20 strongest recent breakouts, extreme runners filtered out |
| Stable Growth Leaders | `stable_growth` | 20 smoothest upward trajectories by stability score |

## How it works

All three reports are **market-wide**, so their output is identical for every
user on a given day. Generating them per click would burn minutes of CPU to
produce bytes someone else already has. So they are pre-built instead:

```
  22:00 UTC daily
        │
        ├─ smart_update()        yfinance → /data/stock_prices.csv
        ├─ build 3 PDFs          in a subprocess (~1.5GB pandas)
        ├─ upload to R2          packs/<date>/<pack_id>/*.pdf
        └─ pack row → 'ready'

  user clicks "Get Reports"
        │
        ├─ deduct 1 credit       shared Postgres, atomic
        ├─ record purchase       SQLite, unique per (user, pack)
        └─ return 3 presigned URLs        ~200ms
```

Measured build time on a warm CSV: **~85 seconds** for all three reports.
A cold volume additionally runs a full 2005→today download first.

### Pieces

| File | Role |
|---|---|
| `api/main.py` | FastAPI app and all endpoints |
| `api/scheduler.py` | Daily schedule, spawns builds, uploads, records packs |
| `api/build_pack.py` | Subprocess entrypoint: refresh prices → build → emit manifest |
| `api/builder.py` | Calls the three analysers; owns the report catalogue |
| `api/database.py` | Credits (Postgres) + packs/purchases (SQLite) |
| `api/storage.py` | Cloudflare R2 upload and presigned URLs |
| `api/auth.py` | Clerk JWT verification |
| `api/settings.py` | All environment configuration |

The analysers in `reports/` are **not modified** — `builder.py` imports them and
calls their existing functions, so `python reports/dip_analyzer.py` locally and
the hosted service produce the same PDFs from the same code.

## Price data: seed once, then incremental forever

The service never bulk-downloads history. Twenty years of daily bars for
hundreds of tickers is exactly the request Yahoo Finance throttles, and it
throttles a datacenter IP far harder than a residential one.

Instead the existing CSV is uploaded to R2 once as a **seed**. On a cold
volume the service restores it and then runs the normal incremental update,
so Yahoo is only ever asked for the days actually missing:

```
  cold volume ──► restore r2://<bucket>/seed/stock_prices.csv
                        │
                        └─► smart_update()   only the gap since the seed
  warm volume ──► smart_update()             only the gap since yesterday
```

Upload the seed **before the first deploy**:

```bash
python scripts/seed_upload.py                 # uses reports/stock_prices.csv
```

If no seed exists, a build **fails with an explanatory error rather than
falling back to a bulk download**. Setting `ALLOW_BULK_SEED=true` opts into
the slow path deliberately; there is no way to trigger it by accident.

Refresh the seed occasionally so a rebuilt volume has less to catch up on:

```bash
curl -X POST "https://<service>/api/admin/seed/backup?key=<ADMIN_SECRET_KEY>"
```

## Deploying to Railway

1. **Upload the seed** (above). Do this first.

2. **New service** from this repo. `railway.json` selects the Dockerfile.

3. **Attach a volume mounted at `/data`.** Required — it holds the price CSV
   and the service SQLite DB. 5GB is plenty. Note the path is `/data`; if you
   run another service with a different mount point, do not copy its
   `DATA_DIR` value here.

4. **Reference the existing Postgres** so credits are the shared wallet:
   ```
   DATABASE_URL=${{Postgres.DATABASE_URL}}
   ```
   Use the variable reference, not a pasted URL, so it survives rotation.

5. **Set the remaining variables** (see `.env.example`):
   `CLERK_JWKS_URL`, `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`,
   `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`, `ADMIN_SECRET_KEY`,
   `FRONTEND_URL`.

   `CLERK_JWKS_URL` **must be the same Clerk application as trading_agents** —
   that is what makes the user IDs match and the credit wallet shared.

6. **First boot** restores the seed, closes the gap, and builds the first pack
   — a few minutes. The API is live and healthy throughout;
   `/api/reports/latest` returns `pack: null, building: true` until it lands.

The R2 bucket must exist and should stay private — the service hands out
short-lived presigned URLs rather than public links. Sharing a bucket with
another service is fine: keys here live under `packs/` and `seed/`.

### Environment variables

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | — | Shared Postgres. Unset ⇒ SQLite (local dev only) |
| `CLERK_JWKS_URL` | — | **Required.** Same Clerk app as trading_agents |
| `R2_ACCOUNT_ID` / `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` | — | **Required** |
| `R2_BUCKET_NAME` | `stock-reports` | Must exist, keep private |
| `ADMIN_SECRET_KEY` | — | Protects `/api/admin/*`. Long random string |
| `FRONTEND_URL` | `http://localhost:3000` | CORS origin |
| `EXTRA_CORS_ORIGINS` | — | Comma-separated extras (preview deploys, www vs apex) |
| `SEED_CSV_R2_KEY` | `seed/stock_prices.csv` | Where the price-history seed lives |
| `ALLOW_BULK_SEED` | `false` | Permit a full Yahoo download when no seed exists |
| `PACK_CREDIT_COST` | `1` | Credits per pack |
| `BUILD_HOUR_UTC` | `22` | ~6pm ET, after the US close |
| `BUILD_ON_BOOT` | `true` | Build immediately if no pack is ready |
| `SCHEDULER_ENABLED` | `true` | See scaling note below |
| `BUILD_TIMEOUT_SECONDS` | `7200` | Ceiling on one build |
| `DOWNLOAD_URL_TTL_SECONDS` | `3600` | Presigned URL lifetime |
| `DATA_DIR` / `STOCK_CSV_PATH` | `/data` | Set by the Dockerfile |

## API

All user endpoints take `Authorization: Bearer <clerk_jwt>`.

### `GET /api/reports/catalogue` — public

What a pack contains. No auth, safe for a landing page.

```json
{ "credit_cost": 1,
  "reports": [ { "slug": "dip", "title": "Dip Opportunities", "description": "…" }, … ] }
```

### `GET /api/reports/latest`

Drives the button. Tells you the pack on sale, the user's balance, and whether
they already own it.

```json
{
  "pack": {
    "id": "93dc2b82-…", "snapshot_date": "2026-08-08",
    "data_through": "2026-08-07", "ticker_count": 500,
    "built_at": "2026-08-08T22:04:11+00:00",
    "reports": [ { "slug": "dip", "title": "…", "description": "…",
                   "filename": "dip_report_2026-08-08.pdf", "bytes": 2295967 }, … ]
  },
  "owned": false,
  "credit_cost": 1,
  "credits": 18,
  "downloads": [],
  "building": false
}
```

- `owned: false` → show the price, enable the buy button.
- `owned: true` → `downloads` is populated; show download links, no charge.
- `pack: null` + `building: true` → first build still running; show a wait state.

### `POST /api/reports/purchase`

The button. Body is optional:

```json
{ "pack_id": "93dc2b82-…" }
```

Passing the `pack_id` the user was shown is recommended — if the nightly
rebuild lands between render and click, you get a `409` instead of silently
selling a different pack.

```json
{
  "purchase_id": "…", "pack": { … }, "charged": true,
  "credits_spent": 1, "credits_remaining": 17,
  "downloads": [ { "slug": "dip", "title": "Dip Opportunities",
                   "filename": "dip_report_2026-08-08.pdf",
                   "bytes": 2295967, "url": "https://…presigned…" }, … ]
}
```

**Charging is idempotent per (user, pack).** Calling it again for a pack the
user already owns returns `charged: false`, `credits_spent: 0`, and fresh
links. A double-click, a retry, or a refresh cannot double-charge.

| Status | Meaning |
|---|---|
| `402` | Insufficient credits — send them to your existing top-up flow |
| `409` | No pack ready yet, or the pinned `pack_id` is stale (refresh) |

### `GET /api/reports/purchases`

Every pack the user owns, newest first, each with freshly signed links.

### `GET /api/reports/packs/{pack_id}/downloads`

Re-sign links for an owned pack. Presigned URLs expire after
`DOWNLOAD_URL_TTL_SECONDS`, so call this rather than caching URLs. `403` if
the user does not own it.

### `GET /api/credits`

`{ "credits": 18 }` — the shared balance, same number trading_agents shows.

### Admin — `?key=<ADMIN_SECRET_KEY>`

| Endpoint | Purpose |
|---|---|
| `GET /api/admin/status` | Scheduler state and the latest pack |
| `GET /api/admin/packs?limit=25` | Pack history including failures |
| `GET /api/admin/users` | All users and balances |
| `POST /api/admin/credits` | `{"user_id": "...", "amount": 5}` — grant credits |
| `POST /api/admin/build` | Force a rebuild now |
| `POST /api/admin/seed/backup` | Snapshot the volume's price CSV to R2 as the seed |

`POST /api/admin/build?key=…&skip_refresh=true` rebuilds the PDFs from the
price CSV as it stands, without hitting Yahoo Finance. That is the fast way to
reissue a pack after changing report code.

## Local development

```bash
pip install -r requirements.txt
cp .env.example .env      # fill in Clerk + R2; leave DATABASE_URL blank for SQLite
```

Serve the API without ever building (uses SQLite, no R2 needed until a purchase):

```bash
SCHEDULER_ENABLED=false uvicorn api.main:app --reload
```

Build a pack from an existing CSV without touching Yahoo Finance:

```bash
python -m api.build_pack --out-dir ./out --snapshot-date 2026-08-08 --skip-refresh
```

Running the analysers directly still works exactly as before — `CSV_PATH` only
moves when `STOCK_CSV_PATH` is set.

## Operational notes

- **One builder only.** The scheduler assumes a single process owns the daily
  build. If you ever scale past one replica, set `SCHEDULER_ENABLED=false` on
  the extras.
- **Packs are never deleted.** Purchases reference them, so old links keep
  working. At ~6MB/day that is ~2GB/year of R2 — pennies, but it does grow.
- **A failed build leaves the previous pack on sale.** `get_latest_ready_pack()`
  only ever returns `ready` packs, so a bad night degrades to stale reports
  rather than an outage. Watch `GET /api/admin/status` for `last_error`.
- **Interrupted builds self-heal.** A pack left `building` by a redeploy is
  marked failed on next boot, so the same-day guard cannot wedge.
- **Credit refunds.** Credits live in Postgres and purchases in SQLite, so the
  two writes cannot share a transaction. The credit is taken first and refunded
  if the purchase row fails to land.
- **Memory.** The build subprocess holds the full price history in pandas —
  roughly 1.5GB at 500 tickers. It is deliberately a separate process so an OOM
  cannot take the API down. If you add many more tickers, watch this.
