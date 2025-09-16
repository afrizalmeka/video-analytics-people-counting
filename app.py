from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from typing import Optional
import psycopg2, os, json

# Routers
from backend.api.routes_stream import router as stream_router

# Use a relative server URL so Swagger doesn't try calling 0.0.0.0
app = FastAPI(
    title="People Counting - MVP",
    servers=[{"url": "/"}]
)

# CORS (open for MVP)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount dashboard AFTER API routes so it doesn't shadow them
app.include_router(stream_router)
app.mount("/dashboard", StaticFiles(directory="dashboard", html=True), name="dashboard")


# ----- DB helpers -----------------------------------------------------------

def _env(key: str, default: Optional[str] = None) -> Optional[str]:
    """Allow DB_* or POSTGRES_* variable names (same behavior as worker)."""
    return os.getenv(key) or os.getenv(key.replace("DB_", "POSTGRES_")) or default


def get_conn():
    return psycopg2.connect(
        host=_env("DB_HOST", "localhost"),
        port=_env("DB_PORT", "5432"),
        dbname=_env("DB_NAME", "people_counting"),
        user=_env("DB_USER", "postgres"),
        password=_env("DB_PASSWORD", ""),
    )


# ----- Schemas --------------------------------------------------------------

class AreaUpdate(BaseModel):
    area_id: int
    polygon_geojson: dict


# ----- Endpoints ------------------------------------------------------------


# Redirect root to dashboard for convenience
@app.get("/")
def root():
    # Keep dashboard mounted at /dashboard to avoid shadowing API routes,
    # but make root URL convenient.
    return RedirectResponse(url="/dashboard/")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/stats/")
def get_stats(
    limit: int = Query(default=100, ge=1, le=1000),
    stream_id: Optional[int] = Query(default=None),
    area_id: Optional[int] = Query(default=None),
):
    """Return recent ENTER/EXIT events. Optional filter by stream_id/area_id."""
    conn = get_conn()
    cur = conn.cursor()

    where = []
    params = []
    if stream_id is not None:
        where.append("stream_id = %s")
        params.append(stream_id)
    if area_id is not None:
        where.append("area_id = %s")
        params.append(area_id)

    sql = "SELECT stream_id, area_id, track_id, ts, direction FROM area_events"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY ts DESC LIMIT %s"
    params.append(limit)

    cur.execute(sql, tuple(params))
    rows = cur.fetchall()
    columns = [desc[0] for desc in cur.description]
    cur.close(); conn.close()
    return [dict(zip(columns, r)) for r in rows]


@app.get("/api/stats/live")
def get_live_stats(
    stream_id: Optional[int] = Query(default=None),
    area_id: Optional[int] = Query(default=None),
):
    """Return current inside count per area from area_live."""
    conn = get_conn()
    cur = conn.cursor()

    where = []
    params = []
    if stream_id is not None:
        where.append("stream_id = %s")
        params.append(stream_id)
    if area_id is not None:
        where.append("area_id = %s")
        params.append(area_id)

    sql = "SELECT stream_id, area_id, current_inside, updated_at FROM area_live"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY updated_at DESC"

    cur.execute(sql, tuple(params))
    rows = cur.fetchall()
    columns = [desc[0] for desc in cur.description]
    cur.close(); conn.close()
    return [dict(zip(columns, r)) for r in rows]


@app.post("/api/config/area")
def update_area_config(payload: AreaUpdate):
    """Update polygon of an area (image_norm coordinates)"""
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE areas
        SET polygon_geojson = %s, updated_at = NOW()
        WHERE area_id = %s
        RETURNING area_id
        """,
        (json.dumps(payload.polygon_geojson), payload.area_id),
    )
    row = cur.fetchone()
    conn.commit()
    cur.close(); conn.close()

    if not row:
        return {"status": "not_found", "area_id": payload.area_id}
    return {"status": "success", "area_id": row[0]}