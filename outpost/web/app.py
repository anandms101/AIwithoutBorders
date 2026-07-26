"""Outpost web UI (F-08, F-09, F-10, F-11).

FastAPI + server-rendered Jinja. No SPA, no bundler, no build step (D4) — there
is no scenario at 16:00 where debugging a bundler is a good use of time.

The UI must not block on the heartbeat and vice versa (PRD §7). Both processes
talk only to SQLite in WAL mode, so they genuinely run concurrently and can be
shown doing so.

    uvicorn outpost.web.app:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)
from fastapi.templating import Jinja2Templates

from outpost import egress, trace
from outpost.agent import alerting, heartbeat
from outpost.config import settings
from outpost.db import connect, init_db

TEMPLATES_DIR = Path(__file__).parent / "templates"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(settings)
    yield


app = FastAPI(title="Outpost", docs_url=None, redoc_url=None, lifespan=lifespan)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _counters() -> dict[str, Any]:
    with connect(settings) as conn:
        state = heartbeat.status(connection=conn, config=settings)
        state["bytes_sent"] = egress.bytes_sent(connection=conn, config=settings)
        state["bytes_on_box"] = egress.bytes_on_box(connection=conn, config=settings)
    state["ratio"] = (
        state["bytes_on_box"] // state["bytes_sent"] if state["bytes_sent"] else 0
    )
    return state


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    with connect(settings) as conn:
        jobs = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM jobs ORDER BY id DESC LIMIT 25"
            ).fetchall()
        ]
        # One row per case, showing which modalities arrived. This is what makes
        # "audio + film + note became one case" visible at a glance.
        case_rows = [
            dict(row)
            for row in conn.execute(
                "SELECT j.case_id,"
                " MAX(j.kind = 'audio') AS has_audio,"
                " MAX(j.kind = 'image') AS has_image,"
                " MAX(j.kind = 'note')  AS has_note,"
                " CASE WHEN SUM(j.status = 'failed') > 0 THEN 'failed'"
                "      WHEN SUM(j.status IN ('queued','running')) > 0 THEN 'running'"
                "      ELSE 'done' END AS status,"
                " MAX(j.error) AS error,"
                " (SELECT a.syndrome_code FROM artifacts a"
                "   WHERE a.case_id = j.case_id) AS syndrome_code"
                " FROM jobs j GROUP BY j.case_id ORDER BY MIN(j.id) DESC LIMIT 15"
            ).fetchall()
        ]
        alerts = alerting.pending_alerts(connection=conn, config=settings)
        decided = [
            {**dict(row), "case_ids": json.loads(row["case_ids_json"])}
            for row in conn.execute(
                "SELECT * FROM alerts WHERE status != 'pending'"
                " ORDER BY decided_at DESC LIMIT 10"
            ).fetchall()
        ]
        traces = trace.recent(limit=40, connection=conn, config=settings)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "counters": _counters(),
            "jobs": jobs,
            "case_rows": case_rows,
            "alerts": alerts,
            "decided": decided,
            "traces": traces,
            "settings": settings,
        },
    )


@app.get("/case/{case_id}", response_class=HTMLResponse)
def case_detail(request: Request, case_id: str) -> HTMLResponse:
    """F-11 — audio, native transcript and English side by side."""
    with connect(settings) as conn:
        artifact = conn.execute(
            "SELECT * FROM artifacts WHERE case_id = ?", (case_id,)
        ).fetchone()
        case = conn.execute(
            "SELECT * FROM cases WHERE case_id = ?", (case_id,)
        ).fetchone()
        jobs = conn.execute(
            "SELECT * FROM jobs WHERE case_id = ? ORDER BY id", (case_id,)
        ).fetchall()

    return templates.TemplateResponse(
        request,
        "case.html",
        {
            "case_id": case_id,
            "artifact": dict(artifact) if artifact else None,
            "case": dict(case) if case else None,
            "jobs": [dict(job) for job in jobs],
        },
    )


@app.post("/alerts/{alert_id}/approve")
def approve(alert_id: str) -> RedirectResponse:
    """F-10 — the only path that transmits anything (invariant 3)."""
    try:
        egress.approve_alert(alert_id, config=settings)
    except egress.EgressBlocked as exc:
        return RedirectResponse(f"/?error={exc}", status_code=303)
    return RedirectResponse("/", status_code=303)


@app.post("/alerts/{alert_id}/dismiss")
def dismiss(alert_id: str) -> RedirectResponse:
    egress.dismiss_alert(alert_id, config=settings)
    return RedirectResponse("/", status_code=303)


@app.get("/api/status")
def api_status() -> JSONResponse:
    return JSONResponse(_counters())


@app.get("/api/trace")
def api_trace(limit: int = 40) -> JSONResponse:
    """Backs the auto-refreshing trace panel."""
    return JSONResponse({"trace": trace.recent(limit=limit, config=settings)})


@app.get("/api/egress-preview/{alert_id}")
def api_egress_preview(alert_id: str) -> JSONResponse:
    """Show exactly what would leave the box, before anyone approves it."""
    with connect(settings) as conn:
        row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    if row is None:
        return JSONResponse({"error": "unknown alert"}, status_code=404)

    payload = egress.payload_for_alert(dict(row), config=settings)
    return JSONResponse(
        {
            "payload": json.loads(payload.to_json()),
            "bytes": payload.byte_size(),
            "limit": egress.MAX_PAYLOAD_BYTES,
            "destination": settings.egress_url,
        }
    )


def _media_path(case_id: str, column: str) -> Path | None:
    """Resolve a stored media path, refusing anything outside the data root."""
    with connect(settings) as conn:
        row = conn.execute(
            f"SELECT {column} FROM artifacts WHERE case_id = ?", (case_id,)
        ).fetchone()
    if row is None or not row[column]:
        return None

    path = Path(str(row[column])).resolve()
    # Only ever serve from inside the data root. The column is written by our
    # own workers, but a path-traversal hole in a medical UI is not a thing to
    # leave open on the assumption that it stays that way.
    root = settings.data_root.resolve()
    if not path.is_file() or root not in path.parents:
        return None
    return path


@app.get("/media/{case_id}/film", response_model=None)
def media_film(case_id: str) -> FileResponse | JSONResponse:
    """Serve the stored radiograph so the imaging panel shows the actual film."""
    path = _media_path(case_id, "image_path")
    if path is None:
        return JSONResponse({"error": "no film"}, status_code=404)
    suffix = path.suffix.lower()
    media_type = "image/png" if suffix == ".png" else "image/jpeg"
    return FileResponse(path, media_type=media_type)


@app.get("/media/{case_id}/audio", response_model=None)
def media_audio(case_id: str) -> FileResponse | JSONResponse:
    """Serve the consultation recording so it can be played in the browser."""
    path = _media_path(case_id, "audio_path")
    if path is None:
        return JSONResponse({"error": "no audio"}, status_code=404)
    return FileResponse(path, media_type="audio/wav")
