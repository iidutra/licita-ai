FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (includes Tesseract for OCR)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    tesseract-ocr \
    tesseract-ocr-por \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/staticfiles

RUN python manage.py collectstatic --noinput || true

COPY entrypoint.sh entrypoint-worker.sh entrypoint-beat.sh /app/
RUN chmod +x /app/entrypoint.sh /app/entrypoint-worker.sh /app/entrypoint-beat.sh

CMD ["sh", "/app/entrypoint.sh"]
