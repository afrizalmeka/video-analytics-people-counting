# workers/worker_track_polygon.py
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
    return os.getenv(key) or os.getenv(key.replace("DB_", "POSTGRES_")) or default

def load_polygon_from_db(stream_id: int, area_id: int):
    conn = psycopg2.connect(
        host=_env("DB_HOST", "localhost"),
        port=_env("DB_PORT", "5432"),
        dbname=_env("DB_NAME", "people_counting"),
        user=_env("DB_USER", "postgres"),
        password=_env("DB_PASSWORD", ""),
    )
    cur = conn.cursor()
    cur.execute("""
        SELECT polygon_geojson
        FROM areas
        WHERE stream_id = %s AND area_id = %s AND is_active = TRUE
        LIMIT 1
    """, (stream_id, area_id))
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
        f.write(buf.tobytes()); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)

# ---------- very simple Centroid Tracker ----------
class CentroidTracker:
    def __init__(self, max_disappeared=30, max_dist=80):
        self.next_id = 1
        self.tracks = {}           # id -> {"centroid":(x,y), "bbox":(x1,y1,x2,y2), "dis":0}
        self.max_disappeared = max_disappeared
        self.max_dist = max_dist

    def _centroid(self, bbox):
        x1,y1,x2,y2 = bbox
        return ((x1+x2)//2, (y1+y2)//2)

    def update(self, bboxes):
        # bboxes: list[(x1,y1,x2,y2)]
        if len(self.tracks) == 0:
            for bb in bboxes:
                self.tracks[self.next_id] = {"bbox":bb, "centroid":self._centroid(bb), "dis":0}
                self.next_id += 1
            return self.tracks

        if len(bboxes) == 0:
            # increment disappeared
            for tid in list(self.tracks.keys()):
                self.tracks[tid]["dis"] += 1
                if self.tracks[tid]["dis"] > self.max_disappeared:
                    del self.tracks[tid]
            return self.tracks

        # build distance matrix (tracks x detections)
        track_ids = list(self.tracks.keys())
        T = len(track_ids); D = len(bboxes)
        dist = np.full((T, D), 1e9, dtype=np.float32)
        for i, tid in enumerate(track_ids):
            c = self.tracks[tid]["centroid"]
            for j, bb in enumerate(bboxes):
                cx, cy = ((bb[0]+bb[2])//2, (bb[1]+bb[3])//2)
                dist[i, j] = np.hypot(c[0]-cx, c[1]-cy)

        # greedy matching (cukup untuk baseline)
        matched_det = set()
        matched_trk = set()
        for _ in range(min(T, D)):
            i, j = np.unravel_index(np.argmin(dist), dist.shape)
            if dist[i, j] > self.max_dist:
                break
            if i in matched_trk or j in matched_det:
                dist[i, j] = 1e9; continue
            # assign
            tid = track_ids[i]
            bb = bboxes[j]
            self.tracks[tid]["bbox"] = bb
            self.tracks[tid]["centroid"] = self._centroid(bb)
            self.tracks[tid]["dis"] = 0
            matched_trk.add(i); matched_det.add(j)
            dist[i, :] = 1e9
            dist[:, j] = 1e9

        # unassigned tracks -> disappear++
        for idx, tid in enumerate(track_ids):
            if idx not in matched_trk:
                self.tracks[tid]["dis"] += 1
                if self.tracks[tid]["dis"] > self.max_disappeared:
                    del self.tracks[tid]

        # unassigned detections -> new tracks
        for j, bb in enumerate(bboxes):
            if j not in matched_det:
                self.tracks[self.next_id] = {"bbox":bb, "centroid":self._centroid(bb), "dis":0}
                self.next_id += 1

        return self.tracks

# ---------- main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--stream-id", type=int, required=True)
    ap.add_argument("--area-id", type=int, required=True)
    ap.add_argument("--outdir", default="samples/output/nolkm-utara")
    ap.add_argument("--imgsz", type=int, default=960)
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--iou", type=float, default=0.5)
    ap.add_argument("--fps", type=float, default=8.0)
    ap.add_argument("--model", default="yolov8l.pt")  # ganti model bebas
    ap.add_argument("--poly", default="", help="JSON list of [x_norm,y_norm] jika tidak pakai DB")
    ap.add_argument("--poly-pad", type=int, default=0, help="expand polygon outward in pixels")
    ap.add_argument("--trk-max-dist", type=int, default=80)
    ap.add_argument("--trk-max-miss", type=int, default=30)
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    latest_path = os.path.join(args.outdir, "latest.jpg")

    cap = cv2.VideoCapture(args.video)
    ok, frame = cap.read()
    if not ok:
        raise SystemExit("Gagal buka video/stream")
    H, W = frame.shape[:2]

    # polygon
    if args.poly:
        poly_norm, coord_sys = json.loads(args.poly), "image_norm"
    else:
        poly_norm, coord_sys = load_polygon_from_db(args.stream_id, args.area_id)
    if not poly_norm:
        raise SystemExit("Polygon tidak tersedia (DB/--poly).")
    poly_px = poly_norm_to_px(poly_norm, W, H)

    # ROI bbox & mask
    x, y, w, h = cv2.boundingRect(poly_px)
    mask = np.zeros((H, W), np.uint8)
    cv2.fillPoly(mask, [poly_px], 255)

    # optional pad polygon outward
    if args.poly_pad > 0:
        m = np.zeros((H, W), np.uint8); cv2.fillPoly(m, [poly_px], 255)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (args.poly_pad*2+1, args.poly_pad*2+1))
        m = cv2.dilate(m, k, iterations=1)
        cnts,_ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if cnts:
            poly_px = max(cnts, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(poly_px)
        mask = np.zeros((H, W), np.uint8); cv2.fillPoly(mask, [poly_px], 255)

    # model & tracker
    model = YOLO(args.model)
    tracker = CentroidTracker(max_disappeared=args.trk_max_miss, max_dist=args.trk_max_dist)

    target = 1.0 / args.fps if args.fps > 0 else 0
    prev = time.perf_counter()

    while True:
        ok, frame = cap.read()
        if not ok:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0); continue

        roi = frame[y:y+h, x:x+w]

        # sedikit upscale buat objek jauh/duduk
        scale_up = 1.5
        roi_big = cv2.resize(roi, None, fx=scale_up, fy=scale_up, interpolation=cv2.INTER_CUBIC)

        results = model.predict(
            roi_big, imgsz=args.imgsz, conf=args.conf, iou=args.iou, classes=[0], verbose=False
        )

        # kumpulkan bbox (global coords) yg centernya di dalam polygon
        det_bboxes = []
        for r in results:
            if r.boxes is None: continue
            for b in r.boxes:
                x1, y1, x2, y2 = map(int, b.xyxy[0])
                # scale back
                x1 = int(x1/scale_up); y1 = int(y1/scale_up)
                x2 = int(x2/scale_up); y2 = int(y2/scale_up)
                gx1, gy1, gx2, gy2 = x + x1, y + y1, x + x2, y + y2
                cx, cy = (gx1+gx2)//2, (gy1+gy2)//2
                if cv2.pointPolygonTest(poly_px, (cx, cy), False) >= 0:
                    det_bboxes.append((gx1, gy1, gx2, gy2))

        tracks = tracker.update(det_bboxes)

        # --- visualize ---
        vis = frame.copy()
        # shade di luar polygon
        vis[mask == 0] = (vis[mask == 0] * 0.35).astype(np.uint8)
        # polygon
        cv2.polylines(vis, [poly_px], True, (0, 255, 255), 2)

        for tid, obj in tracks.items():
            x1,y1,x2,y2 = obj["bbox"]
            cx, cy = obj["centroid"]
            # hanya gambar kalau masih dalam polygon (opsional)
            if cv2.pointPolygonTest(poly_px, (cx, cy), False) < 0:
                continue
            cv2.rectangle(vis, (x1,y1), (x2,y2), (0,255,0), 2)
            cv2.circle(vis, (cx,cy), 3, (0,255,0), -1)
            cv2.putText(vis, f"ID {tid}", (x1, y1-6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 2)

        # HUD
        ts = time.strftime("%d-%m-%Y %H:%M:%S")
        cv2.putText(vis, f"{Path(args.model).name} | imgsz={args.imgsz} conf={args.conf:.2f} fps@{args.fps:.1f}",
                    (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 2)
        cv2.putText(vis, ts, (12, 46), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 2)

        atomic_write_jpeg(latest_path, vis, quality=70)

        if target > 0:
            now = time.perf_counter()
            dt = now - prev
            if dt < target:
                time.sleep(target - dt)
            prev = time.perf_counter()

if __name__ == "__main__":
    main()