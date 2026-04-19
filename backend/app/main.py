"""
Clinical Insight Engine — FastAPI Application Entry Point
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings

logger = structlog.get_logger(__name__)


# ── Lifespan (startup / shutdown) ────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("CIE backend starting", version="1.0.0", env=settings.log_level)
    yield
    logger.info("CIE backend shutting down")


# ── FastAPI instance ──────────────────────────────────────
app = FastAPI(
    title="Clinical Insight Engine API",
    description="AI-powered clinical research data analysis platform",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)


# ── CORS ──────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health Check ──────────────────────────────────────────
@app.get("/health", tags=["system"])
async def health_check():
    return JSONResponse(
        content={
            "status": "ok",
            "service": "backend",
            "version": "1.0.0",
            "timestamp": time.time(),
        }
    )


# ── API Routers (mounted in later phases) ─────────────────
# from app.api.v1 import data, workflows, analysis, visual_ref, templates, export
# app.include_router(data.router,       prefix="/api/v1", tags=["data"])
# app.include_router(workflows.router,  prefix="/api/v1", tags=["workflows"])
# app.include_router(analysis.router,   prefix="/api/v1", tags=["analysis"])
# app.include_router(visual_ref.router, prefix="/api/v1", tags=["visual_ref"])
# app.include_router(templates.router,  prefix="/api/v1", tags=["templates"])
# app.include_router(export.router,     prefix="/api/v1", tags=["export"])
