-- db/01_seed_streams.sql
INSERT INTO streams (name, url) VALUES
    ('Malioboro_10_Kepatihan',
    'https://cctvjss.jogjakota.go.id/malioboro/Malioboro_10_Kepatihan.stream/playlist.m3u8'),
    ('Malioboro_30_Pasar_Beringharjo',
    'https://cctvjss.jogjakota.go.id/malioboro/Malioboro_30_Pasar_Beringharjo.stream/playlist.m3u8'),
    ('NolKm_Utara',
    'https://cctvjss.jogjakota.go.id/malioboro/NolKm_Utara.stream/playlist.m3u8')
ON CONFLICT DO NOTHING;