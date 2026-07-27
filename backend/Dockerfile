# Sensei backend.
#
# Packages are installed into a virtualenv at a fixed path rather than into the
# interpreter's own site-packages. That is not stylistic: the previous version
# copied `/usr/local/lib/python3.12/site-packages` by name, so any base-image
# bump left the packages in a directory the new interpreter does not search,
# and the image built successfully while being completely broken. Dependabot
# only ever rewrites the `FROM` lines, so that bug was guaranteed to recur.
#
# With a venv the Python version appears exactly once, in the ARG below.

ARG PYTHON_VERSION=3.13

FROM python:${PYTHON_VERSION}-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && \
    rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml ./
COPY sensei/ ./sensei/
RUN pip install --no-cache-dir .

# ── Production image ──────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl && \
    rm -rf /var/lib/apt/lists/*

# One self-contained tree, no version-numbered paths to keep in sync.
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app /app
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Create non-root user for security
RUN useradd -m -u 1000 sensei && chown -R sensei:sensei /app
USER sensei

EXPOSE 7000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=15s \
    CMD curl -f http://localhost:7000/health || exit 1

# 0.0.0.0 is correct *here* and only here: inside a container the isolation
# boundary is the container itself, and the port is published deliberately.
# The application default is 127.0.0.1 — see sensei/config.py.
CMD ["uvicorn", "sensei.main:app", "--host", "0.0.0.0", "--port", "7000"]
