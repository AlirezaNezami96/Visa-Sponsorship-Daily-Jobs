FROM python:3.12-slim

# WeasyPrint system dependencies (Pango, Cairo, GLib)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    libssl-dev \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer cache)
COPY engine/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy engine source
COPY engine/ ./engine/

# Create PDF output dir
RUN mkdir -p /tmp/engine_docs

EXPOSE 8000

CMD ["uvicorn", "engine.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
