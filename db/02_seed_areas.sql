BEGIN;

-- 1) Unique key sekali saja (aman jika sudah ada)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM   pg_constraint
    WHERE  conname = 'areas_stream_name_key'
  ) THEN
    ALTER TABLE areas
      ADD CONSTRAINT areas_stream_name_key UNIQUE (stream_id, name);
  END IF;
END$$;

-- 2) Area: Malioboro_10_Kepatihan (nama tetap 'polygon_area_1')
INSERT INTO areas (stream_id, name, polygon_geojson, is_active, created_at, updated_at)
SELECT
  s.stream_id,
  'polygon_area_1',
  $${
      "type":"Feature",
      "properties":{
          "name":"polygon_area_1",
          "coord_system":"image_norm",
          "image_size":[1920,1080],
          "source":"seed"
      },
      "geometry":{
          "type":"Polygon",
          "coordinates":[[
              [0.068577,0.433642],
              [0.094143,0.817039],
              [0.974762,0.651156],
              [0.956784,0.416962],
              [0.434357,0.437531],
              [0.345000,0.450000],
              [0.300000,0.500000],
              [0.250000,0.550000],
              [0.200000,0.600000],
              [0.068577,0.433642]
          ]]
      }
  }$$::jsonb,
  TRUE,
  NOW(),
  NOW()
FROM streams s
WHERE s.name = 'Malioboro_10_Kepatihan'
ON CONFLICT (stream_id, name)
DO UPDATE SET
  polygon_geojson = EXCLUDED.polygon_geojson,
  is_active       = EXCLUDED.is_active,
  updated_at      = NOW();

-- 3) Area: NolKm_Utara (nama tetap 'polygon_area_1')
INSERT INTO areas (stream_id, name, polygon_geojson, is_active, created_at, updated_at)
SELECT
  s.stream_id,
  'polygon_area_1',
  $${
      "type":"Feature",
      "properties":{
          "name":"polygon_area_1",
          "coord_system":"image_norm",
          "image_size":[1920,1080],
          "source":"seed"
      },
      "geometry":{
          "type":"Polygon",
          "coordinates":[[
              [0.0017,0.5663],
              [0.1046,0.4591],
              [0.1849,0.4085],
              [0.3188,0.3411],
              [0.4248,0.3129],
              [0.5369,0.2706],
              [0.7999,0.2997],
              [0.9995,0.5211],
              [0.9995,0.9980],
              [0.0011,0.9981],
              [0.0017,0.5663]
          ]]
      }
  }$$::jsonb,
  TRUE,
  NOW(),
  NOW()
FROM streams s
WHERE s.name = 'NolKm_Utara'
ON CONFLICT (stream_id, name)
DO UPDATE SET
  polygon_geojson = EXCLUDED.polygon_geojson,
  is_active       = EXCLUDED.is_active,
  updated_at      = NOW();

COMMIT;