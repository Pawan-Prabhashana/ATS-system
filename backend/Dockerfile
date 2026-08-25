# Catalist backend — container image for Render (Docker web service).
# Python 3.13 (broad manylinux wheel coverage for our deps) + the poppler
# system binaries that pdf2image needs to rasterize PDF pages to PNG.
FROM python:3.13-slim

# poppler-utils = pdftoppm/pdfinfo, required by pdf2image (PDF -> page images).
RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Install dependencies first so this layer caches across code changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code + the seed data the sample jobs are created from.
COPY app ./app
COPY sample_data ./sample_data

# Render injects $PORT and expects the process to bind 0.0.0.0:$PORT. Never
# hardcode the port; default to 8000 only for a bare local `docker run`.
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
