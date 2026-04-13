FROM python:3.12-slim AS base

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# ─── Development stage ───────────────────────────────────────────────────────
FROM base AS development

# 1. Copy only the manifest — this layer is cached until pyproject.toml changes.
COPY pyproject.toml .

# 2. Create a minimal stub so setuptools can resolve the editable install
#    without needing the real source files yet.
RUN mkdir -p src/mcp_gateway && touch src/mcp_gateway/__init__.py

# 3. Install all dependencies (cached layer — only re-runs when pyproject.toml changes).
RUN pip install --no-cache-dir -e ".[dev]"

# 4. Copy actual source — overwrites the stub. Volume-mounted in docker-compose
#    so changes hot-reload without rebuilding.
COPY . .

CMD ["uvicorn", "mcp_gateway.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--reload-dir", "src"]

# ─── Production stage ────────────────────────────────────────────────────────
FROM base AS production

COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir .

RUN useradd --no-create-home --shell /bin/false appuser && \
    chown -R appuser:appuser /app
USER appuser

CMD ["uvicorn", "mcp_gateway.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
