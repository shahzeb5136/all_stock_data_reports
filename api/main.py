"""FastAPI application for the Stock Reports SaaS backend.

One credit buys the current report pack: all three PDFs (dip, surge, stable
growth) built from the same nightly price snapshot.  Packs are pre-built by
the scheduler, so a purchase is a credit deduction plus three presigned R2
URLs — no waiting, no job polling.

Credits are read from the shared Railway Postgres, the same wallet the
trading_agents service spends, keyed by Clerk user ID.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

from api import database, scheduler
from api.auth import get_user_data_from_token
from api.builder import REPORT_CATALOGUE
from api.database import InsufficientCredits
from api.settings import (
    ADMIN_SECRET_KEY,
    PACK_CREDIT_COST,
    SCHEDULER_ENABLED,
    allowed_origins,
    ensure_dirs,
)
from api.storage import get_download_url

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

_SLUG_ORDER = [r["slug"] for r in REPORT_CATALOGUE]


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    database.init_db()
    if SCHEDULER_ENABLED:
        scheduler.start_scheduler()
    else:
        logger.warning("Scheduler disabled (SCHEDULER_ENABLED=false) — no packs will be built")
    logger.info("Stock Reports API started")
    yield
    if SCHEDULER_ENABLED:
        scheduler.stop_scheduler()
    logger.info("Stock Reports API stopped")


app = FastAPI(title="Stock Reports API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Auth ─────────────────────────────────────────────────────────────────────

async def get_current_user(authorization: Optional[str] = Header(None)) -> str:
    """Verify the Clerk bearer token and return the user ID."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    try:
        user_id, email = get_user_data_from_token(authorization[7:])
    except Exception as exc:
        logger.warning("Auth failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    database.get_or_create_user(user_id, email=email)
    return user_id


def require_admin(key: str) -> None:
    if not ADMIN_SECRET_KEY or key != ADMIN_SECRET_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")


# ── Serialisation helpers ────────────────────────────────────────────────────

def _sorted_reports(report_keys: Dict[str, Any]) -> List[tuple[str, Dict[str, Any]]]:
    """Pack reports in catalogue order so the UI is stable across packs."""
    known = [(s, report_keys[s]) for s in _SLUG_ORDER if s in report_keys]
    extra = [(s, m) for s, m in report_keys.items() if s not in _SLUG_ORDER]
    return known + extra


def _pack_summary(pack: Dict[str, Any]) -> Dict[str, Any]:
    """Public metadata for a pack — safe to show before purchase."""
    return {
        "id": pack["id"],
        "snapshot_date": pack["snapshot_date"],
        "data_through": pack.get("data_through"),
        "ticker_count": pack.get("ticker_count"),
        "built_at": pack.get("completed_at"),
        "reports": [
            {
                "slug": slug,
                "title": meta.get("title"),
                "description": meta.get("description"),
                "filename": meta.get("filename"),
                "bytes": meta.get("bytes"),
            }
            for slug, meta in _sorted_reports(pack.get("report_keys") or {})
        ],
    }


def _downloads_for(pack: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Presigned download links. Only ever called for a pack the user owns."""
    downloads = []
    for slug, meta in _sorted_reports(pack.get("report_keys") or {}):
        try:
            url = get_download_url(meta["key"], filename=meta.get("filename"))
        except Exception:
            logger.exception("Could not sign download for %s", meta.get("key"))
            continue
        downloads.append(
            {
                "slug": slug,
                "title": meta.get("title"),
                "filename": meta.get("filename"),
                "bytes": meta.get("bytes"),
                "url": url,
            }
        )
    return downloads


# ── Models ───────────────────────────────────────────────────────────────────

class PurchaseRequest(BaseModel):
    # Optional: pin the purchase to the pack the user was shown, so a
    # rebuild landing mid-click cannot silently sell them a different one.
    pack_id: Optional[str] = None


class AdminAddCreditsRequest(BaseModel):
    user_id: str
    amount: int


# ── Public endpoints ─────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/reports/catalogue")
async def catalogue():
    """What a pack contains. Unauthenticated — usable on a landing page."""
    return {
        "credit_cost": PACK_CREDIT_COST,
        "reports": [
            {"slug": r["slug"], "title": r["title"], "description": r["description"]}
            for r in REPORT_CATALOGUE
        ],
    }


@app.get("/api/credits")
async def credits(user_id: str = Depends(get_current_user)):
    return {"credits": database.get_user_credits(user_id)}


@app.get("/api/reports/latest")
async def latest_pack(user_id: str = Depends(get_current_user)):
    """The pack currently on sale, plus whether this user already owns it.

    Drives the button state: `owned` true means hand back the download links
    for free, false means show the price.
    """
    pack = database.get_latest_ready_pack()
    if not pack:
        state = scheduler.get_state()
        return {
            "pack": None,
            "owned": False,
            "credit_cost": PACK_CREDIT_COST,
            "credits": database.get_user_credits(user_id),
            "downloads": [],
            "building": state.get("building", False),
        }

    owned = database.get_purchase(user_id, pack["id"]) is not None
    return {
        "pack": _pack_summary(pack),
        "owned": owned,
        "credit_cost": PACK_CREDIT_COST,
        "credits": database.get_user_credits(user_id),
        "downloads": _downloads_for(pack) if owned else [],
        "building": scheduler.get_state().get("building", False),
    }


@app.post("/api/reports/purchase")
async def purchase(
    body: Optional[PurchaseRequest] = None,
    user_id: str = Depends(get_current_user),
):
    """Spend credits on the current pack and return download links.

    Charging is idempotent per (user, pack): buying a pack the user already
    owns re-issues fresh links without deducting again.
    """
    pack = database.get_latest_ready_pack()
    if not pack:
        raise HTTPException(
            status_code=409,
            detail="No report pack is available yet. Please try again shortly.",
        )

    if body and body.pack_id and body.pack_id != pack["id"]:
        # The user clicked on a pack that has since been superseded.
        raise HTTPException(
            status_code=409,
            detail="A newer report pack is available. Refresh and try again.",
        )

    try:
        purchase_row, charged = database.purchase_pack(user_id, pack["id"], PACK_CREDIT_COST)
    except InsufficientCredits:
        raise HTTPException(
            status_code=402,
            detail="Insufficient credits. Please purchase more credits.",
        )

    if charged:
        logger.info("User %s bought pack %s for %s credit(s)", user_id, pack["id"], PACK_CREDIT_COST)

    return {
        "purchase_id": purchase_row["id"],
        "pack": _pack_summary(pack),
        "charged": charged,
        "credits_spent": PACK_CREDIT_COST if charged else 0,
        "credits_remaining": database.get_user_credits(user_id),
        "downloads": _downloads_for(pack),
    }


@app.get("/api/reports/purchases")
async def purchases(user_id: str = Depends(get_current_user)):
    """Every pack this user owns, with freshly signed download links."""
    rows = database.list_user_purchases(user_id)
    return {
        "purchases": [
            {
                "purchase_id": row["purchase_id"],
                "purchased_at": row["purchased_at"],
                "credits_spent": row["credits_spent"],
                "pack": _pack_summary(row),
                "downloads": _downloads_for(row),
            }
            for row in rows
        ]
    }


@app.get("/api/reports/packs/{pack_id}/downloads")
async def pack_downloads(pack_id: str, user_id: str = Depends(get_current_user)):
    """Re-sign links for a pack the user already owns.

    Presigned URLs expire, so the frontend calls this rather than caching them.
    """
    if not database.get_purchase(user_id, pack_id):
        raise HTTPException(status_code=403, detail="You do not own this report pack")

    pack = database.get_pack(pack_id)
    if not pack or pack["status"] != "ready":
        raise HTTPException(status_code=404, detail="Report pack not found")

    return {"pack": _pack_summary(pack), "downloads": _downloads_for(pack)}


# ── Admin endpoints ──────────────────────────────────────────────────────────

@app.get("/api/admin/users")
async def admin_users(key: str):
    require_admin(key)
    return {"users": database.get_all_users()}


@app.post("/api/admin/credits")
async def admin_add_credits(body: AdminAddCreditsRequest, key: str):
    require_admin(key)
    return {"user_id": body.user_id, "new_balance": database.add_credits(body.user_id, body.amount)}


@app.get("/api/admin/packs")
async def admin_packs(key: str, limit: int = 25):
    require_admin(key)
    return {"packs": database.list_packs(limit=limit)}


@app.get("/api/admin/status")
async def admin_status(key: str):
    require_admin(key)
    latest = database.get_latest_ready_pack()
    return {
        "scheduler": scheduler.get_state(),
        "latest_pack": _pack_summary(latest) if latest else None,
        "credit_cost": PACK_CREDIT_COST,
    }


@app.post("/api/admin/build")
async def admin_build(key: str, skip_refresh: bool = False):
    """Force a rebuild now.

    ``skip_refresh=true`` rebuilds the PDFs from the price CSV as it stands,
    without hitting Yahoo Finance — useful for reissuing a pack after a
    report-code change.
    """
    require_admin(key)
    if not scheduler.trigger_build_async(skip_refresh=skip_refresh):
        raise HTTPException(status_code=409, detail="A build is already running")
    return {"status": "started", "skip_refresh": skip_refresh}
