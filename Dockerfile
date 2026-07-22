FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app:/app/src \
    STATIC_DIR=/app/static \
    OUTPUT_DIR=/app/output \
    ASSETS_CACHE_DIR=/app/assets_cache \
    REDIS_URL=redis://redis:6379/0 \
    CELERY_RESULT_BACKEND=redis://redis:6379/1

WORKDIR /app

# System deps: ffmpeg (+ libx264) for MoviePy encoding, build tools for wheels.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libx264-dev \
        libsm6 \
        libxext6 \
        curl \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml README.md ./
COPY config ./config
COPY cli.py ./
COPY src ./src
COPY web ./web

RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install -e .

RUN mkdir -p /app/static /app/output /app/assets_cache

EXPOSE 8000

# Default command is the API + web studio; docker-compose overrides for the Celery worker.
CMD ["uvicorn", "src.youtube_pipeline.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
