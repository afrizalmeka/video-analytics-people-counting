from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from backend.api.routes_stream import router as stream_router
import psycopg2, os, json
from fastapi import Query

app = FastAPI(title="People Counting - MVP")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(stream_router)
app.mount("/", StaticFiles(directory="dashboard", html=True), name="dashboard")


def get_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )


@app.get("/api/stats/")
def get_stats(limit: int = Query(default=100)):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM area_events ORDER BY id DESC LIMIT %s", (limit,))
    rows = cur.fetchall()
    columns = [desc[0] for desc in cur.description]
    cur.close()
    conn.close()
    results = [dict(zip(columns, row)) for row in rows]
    return results


@app.get("/api/stats/live")
def get_live_stats():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM area_live")
    rows = cur.fetchall()
    columns = [desc[0] for desc in cur.description]
    cur.close()
    conn.close()
    results = [dict(zip(columns, row)) for row in rows]
    return results


@app.post("/api/config/area")
def update_area_config(area_id: int, polygon_geojson: dict):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE area SET polygon_geojson = %s WHERE id = %s",
        (json.dumps(polygon_geojson), area_id)
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "success", "area_id": area_id}