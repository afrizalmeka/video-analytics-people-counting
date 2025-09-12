#!/usr/bin/env bash
set -euo pipefail

command -v ffmpeg >/dev/null || { echo "ffmpeg belum terpasang"; exit 1; }

if [[ $# -lt 1 ]]; then
  echo "ERROR: isi URL HLS (.m3u8) sebagai argumen pertama."; exit 1
fi

URL="$1"; shift || true
NAME="sample"; DURATION=20; OUT_DIR="samples/output"; FPS=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name) NAME="$2"; shift 2;;
    --duration) DURATION="$2"; shift 2;;
    --fps) FPS="$2"; shift 2;;
    *) echo "Unknown arg: $1"; exit 1;;
  esac
done

SLUG="$(echo "$NAME" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | sed 's/^-//;s/-$//')"
DEST_DIR="${OUT_DIR}/${SLUG}"
mkdir -p "${DEST_DIR}"

VIDEO_PATH="${DEST_DIR}/${SLUG}.mp4"
META_PATH="${DEST_DIR}/meta.txt"

echo ">> Recording ${DURATION}s from: ${URL}"
echo ">> Output: ${VIDEO_PATH}"

ffmpeg -y -loglevel error \
  -reconnect 1 -reconnect_streamed 1 -reconnect_on_network_error 1 -reconnect_delay_max 2 \
  -rw_timeout 15000000 \
  -i "${URL}" -t "${DURATION}" \
  -c:v libx264 -preset veryfast -pix_fmt yuv420p -movflags +faststart \
  -c:a aac -shortest \
  "${VIDEO_PATH}"

{
  echo "url=${URL}"
  echo "name=${NAME}"
  echo "duration_s=${DURATION}"
  date -u +"captured_at=%Y-%m-%dT%H:%M:%SZ"
} > "${META_PATH}"

if [[ "${FPS}" != "0" ]]; then
  echo ">> Extracting frames @ ${FPS} fps"
  mkdir -p "${DEST_DIR}/frames"
  ffmpeg -y -loglevel error -i "${VIDEO_PATH}" -vf "fps=${FPS}" "${DEST_DIR}/frames/frame_%04d.jpg"
fi

echo ">> Done. Saved to: ${DEST_DIR}"
