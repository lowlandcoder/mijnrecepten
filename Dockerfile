# Container voor de MijnRecepten-backend.
# Bevat Tesseract met het Nederlandse taalpakket voor de tekstherkenning (OCR).
FROM python:3.12-slim

# Tesseract en het Nederlandse taalpakket installeren.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-nld \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY schraper.py .
COPY static/ ./static/

# Map voor database en foto's (wordt als volume gekoppeld).
RUN mkdir -p /app/data
VOLUME ["/app/data"]

EXPOSE 8000
CMD ["python", "app.py"]
