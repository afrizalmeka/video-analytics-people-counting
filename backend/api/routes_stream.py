from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
import time, os

router = APIRouter(prefix="/api/stream")

BOUNDARY = "frame"

# mapping stream_id -> folder output worker
STREAM_OUTPUTS = {
    1: "samples/output/malioboro-10-kepatihan/latest.jpg",  # Malioboro_10_Kepatihan
    # 3: "samples/output/nolkm-utara/latest.jpg",             # NolKm_Utara
}

def mjpeg_generator(latest_path: str, target_fps: float = 8.0):
    delay = 1.0 / max(target_fps, 0.1)
    while True:
        try:
            with open(latest_path, "rb") as f:
                jpg = f.read()
        except FileNotFoundError:
            time.sleep(0.05)
            continue

        yield (
            b"--" + BOUNDARY.encode() + b"\r\n"
            b"Content-Type: image/jpeg\r\n"
            b"Content-Length: " + str(len(jpg)).encode() + b"\r\n\r\n"
        ) + jpg + b"\r\n"

        time.sleep(delay)

@router.get("/mjpeg")
def stream_mjpeg(stream_id: int = Query(..., description="ID stream video")):
    latest_path = STREAM_OUTPUTS.get(stream_id)
    if not latest_path:
        # fallback: kalau stream_id tidak dikenali
        latest_path = "samples/output/default/latest.jpg"

    headers = {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
    }
    return StreamingResponse(
        mjpeg_generator(latest_path, target_fps=8.0),
        media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY}",
        headers=headers,
    )