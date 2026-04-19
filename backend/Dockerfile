# =========================================================
# Backend — FastAPI + Uvicorn (Python 3.11)
# Multi-stage: dev → prod
# =========================================================

# ── Stage 1: base ─────────────────────────────────────────
FROM python:3.11-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    libpq-dev \
 && rm -rf /var/lib/apt/lists/*

# ── Stage 2: deps ─────────────────────────────────────────
FROM base AS deps
COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install -r requirements.txt

# ── Stage 3: dev (volume mount, auto-reload) ──────────────
FROM deps AS dev
ENV PYTHONPATH=/app
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ── Stage 4: prod ─────────────────────────────────────────
FROM deps AS prod
ENV PYTHONPATH=/app
RUN addgroup --system --gid 1001 appgroup \
 && adduser  --system --uid 1001 --ingroup appgroup appuser
COPY --chown=appuser:appgroup . .
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
