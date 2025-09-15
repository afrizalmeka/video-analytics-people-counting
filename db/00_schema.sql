-- 00_schema.sql (UPDATED)
-- Skema database untuk sistem People Counting

BEGIN;

-- ========== streams ==========
CREATE TABLE IF NOT EXISTS streams (
    stream_id   SERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    url         TEXT,
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

-- ========== areas ==========
CREATE TABLE IF NOT EXISTS areas (
    area_id         SERIAL PRIMARY KEY,
    stream_id       INTEGER NOT NULL REFERENCES streams(stream_id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    polygon_geojson JSONB NOT NULL,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- ========== tracks ==========
CREATE TABLE IF NOT EXISTS tracks (
    track_id   BIGSERIAL PRIMARY KEY,
    stream_id  INTEGER NOT NULL REFERENCES streams(stream_id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- ========== detections ==========
CREATE TABLE IF NOT EXISTS detections (
    detection_id BIGSERIAL PRIMARY KEY,
    stream_id    INTEGER NOT NULL REFERENCES streams(stream_id) ON DELETE CASCADE,
    area_id      INTEGER REFERENCES areas(area_id) ON DELETE SET NULL,
    track_id     BIGINT REFERENCES tracks(track_id) ON DELETE SET NULL,
    ts           TIMESTAMPTZ NOT NULL DEFAULT now(),
    x1           INTEGER,
    y1           INTEGER,
    x2           INTEGER,
    y2           INTEGER,
    conf         REAL
);

-- ========== area_events ==========
CREATE TABLE IF NOT EXISTS area_events (
    event_id   BIGSERIAL PRIMARY KEY,
    stream_id  INTEGER NOT NULL REFERENCES streams(stream_id) ON DELETE CASCADE,
    area_id    INTEGER NOT NULL REFERENCES areas(area_id) ON DELETE CASCADE,
    track_id   BIGINT REFERENCES tracks(track_id) ON DELETE SET NULL,
    ts         TIMESTAMPTZ NOT NULL,
    direction  TEXT NOT NULL CHECK (direction IN ('enter','exit'))
);
CREATE INDEX IF NOT EXISTS idx_area_events_ts ON area_events(ts);

-- ========== area_counts ==========
CREATE TABLE IF NOT EXISTS area_counts (
    count_id     BIGSERIAL PRIMARY KEY,
    stream_id    INTEGER NOT NULL REFERENCES streams(stream_id) ON DELETE CASCADE,
    area_id      INTEGER NOT NULL REFERENCES areas(area_id) ON DELETE CASCADE,
    window_start TIMESTAMPTZ NOT NULL,
    window_end   TIMESTAMPTZ NOT NULL,
    enters       INTEGER NOT NULL DEFAULT 0,
    exits        INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT area_counts_stream_id_area_id_window_start_window_end_key
        UNIQUE (stream_id, area_id, window_start, window_end)
);
CREATE INDEX IF NOT EXISTS idx_area_counts_window ON area_counts(area_id, window_start, window_end);

COMMIT;