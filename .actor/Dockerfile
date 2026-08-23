# .actor/Dockerfile
# PRODUCTION IMAGE: API-only, NO Playwright, NO browser dependencies.
# This keeps compute costs near zero and margins high.

FROM python:3.12-slim

# Install system dependencies (minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the shared core
COPY src/ ./src/
COPY pyproject.toml ./

# Copy the Apify-specific code
COPY apify/ ./apify/
COPY .actor/ ./.actor/

# Copy curated company and visa data
COPY data/ ./data/

# Install the package in editable/production mode
RUN pip install --no-cache-dir -e .

# Set environment
ENV PYTHONPATH=/app
ENV APIFY_DISABLE_BROWSER=true
ENV SCRAPER_DISABLE_BROWSER=true

# Run the Actor
CMD ["python", "-m", "apify.main"]
