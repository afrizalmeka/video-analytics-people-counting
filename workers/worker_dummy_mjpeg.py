import os, time, argparse, cv2

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True, help="input video file / rtsp / hls")
    ap.add_argument("--outdir", default="samples/output/nolkm-utara")
    ap.add_argument("--fps", type=float, default=8.0, help="target fps output")
    ap.add_argument("--scale", type=float, default=1.0, help="resize factor (0–1), mis. 0.5 = setengah ukuran")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    latest_path = os.path.join(args.outdir, "latest.jpg")

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        raise SystemExit("Gagal buka video/stream")

    target = 1.0 / args.fps if args.fps > 0 else 0
    prev = time.perf_counter()

    while True:
        ok, frame = cap.read()
        if not ok:
            # loop untuk file; untuk RTSP/HLS bisa diganti reconnect
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            continue

        # resize bila perlu
        if args.scale and 0 < args.scale < 1.0:
            nh, nw = int(frame.shape[0] * args.scale), int(frame.shape[1] * args.scale)
            frame = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)

        # overlay kecil (opsional)
        cv2.putText(frame, f"dummy@{args.fps:.1f}fps", (12, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,0), 2)

        # === simpan sebagai latest.jpg (ATOMIC WRITE) ===
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
        if ok:
            tmp_path = latest_path + ".tmp"
            with open(tmp_path, "wb") as f:
                f.write(buf.tobytes())
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, latest_path)   # atomic di POSIX
        # ================================================

        # sinkronisasi pace fps stabil
        if target > 0:
            now = time.perf_counter()
            dt = now - prev
            if dt < target:
                time.sleep(target - dt)
            prev = time.perf_counter()

if __name__ == "__main__":
    main()
