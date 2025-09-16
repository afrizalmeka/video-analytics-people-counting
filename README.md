# Video Analytics People Counting

## Project Overview
Proyek ini adalah sistem video analytics untuk **mendeteksi, melacak, dan menghitung orang** (people counting) secara real‑time dari video feed. Sistem memanfaatkan computer vision dan deep learning untuk mengidentifikasi individu serta menghitung pergerakan **masuk/keluar area berisiko (polygon)**. Implementasi dan pengujian difokuskan pada **keramaian di koridor Malioboro–Kepatihan**, sehingga dapat dipakai untuk manajemen kerumunan, keamanan, maupun analitik pejalan kaki.

## Cara Menjalankan dengan Docker
Untuk menjalankan proyek ini menggunakan Docker, ikuti langkah-langkah berikut:

1. Pastikan Docker sudah terinstall di sistem Anda.
2. Clone repository ini:
   ```
   git clone https://github.com/afrizalmeka/video-analytics-people-counting.git
   cd video-analytics-people-counting
   ```
3. Build dan jalankan container dengan docker compose:
   ```
   docker compose up --build -d
   docker compose logs -f
   ```
4. Akses aplikasi melalui:  
   - API base: `http://localhost:8000`  
   - Dashboard: `http://localhost:8000/` (root men-serve `dashboard/index.html`)

## Struktur Direktori
```
video-analytics-people-counting/
├── backend/
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes_stream.py
│   └── __init__.py
├── dashboard/
│   └── index.html
├── db/
│   ├── 00_schema.sql
│   ├── 01_seed_streams.sql
│   ├── 02_seed_areas.sql
│   └── README.md
├── samples/
│   ├── output/
│   ├── ffmpeg_extract.sh
│   └── README.md
├── workers/
│   ├── trackers/
│   ├── detect_in_polygon.py
│   ├── detect_track_count.py
│   ├── worker_detect_polygon.py
│   ├── worker_dummy_mjpeg.py
│   └── worker_track_polygon.py
├── app.py
├── docker-compose.yml
├── Dockerfile
├── README.md
├── requirements.txt
├── yolov8l.pt
├── yolov8m.pt
├── yolov8n.pt
└── yolov8s.pt
```

## Database
Detail sumber video/stream, contoh seed, dan cara menambah stream/area ada di **[db/README.md](https://github.com/afrizalmeka/video-analytics-people-counting/blob/master/db/README.md)**. Silakan lihat dokumen tersebut untuk skema tabel, seed awal (`01_seed_streams.sql`, `02_seed_areas.sql`), serta petunjuk update konfigurasi.

## System Design
Sistem ini terdiri dari beberapa komponen utama:

- **Video Input Module**: *komponen pengujian awal* (`workers/worker_dummy_mjpeg.py`, `workers/worker_detect_polygon.py`, `workers/worker_track_polygon.py`) untuk memastikan alur frame dan viewer. Modul-modul ini membaca stream/file via OpenCV (`cv2.VideoCapture`) dan memancarkan MJPEG untuk uji cepat; *pada implementasi utama pipeline berpindah ke* `workers/detect_track_count.py`.
- **Detection + Tracking + Counting (utama)** (`workers/detect_track_count.py`):
  - **Deteksi**: menggunakan Ultralytics YOLOv8 (model `yolov8n/s/m/l.pt`) untuk kelas person (COCO id 0).
  - **Ekstraksi centroid**: ambil titik pusat bbox tiap deteksi untuk keperluan asosiasi.
  - **Tracking**: Centroid Tracker untuk penugasan ID antar-frame.
  - **Counting**: status inside/outside polygon dihitung dengan Shapely (Polygon.contains/intersects). Transisi outside→inside = ENTER, inside→outside = EXIT. Nilai current_inside diupdate; event disimpan ke DB (`area_events`, agregat `area_counts`) via psycopg2-binary.
- **Counting Module** (`workers/detect_in_polygon.py`): menghitung **ENTER/EXIT** berdasarkan transisi posisi track terhadap **area polygon**. Cek titik/box di dalam polygon memakai **Shapely** (`shapely.geometry.Polygon`, `contains`/`intersects`). Event dicatat sebagai `area_events`, agregat disimpan di `area_counts`.
- **API Server** (`app.py`, `backend/api`, `routes_stream.py`): **FastAPI + Uvicorn** untuk mengekspor:
  - `GET /api/stream/mjpeg?stream_id={id}` → stream MJPEG.
  - `GET /api/stats/?stream_id={id}&area_id={id}&limit={n}` → daftar event ENTER/EXIT terbaru.
  - `GET /api/stats/live?stream_id={id}&area_id={id}` → ringkasan `current_inside` dan timestamp update.
  - (Opsional) `POST /api/config/area` → ubah koordinat polygon secara dinamis.
- **Dashboard** (`dashboard/index.html`): halaman HTML statis menampilkan **KPI Inside Now**, **Enters/Exits (15m)**, **Net Flow**, grafik **Enter/Exit per menit** (Chart.js), tabel **Recent Events**, serta viewer MJPEG yang memanggil `GET /api/stream/mjpeg`.

## API Endpoints
| Endpoint                     | Method | Query/Body                                    | Deskripsi                                                                 |
|-----------------------------|--------|-----------------------------------------------|---------------------------------------------------------------------------|
| `/api/stream/mjpeg`         | GET    | `stream_id`                                   | Mengirim stream MJPEG untuk viewer/dashboard.                             |
| `/api/stats/`               | GET    | `stream_id`, `area_id`, `limit`, (`from`,`to` opsional) | Riwayat event ENTER/EXIT terurut waktu (terbaru dulu).                    |
| `/api/stats/live`           | GET    | `stream_id`, `area_id`                        | Ringkasan terbaru: `current_inside`, `updated_at`.                        |
| `/api/config/area` (opsional)| POST  | JSON `{ "area_id": int, "coords": [[x,y],...] }` | Update koordinat polygon secara dinamis (jika fitur diaktifkan).          |

### Pengujian API via Swagger UI

FastAPI otomatis menyediakan dokumentasi interaktif melalui Swagger UI.  
Untuk menguji API tanpa dashboard:

1. Jalankan container (jika sudah di awal tadi tidak perlu jalankan):
   ```bash
   docker compose up --build -d
   ```
2. Akses Swagger UI di: [http://localhost:8000/docs](http://localhost:8000/docs)
3. Pilih endpoint yang ingin diuji, misalnya:
   - **GET /api/stats/live** → isi parameter `stream_id` dan `area_id`, lalu klik "Execute".
   - **GET /api/stats/** → masukkan `stream_id`, `area_id`, serta `limit` atau rentang waktu (`from`, `to`).
   - **POST /api/config/area** (jika diaktifkan) → kirim JSON body dengan koordinat polygon baru.

4. Swagger akan menampilkan response JSON langsung sehingga mudah divalidasi.

#### Nilai Parameter untuk Uji Cepat (agar pasti jalan)
Gunakan nilai berikut saat mencoba di Swagger:
- **GET /api/stats/live** → `stream_id=1`, `area_id=1`
- **GET /api/stats/** → `stream_id=1`, `area_id=1`, `limit=100` (nilai `limit` bebas)

Contoh cURL:
```bash
curl "http://localhost:8000/api/stats/live?stream_id=1&area_id=1"
curl "http://localhost:8000/api/stats/?stream_id=1&area_id=1&limit=100"
```

> Catatan: ID di atas mengikuti seed default pada **db/README.md**. Jika Anda mengubah seed/konfigurasi, sesuaikan `stream_id`/`area_id`-nya.

## Dashboard
Dashboard di-root pada `/` dan di-serve dari `dashboard/index.html`. Fitur:
- Viewer MJPEG: `<img src="/api/stream/mjpeg?stream_id=1" />`
- KPI cards: Inside Now, Enters (15m), Exits (15m), Net Flow (15m)
- Chart Enter/Exit per menit (60 menit terakhir) dengan **Chart.js**
- Tabel Recent Events (maks. 50 baris)

Dashboard melakukan polling ke:
- `GET /api/stats/live?stream_id=1&area_id=1` (interval 3s)
- `GET /api/stats/?limit=400&stream_id=1&area_id=1` (interval 12s)

## Checklist Fitur
1. Desain Database (Done)  
   Kendala: –
2. Pengumpulan Dataset (Done)  
   Kendala: Akses live stream terbatas → gunakan fallback video statis.
3. Object Detection & Tracking (Done)  
   Kendala: FPS rendah di CPU-only; tracking kurang stabil pada crowd padat.
4. Counting & Polygon Area (Done)  
   Kendala: Tuning threshold untuk transisi ENTER/EXIT.
5. Prediksi (Forecasting) (X)  
   Kendala: Fitur tidak dikerjakan pada versi ini.
6. Integrasi API (API/Front End) (Done)  
   Kendala: – 
7. Deployment (Done)  
   Kendala: Perlu port 8000 bebas; environment `.env` wajib terisi.

## Kendala
- Kinerja terpengaruh saat dijalankan tanpa GPU (CPU-only), menyebabkan FPS rendah dan latency lebih tinggi.
- Ketelitian tracking menurun pada skenario kerumunan padat dan occlusion tinggi.
- Parameter polygon/threshold perlu penyesuaian per lokasi kamera agar akurat.

## Credits
- Model deteksi: **Ultralytics YOLOv8** (`yolov8n.pt`, `yolov8s.pt`, `yolov8m.pt`, `yolov8l.pt`) pretrained pada COCO.
- Framework: FastAPI, Uvicorn, OpenCV, Shapely, PostgreSQL (psycopg2), Docker.
- Kontributor: **Afrizal Meka Mulyana** — [LinkedIn](https://www.linkedin.com/in/afrizalmeka/).

Terima kasih telah menggunakan proyek ini! Silakan hubungi kami untuk pertanyaan atau kontribusi lebih lanjut.
