-- Seed polygon areas (NolKm_Utara only)
-- Format GeoJSON pakai koordinat ternormalisasi (x = col/1920, y = row/1080)
-- Ring ditutup (titik pertama diulang di akhir)

BEGIN;

WITH s AS (
    SELECT stream_id FROM streams WHERE name = 'NolKm_Utara' LIMIT 1
), up AS (
    UPDATE areas a
        SET polygon_geojson = $${
        "type":"Feature",
        "properties":{
            "name":"polygon_area_1",
            "coord_system":"image_norm",
            "image_size":[1920,1080],
            "source":"roboflow_manual"
        },
        "geometry":{
            "type":"Polygon",
            "coordinates":[[
            [0.158837,0.505552],
            [0.238943,0.445794],
            [0.355462,0.399546],
            [0.495236,0.344172],
            [0.630602,0.297182],
            [0.794125,0.340157],
            [0.879951,0.442702],
            [0.997423,0.615969],
            [0.999479,0.995654],
            [0.000000,0.996064],
            [0.000180,0.652784],
            [0.158837,0.505552]
            ]]
        }
        }$$::jsonb,
            is_active = TRUE,
            updated_at = NOW()
    FROM s
    WHERE a.stream_id = s.stream_id AND a.name = 'polygon_area_1'
    RETURNING a.area_id
)
INSERT INTO areas (stream_id, name, polygon_geojson, is_active)
SELECT s.stream_id,
        'polygon_area_1',
        $${
            "type":"Feature",
            "properties":{
            "name":"polygon_area_1",
            "coord_system":"image_norm",
            "image_size":[1920,1080],
            "source":"roboflow_manual"
            },
            "geometry":{
            "type":"Polygon",
            "coordinates":[[
                [0.158837,0.505552],
                [0.238943,0.445794],
                [0.355462,0.399546],
                [0.495236,0.344172],
                [0.630602,0.297182],
                [0.794125,0.340157],
                [0.879951,0.442702],
                [0.997423,0.615969],
                [0.999479,0.995654],
                [0.000000,0.996064],
                [0.000180,0.652784],
                [0.158837,0.505552]
            ]]
            }
        }$$::jsonb,
        TRUE
FROM s
WHERE NOT EXISTS (SELECT 1 FROM up);

COMMIT;