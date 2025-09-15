import psycopg2, json, os
from dotenv import load_dotenv
load_dotenv()

def load_polygon_from_db(stream_id: int, area_id: int = 1):
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )
    cur = conn.cursor()
    cur.execute("""
        SELECT polygon_geojson
        FROM areas
        WHERE stream_id=%s AND area_id=%s AND is_active=TRUE
        LIMIT 1
    """, (stream_id, area_id))
    row = cur.fetchone()
    conn.close()
    if not row:
        raise ValueError("Polygon tidak ditemukan di DB")

    # parsing GeoJSON Feature
    feat = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    coords_norm = feat["geometry"]["coordinates"][0]   # ring pertama
    coord_sys = feat.get("properties", {}).get("coord_system", "image_norm")
    return coords_norm, coord_sys
