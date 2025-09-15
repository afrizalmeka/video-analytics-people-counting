# workers/worker_detect_polygon.py
import os, time, json, argparse
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

# ---------- DB loader (psycopg2) ----------
import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

def _env(key, default=""):
    # Prioritas DB_*, fallback ke POSTGRES_*
    return os.getenv(key) or os.getenv(key.replace("DB_", "POSTGRES_")) or default

def load_polygon_from_db(stream_id: int, area_id: int):
    """
    Ambil polygon_geojson dari tabel areas.
    Ekspektasi: GeoJSON Feature (geometry Polygon), koordinat ternormalisasi (0..1).
    """
    conn = psycopg2.connect(
        host=_env("DB_HOST", "localhost"),
        port=_env("DB_PORT", "5432"),
        dbname=_env("DB_NAME", "people_counting"),
        user=_env("DB_USER", "postgres"),
        password=_env("DB_PASSWORD", ""),
    )
    cur = conn.cursor()
    cur.execute(
        """
        SELECT polygon_geojson
        FROM areas
        WHERE stream_id = %s AND area_id = %s AND is_active = TRUE
        LIMIT 1
        """,
        (stream_id, area_id),
    )
    row = cur.fetchone()
    cur.close(); conn.close()

    if not row:
        return None, None

    feat = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    coords_norm = feat["geometry"]["coordinates"][0]
    coord_system = feat.get("properties", {}).get("coord_system", "image_norm")
    return coords_norm, coord_system

# ---------- utils ----------
def poly_norm_to_px(poly_norm, W, H):
    pts = (np.asarray(poly_norm, np.float32) * np.array([W, H], np.float32)).astype(int)
    return pts.reshape((-1, 1, 2))

def atomic_write_jpeg(path: str, bgr_image, quality: int = 70):
    ok, buf = cv2.imencode(".jpg", bgr_image, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        return
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(buf.tobytes())
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

# ---------- main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True, help="mp4/rtsp/hls")
    ap.add_argument("--stream-id", type=int, required=True)
    ap.add_argument("--area-id", type=int, required=True)
    ap.add_argument("--outdir", default="samples/output/nolkm-utara")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--conf", type=float, default=0.3)
    ap.add_argument("--fps", type=float, default=8.0, help="target fps output")
    ap.add_argument("--poly", default="", help="JSON list of [x_norm,y_norm] jika tidak pakai DB")
    ap.add_argument("--poly-pad", type=int, default=0, help="expand polygon outward in pixels")
    ap.add_argument("--model", default="yolov8l.pt", help="model YOLO (mis. yolov8s.pt / yolov8l.pt / path kustom)")
    ap.add_argument("--roi-scale", type=float, default=1.5, help="pembesaran ROI sebelum inferensi (1.0=tanpa)")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    latest_path = os.path.join(args.outdir, "latest.jpg")

    cap = cv2.VideoCapture(args.video)
    ok, frame = cap.read()
    if not ok:
        raise SystemExit("Gagal buka video/stream")

    H, W = frame.shape[:2]

    # --- ambil polygon ---
    if args.poly:
        poly_norm = json.loads(args.poly)
        coord_sys = "image_norm"
    else:
        poly_norm, coord_sys = load_polygon_from_db(args.stream_id, args.area_id)

    if not poly_norm:
        raise SystemExit("Polygon tidak tersedia di DB dan tidak diberikan via --poly")

    if coord_sys != "image_norm":
        print(f"[WARN] coord_system={coord_sys} belum didukung, diasumsikan image_norm 0..1")

    poly_px = poly_norm_to_px(poly_norm, W, H)

    # mask & ROI awal
    mask = np.zeros((H, W), np.uint8)
    cv2.fillPoly(mask, [poly_px], 255)

    # --- expand polygon outward bila diminta ---
    if args.poly_pad and args.poly_pad > 0:
        m = np.zeros((H, W), np.uint8)
        cv2.fillPoly(m, [poly_px], 255)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (args.poly_pad*2+1, args.poly_pad*2+1))
        m = cv2.dilate(m, k, iterations=1)
        cnts,_ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if cnts:
            poly_px = max(cnts, key=cv2.contourArea)
        # rebuild mask setelah expand
        mask = np.zeros((H, W), np.uint8)
        cv2.fillPoly(mask, [poly_px], 255)

    # ROI bbox (pakai nama yang konsisten!)
    x, y, w, h = cv2.boundingRect(poly_px)

    # --- load YOLO ---
    model = YOLO(args.model)

    target = 1.0 / args.fps if args.fps > 0 else 0
    prev = time.perf_counter()

    while True:
        ok, frame = cap.read()
        if not ok:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            continue

        roi = frame[y:y+h, x:x+w]

        # optional: upscale ROI agar detail kecil (orang duduk) lebih “kelihatan”
        if args.roi_scale and args.roi_scale != 1.0:
            roi_for_infer = cv2.resize(
                roi, None, fx=args.roi_scale, fy=args.roi_scale, interpolation=cv2.INTER_CUBIC
            )
        else:
            roi_for_infer = roi

        results = model.predict(
            roi_for_infer, imgsz=args.imgsz, conf=args.conf, classes=[0], iou=0.5, verbose=False
        )

        vis = frame.copy()

        # gambar deteksi (centroid harus di dalam polygon)
        for r in results:
            if getattr(r, "boxes", None) is None:
                continue
            for b in r.boxes:
                x1, y1, x2, y2 = map(int, b.xyxy[0])

                # kembalikan ke skala ROI asli jika tadi dibesarkan
                if args.roi_scale and args.roi_scale != 1.0:
                    inv = 1.0 / args.roi_scale
                    x1 = int(x1 * inv); y1 = int(y1 * inv)
                    x2 = int(x2 * inv); y2 = int(y2 * inv)

                gx1, gy1, gx2, gy2 = x + x1, y + y1, x + x2, y + y2
                cx, cy = (gx1 + gx2)//2, (gy1 + gy2)//2

                if cv2.pointPolygonTest(poly_px, (cx, cy), False) < 0:
                    continue

                cv2.rectangle(vis, (gx1, gy1), (gx2, gy2), (0,255,0), 2)
                conf = float(b.conf[0]) if getattr(b, "conf", None) is not None else 0.0
                cv2.putText(vis, f"person {conf:.2f}",
                            (gx1, max(gy1 - 6, 0)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 2)

        # overlay polygon & gelapkan luar area
        cv2.polylines(vis, [poly_px], True, (0, 255, 255), 2)
        vis[mask == 0] = (vis[mask == 0] * 0.35).astype(np.uint8)

        # header kecil
        cv2.putText(
            vis,
            f"{Path(args.model).name} | imgsz={args.imgsz} conf={args.conf:.2f} fps@{args.fps:.1f}",
            (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,0), 2
        )

        # tulis latest.jpg (atomic)
        atomic_write_jpeg(latest_path, vis, quality=70)

        # pace output
        if target > 0:
            now = time.perf_counter()
            dt = now - prev
            if dt < target:
                time.sleep(target - dt)
            prev = time.perf_counter()

if __name__ == "__main__":
    main()