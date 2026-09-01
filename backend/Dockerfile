# GrantRx Backend — Production Dockerfile
#
# Slim Python base with Playwright/Chromium runtime for the scraper pipeline.
# Compatible with Render, Fly.io, Railway, and standard container orchestrators.

FROM python:3.12-slim AS base

# ---------------------------------------------------------------------------
# System dependencies
# ---------------------------------------------------------------------------
# Playwright/Chromium requires shared libraries that are not in slim images.
# We install them via Playwright's own dependency list for reliability.
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    fonts-liberation \
    libnss3 \
    libnspr4 \
    libdbus-1-3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libatspi2.0-0 \
    libwayland-client0 \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Python dependencies
# ---------------------------------------------------------------------------
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium browser
RUN playwright install chromium

# ---------------------------------------------------------------------------
# Application code
# ---------------------------------------------------------------------------
COPY . .

# Expose the port the app listens on (Render/Fly.io inject $PORT)
EXPOSE 8000
ENV PORT=8000

# Health check — hit the public /health endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f "http://localhost:${PORT:-8000}/health" || exit 1

# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
# Use shell form so ${PORT} is expanded at runtime.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
