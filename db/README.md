# 📂 Database Diagram – People Counting

## Entity Relationship Diagram (ERD)

```mermaid
erDiagram
  STREAMS ||--o{ AREAS : has
  STREAMS ||--o{ TRACKS : has
  STREAMS ||--o{ DETECTIONS : has
  STREAMS ||--o{ AREA_EVENTS : has
  STREAMS ||--o{ AREA_COUNTS : has

  AREAS ||--o{ DETECTIONS : optional match
  AREAS ||--o{ AREA_EVENTS : generates
  AREAS ||--o{ AREA_COUNTS : aggregates

  TRACKS ||--o{ DETECTIONS : explains
  TRACKS ||--o{ AREA_EVENTS : crosses

  STREAMS {
    int stream_id PK
    text name
    text source_url
    boolean is_active
    timestamptz created_at
  }

  AREAS {
    int area_id PK
    int stream_id FK
    text name
    jsonb polygon_geojson
    boolean is_active
    timestamptz created_at
    timestamptz updated_at
  }

  TRACKS {
    bigint track_id PK
    int stream_id FK
    text tracker_name
    timestamptz first_seen
    timestamptz last_seen
  }

  DETECTIONS {
    bigint detection_id PK
    int stream_id FK
    bigint track_id FK
    timestamptz ts
    bigint frame_index
    text class_label
    real confidence
    real bbox_x
    real bbox_y
    real bbox_w
    real bbox_h
    real centroid_x
    real centroid_y
    boolean inside_area
    int area_id FK
  }

  AREA_EVENTS {
    bigint event_id PK
    int stream_id FK
    int area_id FK
    bigint track_id FK
    timestamptz ts
    text direction
  }

  AREA_COUNTS {
    bigint count_id PK
    int stream_id FK
    int area_id FK
    timestamptz window_start
    timestamptz window_end
    int enters
    int exits
  }
