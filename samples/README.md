cat > samples/README.md <<'MD'
# Samples (FFmpeg Capture)

## Prasyarat
- FFmpeg terpasang (macOS: `brew install ffmpeg`, Ubuntu/Debian: `sudo apt-get install ffmpeg`)

## Rekam 20 detik dari stream
```bash
./samples/ffmpeg_extract.sh "https://cctvjss.jogjakota.go.id/malioboro/NolKm_Utara.stream/playlist.m3u8" \
  --name "NolKm_Utara" --duration 20