-- Aktifkan PostGIS jika image postgis digunakan (aman kalau dipanggil berulang)
CREATE EXTENSION IF NOT EXISTS postgis;

-- Sumber video stream (m3u8/rtsp/mp4)
CREATE TABLE IF NOT EXISTS streams (
  stream_id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  source_url TEXT NOT NULL,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Area polygon per stream (pakai GeoJSON biar mudah di-API)
CREATE TABLE IF NOT EXISTS areas (
  area_id SERIAL PRIMARY KEY,
  stream_id INT NOT NULL REFERENCES streams(stream_id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  polygon_geojson JSONB NOT NULL,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Track = identitas jejak orang dari tracker
CREATE TABLE IF NOT EXISTS tracks (
  track_id BIGSERIAL PRIMARY KEY,
  stream_id INT NOT NULL REFERENCES streams(stream_id) ON DELETE CASCADE,
  tracker_name TEXT NOT NULL,              -- "bytetrack"/"kalman"/"centroid"
  first_seen TIMESTAMPTZ NOT NULL,
  last_seen TIMESTAMPTZ NOT NULL
);

-- Hasil deteksi per frame
CREATE TABLE IF NOT EXISTS detections (
  detection_id BIGSERIAL PRIMARY KEY,
  stream_id INT NOT NULL REFERENCES streams(stream_id) ON DELETE CASCADE,
  track_id BIGINT REFERENCES tracks(track_id) ON DELETE SET NULL,
  ts TIMESTAMPTZ NOT NULL,                 -- waktu proses frame
  frame_index BIGINT,
  class_label TEXT DEFAULT 'person',
  confidence REAL,
  bbox_x REAL NOT NULL,                    -- definisikan di README: normalized [0,1] atau pixel
  bbox_y REAL NOT NULL,
  bbox_w REAL NOT NULL,
  bbox_h REAL NOT NULL,
  centroid_x REAL,
  centroid_y REAL,
  inside_area BOOLEAN,
  area_id INT REFERENCES areas(area_id) ON DELETE SET NULL
);

-- Event crossing boundary polygon (enter/exit)
CREATE TABLE IF NOT EXISTS area_events (
  event_id BIGSERIAL PRIMARY KEY,
  stream_id INT NOT NULL REFERENCES streams(stream_id) ON DELETE CASCADE,
  area_id INT NOT NULL REFERENCES areas(area_id) ON DELETE CASCADE,
  track_id BIGINT REFERENCES tracks(track_id) ON DELETE SET NULL,
  ts TIMESTAMPTZ NOT NULL,
  direction TEXT NOT NULL CHECK (direction IN ('enter','exit'))
);

-- Agregasi per window (untuk response API cepat)
CREATE TABLE IF NOT EXISTS area_counts (
  count_id BIGSERIAL PRIMARY KEY,
  stream_id INT NOT NULL REFERENCES streams(stream_id) ON DELETE CASCADE,
  area_id INT NOT NULL REFERENCES areas(area_id) ON DELETE CASCADE,
  window_start TIMESTAMPTZ NOT NULL,
  window_end   TIMESTAMPTZ NOT NULL,
  enters INT NOT NULL DEFAULT 0,
  exits  INT NOT NULL DEFAULT 0,
  UNIQUE(stream_id, area_id, window_start, window_end)
);

-- Indeks penting
CREATE INDEX IF NOT EXISTS idx_detections_ts ON detections (ts);
CREATE INDEX IF NOT EXISTS idx_events_ts ON area_events (ts);
CREATE INDEX IF NOT EXISTS idx_counts_window ON area_counts (area_id, window_start, window_end);