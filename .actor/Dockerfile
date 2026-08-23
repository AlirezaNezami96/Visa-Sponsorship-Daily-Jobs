# .actor/Dockerfile
# API-ONLY, PRODUCTION-GRADE DOCKERFILE (NO PLAYWRIGHT, NO BROWSER OVERHEAD)

FROM python:3.12-slim

# Install system dependencies (minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy minimal Actor requirements
COPY .actor/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared core, scripts, and project configuration
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY pyproject.toml ./

# Copy Apify Actor wrapper and metadata
COPY apify_actor/ ./apify_actor/
COPY .actor/ ./.actor/

# Copy curated sponsor and company data (root and data/ paths)
COPY data/ ./data/
COPY companies*.json remote_companies*.json ai_companies*.json ./

# Bake official sponsor database into the image
RUN python scripts/build_sponsors_db.py

# Install the package in editable mode without pulling heavy optional dev dependencies
RUN pip install --no-cache-dir -e . --no-deps

# Set environment
ENV PYTHONPATH=/app
ENV APIFY_DISABLE_BROWSER=true
ENV SCRAPER_DISABLE_BROWSER=true

# Run the Actor entrypoint
CMD ["python", "-m", "apify_actor.main"]
