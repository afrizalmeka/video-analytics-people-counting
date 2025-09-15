# Dockerfile
FROM python:3.11-slim

ENV TZ=Asia/Jakarta \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 ffmpeg libpq5 curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# ⬇️ penting: masukkan seluruh source ke image
COPY . .

ENV PYTHONPATH=/app
CMD ["uvicorn","app:app","--host","0.0.0.0","--port","8080"]

# opsional: cache untuk ultralytics
RUN mkdir -p /app/.cache/ultralytics