FROM python:3.12-slim AS base

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# ─── Development stage ───────────────────────────────────────────────────────
FROM base AS development

COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

COPY . .

CMD ["uvicorn", "mcp_gateway.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--reload-dir", "src"]

# ─── Production stage ────────────────────────────────────────────────────────
FROM base AS production

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY src/ src/

RUN useradd --no-create-home --shell /bin/false appuser && \
    chown -R appuser:appuser /app
USER appuser

CMD ["uvicorn", "mcp_gateway.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
