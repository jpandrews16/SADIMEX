FROM python:3.12-slim

# Fuentes DejaVu: las usa la hoja de referencia para rotular cada packshot
# con su código de SKU. Sin ellas Pillow cae a una fuente bitmap ilegible.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/gondola
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Railway inyecta PORT. El worker se despliega con el mismo Dockerfile
# cambiando el startCommand a: python -m gondola.app.worker
CMD ["sh", "-c", "uvicorn gondola.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
