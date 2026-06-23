FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY sensei/ ./sensei/
RUN pip install --no-cache-dir -e ".[dev]"

# ── Production image ──────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Install runtime deps only
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl && \
    rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY --from=builder /app /app

# Create non-root user for security
RUN useradd -m -u 1000 sensei && chown -R sensei:sensei /app
USER sensei

EXPOSE 7000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=15s \
    CMD curl -f http://localhost:7000/health || exit 1

CMD ["uvicorn", "sensei.main:app", "--host", "0.0.0.0", "--port", "7000"]
