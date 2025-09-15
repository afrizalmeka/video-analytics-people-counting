# workers/detect_track_count.py
import os, time, json, argparse
from pathlib import Path
import cv2
import numpy as np
from ultralytics import YOLO
import sys
from datetime import datetime, timezone

# Tambahkan REPO ROOT ke sys.path agar "workers.*" bisa diimport
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from workers.trackers.centroid import CentroidTracker

# ---------- DB loader (opsional) ----------
import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]  # repo root
load_dotenv(ROOT / ".env")

def _env(key, default=""):
    # Prioritas DB_* lalu fallback ke POSTGRES_*
    return os.getenv(key) or os.getenv(key.replace("DB_", "POSTGRES_")) or default

def load_polygon_from_db(stream_id: int, area_id: int):
    """
    Ambil polygon dari tabel areas (kolom polygon_geojson).
    GeoJSON Feature (geometry Polygon), koordinat ternormalisasi (0..1).
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


# ---------- DBLogger helper ----------
class DBLogger:
    """Helper untuk menulis ENTER/EXIT ke DB: area_events + agregasi per-menit ke area_counts (tanpa area_live)."""
    def __init__(self):
        self.conn = None
        self._connect()

    def _connect(self):
        try:
            self.conn = psycopg2.connect(
                host=_env("DB_HOST", "localhost"),
                port=_env("DB_PORT", "5432"),
                dbname=_env("DB_NAME", "people_counting"),
                user=_env("DB_USER", "postgres"),
                password=_env("DB_PASSWORD", ""),
            )
            self.conn.autocommit = True
        except Exception as e:
            print(f"[DB] connect failed: {e}")
            self.conn = None

    def _ensure(self):
        if self.conn is None:
            self._connect()
        return self.conn is not None

    def ensure_track(self, stream_id: int, track_id: int):
        if not self._ensure():
            return
        try:
            cur = self.conn.cursor()
            # Robust upsert dengan tracker_name default
            cur.execute(
                """
                INSERT INTO tracks (track_id, stream_id, tracker_name, first_seen, last_seen)
                VALUES (%s, %s, %s, NOW(), NOW())
                ON CONFLICT (track_id)
                DO UPDATE SET
                    last_seen    = EXCLUDED.last_seen,
                    stream_id    = COALESCE(tracks.stream_id, EXCLUDED.stream_id),
                    tracker_name = COALESCE(tracks.tracker_name, EXCLUDED.tracker_name)
                """,
                (int(track_id), int(stream_id), "centroid"),
            )
            cur.close()
        except Exception as e:
            print(f"[DB] ensure_track failed: {e}")
            try:
                self.conn.rollback()
            except Exception:
                pass

    def log_event_and_counts(self, stream_id: int, area_id: int, track_id: int, direction: str):
        """
        direction: 'enter' | 'exit'
        - Insert baris ke area_events (kolom: stream_id, area_id, track_id, ts, direction)
        - Upsert agregasi per-menit ke area_counts (kolom: window_start, window_end, enters, exits)
        """
        if not self._ensure():
            return
        try:
            # Pastikan row di tracks ada agar FK tidak gagal
            self.ensure_track(stream_id, track_id)
            cur = self.conn.cursor()
            # 1) Simpan event detail
            cur.execute(
                """
                INSERT INTO area_events (stream_id, area_id, track_id, ts, direction)
                VALUES (%s, %s, %s, NOW(), %s)
                """,
                (stream_id, area_id, int(track_id), direction),
            )

            # 2) Upsert per-menit ke area_counts
            #    window_start = awal menit sekarang, window_end = +1 menit
            cur.execute("SELECT date_trunc('minute', NOW())")
            (win_start,) = cur.fetchone()
            cur.execute("SELECT %s + interval '1 minute'", (win_start,))
            (win_end,) = cur.fetchone()

            if direction == 'enter':
                cur.execute(
                    """
                    INSERT INTO area_counts (stream_id, area_id, window_start, window_end, enters, exits)
                    VALUES (%s, %s, %s, %s, 1, 0)
                    ON CONFLICT (stream_id, area_id, window_start, window_end)
                    DO UPDATE SET enters = area_counts.enters + 1
                    """,
                    (stream_id, area_id, win_start, win_end),
                )
            elif direction == 'exit':
                cur.execute(
                    """
                    INSERT INTO area_counts (stream_id, area_id, window_start, window_end, enters, exits)
                    VALUES (%s, %s, %s, %s, 0, 1)
                    ON CONFLICT (stream_id, area_id, window_start, window_end)
                    DO UPDATE SET exits = area_counts.exits + 1
                    """,
                    (stream_id, area_id, win_start, win_end),
                )
            cur.close()
        except Exception as e:
            print(f"[DB] log_event_and_counts failed: {e}")
            try:
                if self.conn:
                    self.conn.rollback()
            except Exception:
                pass

    def upsert_live(self, stream_id: int, area_id: int, current_inside: int):
        if not self._ensure():
            return
        try:
            cur = self.conn.cursor()
            cur.execute("""
                INSERT INTO area_live (stream_id, area_id, current_inside, updated_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (stream_id, area_id)
                DO UPDATE SET current_inside = EXCLUDED.current_inside,
                              updated_at     = NOW()
            """, (int(stream_id), int(area_id), int(current_inside)))
            cur.close()
        except Exception as e:
            print(f"[DB] upsert_live failed: {e}")
            try:
                if self.conn:
                    self.conn.rollback()
            except Exception:
                pass


    def close(self):
        try:
            if self.conn:
                self.conn.close()
        except Exception:
            pass

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

# --- geometry helpers ---
def _ccw(A, B, C):
    return (C[1]-A[1])*(B[0]-A[0]) > (B[1]-A[1])*(C[0]-A[0])

def _seg_intersect(A, B, C, D):
    # True jika segmen AB memotong segmen CD
    return _ccw(A, C, D) != _ccw(B, C, D) and _ccw(A, B, C) != _ccw(A, B, D)

def crossed_boundary(p_prev, p_now, poly_px):
    """Return True jika garis p_prev→p_now memotong salah satu sisi polygon."""
    if p_prev is None or p_now is None:
        return False
    pts = poly_px.reshape(-1, 2)
    n = len(pts)
    for i in range(n):
        C = tuple(pts[i])
        D = tuple(pts[(i+1) % n])
        if _seg_intersect(tuple(p_prev), tuple(p_now), C, D):
            return True
    return False

def inside_with_margin(poly_px, pt, margin_px: float = 0.0):
    # gunakan measureDist=True agar dapat jarak signed; >=0 = inside/on-edge
    dist = cv2.pointPolygonTest(poly_px, pt, True)  # signed distance (px)
    return dist >= -float(margin_px)

# --- helper: rasio area bbox di dalam polygon (sampling grid) ---
def bbox_inside_ratio(poly_px, box, margin=0.0, grid=4):
    """
    Perkiraan rasio area bbox yang berada di dalam polygon.
    Sampling grid (grid x grid) dan hitung proporsi titik yg inside.
    box = (x1,y1,x2,y2)
    """
    x1, y1, x2, y2 = box
    x1 = max(int(x1), 0); y1 = max(int(y1), 0)
    x2 = int(x2); y2 = int(y2)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    gx = max(int(grid), 1); gy = gx
    inside = 0; total = gx * gy
    for i in range(gx):
        for j in range(gy):
            # sample di pusat sel grid
            sx = x1 + (i + 0.5) * (x2 - x1) / gx
            sy = y1 + (j + 0.5) * (y2 - y1) / gy
            if inside_with_margin(poly_px, (sx, sy), margin):
                inside += 1
    return inside / float(total)

# ---------- main ----------
def main():
    ap = argparse.ArgumentParser(description="Detection + Tracking + Counting in Polygon (MJPEG latest.jpg)")
    # Input video & output
    ap.add_argument("--video",
        default="https://cctvjss.jogjakota.go.id/malioboro/Malioboro_10_Kepatihan.stream/playlist.m3u8",
        help="mp4/rtsp/hls")
    ap.add_argument("--outdir",
        default="samples/output/malioboro-10-kepatihan")

    # Model & inferencing
    ap.add_argument("--model",
        default="yolov8m.pt",
        help="ultralytics model path (e.g., yolov8n.pt/yolov8l.pt)")
    ap.add_argument("--imgsz",
        type=int,
        default=960)
    ap.add_argument("--conf",
        type=float,
        default=0.15)
    ap.add_argument("--fps",
        type=int,
        default=8,
        help="target output FPS to latest.jpg")
    ap.add_argument("--frame-skip",
        type=int,
        default=0,
        help="skip N frames between inference")
    ap.add_argument("--roi-scale",
        type=float,
        default=1.0,
        help="scale bbox(ROI) padding multiplier (>=1.0)")
    ap.add_argument("--roi-upscale",
        type=float,
        default=1.0,
        help="upscale ROI before YOLO (1.0 = off)")

    ap.add_argument("--poly-pad",
        type=int,
        default=0,
        help="expand polygon outward in pixels")

    # DB / polygon
    ap.add_argument("--stream-id",
        type=int,
        default=1)
    ap.add_argument("--area-id",
        type=int,
        default=1)
    ap.add_argument("--poly",
        default="",
        help="JSON list [[x_norm,y_norm],...] if not using DB")
    ap.add_argument("--rider-iou-th",
        type=float,
        default=0.25,
        help="buang person yang overlap ≥ threshold dengan bicycle/motorcycle (indikasi rider)")
    ap.add_argument("--poly-margin",
        type=int,
        default=5,
        help="toleransi (px) untuk cek inside polygon agar tidak jitter")
    ap.add_argument("--debug-cross",
        action="store_true",
        help="print log crossing (px,py)->(cx,cy) dan hasil crossed_boundary")
    ap.add_argument("--cross-margin",
        type=int,
        default=8,
        help="toleransi (px) saat menentukan crossing: dekat tepi dianggap lintas")
    ap.add_argument("--db-log",
        action="store_true",
        help="tulis ENTER/EXIT ke tabel area_events (butuh stream-id & area-id)")

    # Hysteresis & confirm logic
    ap.add_argument("--in-ratio-in",
        type=float,
        default=0.6,
        help="rasio bbox di dalam polygon agar dianggap INSIDE (hysteresis: ambang masuk)")
    ap.add_argument("--in-ratio-out",
        type=float,
        default=0.4,
        help="rasio bbox di dalam polygon di bawah ini dianggap OUTSIDE (hysteresis: ambang keluar)")
    ap.add_argument("--confirm-frames",
        type=int,
        default=2,
        help="ENTER/EXIT dihitung setelah kondisi terpenuhi N frame berturut-turut")
    ap.add_argument("--cross-delta",
        type=float,
        default=6.0,
        help="minimal selisih jarak ke tepi (px) agar crossing dianggap valid (hindari 'menyentuh' garis)")
    
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    latest_path = os.path.join(args.outdir, "latest.jpg")

    # --- open video ---
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
        if args.stream_id is None or args.area_id is None:
            raise SystemExit("Berikan --poly atau (--stream-id dan --area-id) untuk ambil dari DB")
        poly_norm, coord_sys = load_polygon_from_db(args.stream_id, args.area_id)

    if not poly_norm:
        raise SystemExit("Polygon tidak tersedia. Pastikan di DB atau arg --poly terisi.")

    if coord_sys != "image_norm":
        print(f"[WARN] coord_system={coord_sys} belum didukung, diasumsikan image_norm 0..1")

    poly_px = poly_norm_to_px(poly_norm, W, H)

    # polygon padding (opsional): melebar pakai dilate mask
    if args.poly_pad and args.poly_pad > 0:
        m = np.zeros((H, W), np.uint8)
        cv2.fillPoly(m, [poly_px], 255)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (args.poly_pad*2+1, args.poly_pad*2+1))
        m = cv2.dilate(m, k, iterations=1)
        cnts,_ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if cnts:
            poly_px = max(cnts, key=cv2.contourArea)

    # ROI bounding box dari polygon
    x, y, w, h = cv2.boundingRect(poly_px)

    # ROI scale (padding di sekeliling bbox)
    if args.roi_scale and args.roi_scale > 1.0:
        cx, cy = x + w/2, y + h/2
        nw, nh = int(w * args.roi_scale), int(h * args.roi_scale)
        x = max(int(cx - nw/2), 0); y = max(int(cy - nh/2), 0)
        w = min(nw, W - x); h = min(nh, H - y)

    # mask untuk gelapkan luar polygon
    mask = np.zeros((H, W), np.uint8)
    cv2.fillPoly(mask, [poly_px], 255)

    dblogger = DBLogger() if args.db_log else None

    # --- model & tracker ---
    model = YOLO(args.model)
    tracker = CentroidTracker(max_distance=60, max_miss=40)  # silakan tuning

    # --- counting state ---
    inside_state = {}
    prev_pos = {}
    enter_count, exit_count = 0, 0
    current_inside_ids = set()
    entered_ids, exited_ids = set(), set()
    enter_streak, exit_streak = {}, {}

    # pacing & loop
    target_dt = 1.0 / args.fps if args.fps > 0 else 0
    prev_tick = time.perf_counter()
    frame_idx = 0
    fps_ema = 0.0
    ema_alpha = 0.2
    loop_prev = time.perf_counter()

    while True:
        ok, frame = cap.read()
        if not ok:
            # reset state ketika loop ulang video MP4
            inside_state.clear()
            prev_pos.clear()
            current_inside_ids.clear()
            entered_ids.clear()
            exited_ids.clear()
            enter_count = 0
            exit_count  = 0
            # enter/exit BIARKAN cumulative (sesuai kebutuhan laporan); kalau mau reset, kosongkan juga set & counter
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            continue
        frame_idx += 1

        vis = frame.copy()

        # ambil ROI dari bbox polygon
        roi = frame[y:y+h, x:x+w]
        infer_img = roi

        # (opsional) upscale ROI agar objek kecil lebih “terlihat”
        if args.roi_upscale and args.roi_upscale > 1.0:
            infer_img = cv2.resize(
                roi, None, fx=args.roi_upscale, fy=args.roi_upscale, interpolation=cv2.INTER_CUBIC
            )

        # frame skipping (simple throttle)
        do_infer = True
        if args.frame_skip > 0 and (frame_idx % (args.frame_skip + 1)) != 1:
            do_infer = False

        detections = []
        if do_infer:
            # 0=person, 1=bicycle, 3=motorcycle (dataset COCO)
            results = model.predict(
                infer_img, imgsz=args.imgsz, conf=args.conf, classes=[0, 1, 3], iou=0.5, verbose=False
            )

            persons, riders = [], []  # riders = gabungan bbox bicycle & motorcycle (proxy untuk pemotor/pesepeda)

            for r in results:
                if r.boxes is None:
                    continue
                for b in r.boxes:
                    cls = int(b.cls[0])
                    x1, y1, x2, y2 = map(int, b.xyxy[0])

                    # scale back jika ROI di-upscale
                    if args.roi_upscale and args.roi_upscale > 1.0:
                        s = args.roi_upscale
                        x1 = int(x1 / s); y1 = int(y1 / s)
                        x2 = int(x2 / s); y2 = int(y2 / s)

                    # koordinat global
                    gx1, gy1, gx2, gy2 = x + x1, y + y1, x + x2, y + y2

                    if cls == 0:  # person
                        persons.append((gx1, gy1, gx2, gy2, float(b.conf[0])))
                    elif cls in (1, 3):  # bicycle atau motorcycle
                        riders.append((gx1, gy1, gx2, gy2))

            # fungsi IoU sederhana
            def iou(a, b):
                ax1, ay1, ax2, ay2 = a[:4]; bx1, by1, bx2, by2 = b[:4]
                inter_x1, inter_y1 = max(ax1, bx1), max(ay1, by1)
                inter_x2, inter_y2 = min(ax2, bx2), min(ay2, by2)
                iw, ih = max(0, inter_x2 - inter_x1), max(0, inter_y2 - inter_y1)
                inter = iw * ih
                if inter <= 0:
                    return 0.0
                area_a = (ax2 - ax1) * (ay2 - ay1)
                area_b = (bx2 - bx1) * (by2 - by1)
                return inter / (area_a + area_b - inter + 1e-6)

            # buang 'person' yang overlap signifikan dengan kendaraan (indikasi rider)
            clean_persons = []
            for p in persons:
                max_iou = max((iou(p, r) for r in riders), default=0.0)
                if max_iou < args.rider_iou_th:
                    clean_persons.append(p)

            # simpan hanya person yang lolos filter + berada di dalam polygon
            for gx1, gy1, gx2, gy2, _conf in clean_persons:
                # (opsional) pakai bottom-center utk lebih stabil menyentuh ground
                cx = (gx1 + gx2) // 2
                cy = gy2  # bottom-center y
                detections.append({
                    "x1": gx1, "y1": gy1, "x2": gx2, "y2": gy2,
                    "cx": cx, "cy": cy
                })

        # update tracking (tracker boleh handle empty → decay)
        tracked = tracker.update(detections)

        # bangun ulang daftar ID yang benar-benar masih "inside" untuk frame ini
        new_inside_ids = set()

        for t in tracked:
            tid, cx, cy = t["id"], t["cx"], t["cy"]  # pakai cx,cy dari bottom-center
            # Revert: gunakan centroid + margin saja untuk status inside
            prev_inside = inside_state.get(tid, False)
            is_inside = inside_with_margin(poly_px, (cx, cy), args.poly_margin)

            # ambil posisi sebelumnya
            px, py = prev_pos.get(tid, (cx, cy))
            crossed = crossed_boundary((px, py), (cx, cy), poly_px)

            # jarak bertanda ke tepi utk prev & now (px)
            dist_now = cv2.pointPolygonTest(poly_px, (cx, cy), True)

            prev_dist = None
            if tid in prev_pos:
                px, py = prev_pos[tid]
                prev_dist = cv2.pointPolygonTest(poly_px, (px, py), True)

            # state berubah?
            state_changed = (prev_inside != is_inside)

            # crossing berbasis geometri garis ATAU berbasis jarak/toleransi di tepi (tanpa delta)
            crossing_simple = False
            if prev_dist is not None:
                sign_flip = (prev_dist <= 0 < dist_now) or (prev_dist >= 0 > dist_now)
                near_edge = (abs(prev_dist) <= args.cross_margin) or (abs(dist_now) <= args.cross_margin)
                crossing_simple = state_changed and (sign_flip or near_edge)

            # final keputusan crossing
            crossing_ok = crossed or crossing_simple

            # ENTER: outside -> inside
            if not prev_inside and is_inside and crossing_ok and tid not in entered_ids:
                enter_count += 1
                entered_ids.add(tid)
                # DB log + counts
                if dblogger and args.stream_id is not None and args.area_id is not None:
                    dblogger.log_event_and_counts(args.stream_id, args.area_id, tid, 'enter')

            # EXIT: inside -> outside
            if prev_inside and not is_inside and crossing_ok and tid not in exited_ids:
                exit_count += 1
                exited_ids.add(tid)
                # DB log + counts
                if dblogger and args.stream_id is not None and args.area_id is not None:
                    dblogger.log_event_and_counts(args.stream_id, args.area_id, tid, 'exit')

            # (opsional) debug yang lebih informatif
            if args.debug_cross and (crossed or state_changed or frame_idx % 30 == 0):
                print(
                    f"[cross] id={tid} prev=({px:.0f},{py:.0f}) now=({cx:.0f},{cy:.0f}) "
                    f"prev_dist={prev_dist if prev_dist is not None else 'NA'} now_dist={dist_now:.2f} "
                    f"inside_prev={prev_inside} inside_now={is_inside} "
                    f"seg_crossed={crossed} simple_cross={crossing_simple} => crossing_ok={crossing_ok}"
                )

            # update state (tetap SETELAH keputusan enter/exit)
            inside_state[tid] = is_inside
            prev_pos[tid] = (cx, cy)

            if is_inside:
                new_inside_ids.add(tid)

            # draw bbox + id (tetap)
            cv2.rectangle(vis, (t["x1"], t["y1"]), (t["x2"], t["y2"]), (0, 255, 0), 2)
            cv2.putText(vis, f"ID {tid}", (t["x1"], t["y1"] - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

        # replace set aktif
        current_inside_ids = new_inside_ids
        current_inside = len(current_inside_ids)

        # Upsert live occupancy ke DB (opsional)
        if dblogger and args.db_log and args.stream_id is not None and args.area_id is not None:
            dblogger.upsert_live(args.stream_id, args.area_id, current_inside)


        # ---------- D) Housekeeping ----------
        active_ids = {t["id"] for t in tracked}

        for tid in list(inside_state.keys()):
            if tid not in active_ids:
                inside_state.pop(tid, None)
                prev_pos.pop(tid, None)
                enter_streak.pop(tid, None)
                exit_streak.pop(tid, None)

        current_inside_ids.intersection_update(active_ids)

        # overlay polygon & gelapkan luar area
        cv2.polylines(vis, [poly_px], True, (0, 255, 255), 2)
        vis[mask == 0] = (vis[mask == 0] * 0.35).astype(np.uint8)

        # counter overlay
        cv2.putText(vis, f"ENTER={enter_count} EXIT={exit_count} INSIDE={current_inside}",
                (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

        # --- tambahan log ke terminal ---
        print(f"[Frame {frame_idx}] ENTER={enter_count} EXIT={exit_count} INSIDE={current_inside}")

        # update runtime FPS EMA
        now_loop = time.perf_counter()
        dt_loop = now_loop - loop_prev
        if dt_loop > 0:
            fps_ema = (1 - ema_alpha) * fps_ema + ema_alpha * (1.0 / dt_loop)
        loop_prev = now_loop

        # info kecil
        cv2.putText(vis, f"{Path(args.model).name} img{args.imgsz} conf={args.conf:.2f} "
                         f"fpsSet={args.fps:.1f} fpsRun={fps_ema:.1f} skip={args.frame_skip} "
                         f"roiScale={args.roi_scale} up={args.roi_upscale}",
                    (12, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)

        # tulis latest.jpg (atomic)
        atomic_write_jpeg(latest_path, vis, quality=70)

        # pace output (agar MJPEG stabil & tak berkedip)
        if target_dt > 0:
            now = time.perf_counter()
            dt = now - prev_tick
            if dt < target_dt:
                time.sleep(target_dt - dt)
            prev_tick = time.perf_counter()

    try:
        if args.db_log and 'dblogger' in locals() and dblogger:
            dblogger.close()
    except Exception:
        pass

if __name__ == "__main__":
    main()