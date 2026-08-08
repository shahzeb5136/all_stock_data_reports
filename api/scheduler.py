"""Daily refresh + pack build orchestration.

A single background thread owns the schedule.  When a build is due it spawns
``api.build_pack`` as a child process, reads the manifest it prints, uploads
the PDFs to R2, and flips the pack row to ``ready``.  The API process itself
never loads the price history.

Only one build runs at a time — guarded by ``_build_lock`` — so a manual
admin rebuild cannot collide with the scheduled one.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from api import database
from api.build_pack import MANIFEST_SENTINEL
from api.builder import REPO_ROOT
from api.settings import (
    BUILD_HOUR_UTC,
    BUILD_ON_BOOT,
    BUILD_TIMEOUT_SECONDS,
    PACK_WORK_DIR,
    SCHEDULER_POLL_SECONDS,
    ensure_dirs,
)
from api.storage import upload_pack_file

logger = logging.getLogger(__name__)

_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_build_lock = threading.Lock()

# Observable state for the admin status endpoint.
_state: Dict[str, Any] = {
    "building": False,
    "last_started_at": None,
    "last_finished_at": None,
    "last_pack_id": None,
    "last_error": None,
}
_state_lock = threading.Lock()


def _set_state(**kwargs: Any) -> None:
    with _state_lock:
        _state.update(kwargs)


def get_state() -> Dict[str, Any]:
    with _state_lock:
        return dict(_state)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> str:
    return _now().strftime("%Y-%m-%d")


# ── Child process ────────────────────────────────────────────────────────────

def _drain(stream, sink: deque) -> None:
    """Log the child's stderr live and keep a tail for error reporting."""
    for line in iter(stream.readline, ""):
        line = line.rstrip()
        if line:
            sink.append(line)
            logger.info("[build] %s", line)
    stream.close()


def _run_build_subprocess(out_dir: Path, snapshot_date: str, skip_refresh: bool) -> Dict[str, Any]:
    """Run api.build_pack and return its manifest.

    Raises RuntimeError with the tail of the child's stderr on failure.
    """
    cmd = [
        sys.executable,
        "-m",
        "api.build_pack",
        "--out-dir",
        str(out_dir),
        "--snapshot-date",
        snapshot_date,
    ]
    if skip_refresh:
        cmd.append("--skip-refresh")

    logger.info("Spawning build: %s", " ".join(cmd))
    # UTF-8 is pinned on both sides of the pipe: the report scripts print
    # emoji, and the default locale codec would raise on either encode or
    # decode. errors="replace" keeps a stray byte from killing a good build.
    child_env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.Popen(
        cmd,
        cwd=str(REPO_ROOT),
        env=child_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    err_tail: deque = deque(maxlen=40)
    drainer = threading.Thread(target=_drain, args=(proc.stderr, err_tail), daemon=True)
    drainer.start()

    # Watchdog: a wedged network call must not block every future build.
    timed_out = threading.Event()

    def _kill() -> None:
        timed_out.set()
        logger.error("Build exceeded %ss — killing", BUILD_TIMEOUT_SECONDS)
        proc.kill()

    watchdog = threading.Timer(BUILD_TIMEOUT_SECONDS, _kill)
    watchdog.start()

    try:
        stdout_data = proc.stdout.read()
        returncode = proc.wait()
    finally:
        watchdog.cancel()
        proc.stdout.close()
        drainer.join(timeout=10)

    if timed_out.is_set():
        raise RuntimeError(f"Build timed out after {BUILD_TIMEOUT_SECONDS}s")

    if returncode != 0:
        raise RuntimeError(
            f"Build process exited {returncode}. Last output:\n" + "\n".join(err_tail)
        )

    for line in stdout_data.splitlines():
        if line.startswith(MANIFEST_SENTINEL):
            return json.loads(line[len(MANIFEST_SENTINEL):])

    raise RuntimeError("Build produced no manifest. Last output:\n" + "\n".join(err_tail))


# ── Build orchestration ──────────────────────────────────────────────────────

def run_build(skip_refresh: bool = False) -> Optional[str]:
    """Build, upload, and register one pack. Returns the pack id, or None if
    another build is already running.
    """
    if not _build_lock.acquire(blocking=False):
        logger.info("Build already in progress — skipping this trigger")
        return None

    ensure_dirs()
    snapshot_date = _today()
    pack_id = database.create_pack(snapshot_date)
    out_dir = PACK_WORK_DIR / pack_id

    _set_state(
        building=True,
        last_started_at=_now().isoformat(),
        last_pack_id=pack_id,
        last_error=None,
    )
    logger.info("Starting pack %s for %s", pack_id, snapshot_date)

    try:
        manifest = _run_build_subprocess(out_dir, snapshot_date, skip_refresh)

        report_keys: Dict[str, Dict[str, Any]] = {}
        for report in manifest["reports"]:
            path = Path(report["path"])
            key = upload_pack_file(snapshot_date, pack_id, path)
            report_keys[report["slug"]] = {
                "key": key,
                "filename": report["filename"],
                "title": report["title"],
                "description": report["description"],
                "bytes": report["bytes"],
            }
            logger.info("Uploaded %s → %s", report["filename"], key)

        database.mark_pack_ready(
            pack_id,
            report_keys=report_keys,
            data_through=manifest.get("data_through"),
            ticker_count=manifest.get("ticker_count"),
        )
        _set_state(building=False, last_finished_at=_now().isoformat(), last_error=None)
        logger.info("Pack %s ready with %s reports", pack_id, len(report_keys))
        return pack_id

    except Exception as exc:
        logger.exception("Pack %s failed", pack_id)
        database.mark_pack_failed(pack_id, str(exc))
        _set_state(building=False, last_finished_at=_now().isoformat(), last_error=str(exc))
        return None

    finally:
        _cleanup_work_dir(out_dir)
        _build_lock.release()


def _cleanup_work_dir(out_dir: Path) -> None:
    """Drop the local PDFs once they are safely in R2."""
    if not out_dir.exists():
        return
    try:
        for item in out_dir.iterdir():
            item.unlink()
        out_dir.rmdir()
    except OSError as exc:
        logger.warning("Could not clean build dir %s: %s", out_dir, exc)


# ── Schedule ─────────────────────────────────────────────────────────────────

def _build_is_due() -> bool:
    """True when today's pack has not been built and the build hour has passed."""
    if _now().hour < BUILD_HOUR_UTC:
        return False
    return not database.has_pack_for_date(_today())


def _loop() -> None:
    # A pack left "building" cannot resume after a restart, and would
    # otherwise make has_pack_for_date() block today's real build.
    reaped = database.reap_stale_building_packs()
    if reaped:
        logger.warning("Marked %s interrupted pack(s) as failed", reaped)

    if BUILD_ON_BOOT and database.get_latest_ready_pack() is None:
        logger.info("No ready pack exists — building one now")
        run_build()

    while not _stop_event.is_set():
        try:
            if _build_is_due():
                logger.info("Daily build is due")
                run_build()
        except Exception:
            logger.exception("Scheduler loop error")
        _stop_event.wait(timeout=SCHEDULER_POLL_SECONDS)


def start_scheduler() -> None:
    """Start the background scheduler thread (idempotent)."""
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="pack-scheduler")
    _thread.start()
    logger.info("Scheduler started (daily build at %02d:00 UTC)", BUILD_HOUR_UTC)


def stop_scheduler() -> None:
    """Signal the scheduler to stop and wait briefly for it."""
    _stop_event.set()
    if _thread:
        _thread.join(timeout=10)
    logger.info("Scheduler stopped")


def trigger_build_async(skip_refresh: bool = False) -> bool:
    """Kick a build off-thread. False if one is already running."""
    if _build_lock.locked():
        return False
    threading.Thread(
        target=run_build,
        kwargs={"skip_refresh": skip_refresh},
        daemon=True,
        name="manual-build",
    ).start()
    return True
