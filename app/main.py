"""
app/main.py — FastAPI application entry point.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import enrich, status, internal
from app.api.schemas.responses import HealthResponse
from app.db.firebase import init_firebase
from app.utils.logging import get_logger, setup_logging

setup_logging()
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle handler."""
    log.info("Starting AI Lead Enrichment Service")
    init_firebase()
    log.info("Firebase initialized")
    yield
    log.info("Shutting down AI Lead Enrichment Service")


app = FastAPI(
    title="AI Lead Enrichment Service",
    description=(
        "Enriches Specxnet ERP market leads using Perplexity sonar-pro. "
        "Accepts batches of leads, enriches company + contact data asynchronously, "
        "and sends progress/completion callbacks to the ERP."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS (restrict to ERP domain in production) ───────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten this to specxnet.com in production
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────
app.include_router(enrich.router, prefix="/api/v1", tags=["Lead Enrichment"])
app.include_router(status.router, prefix="/api/v1", tags=["Job Status"])
app.include_router(internal.router, prefix="/api/internal", tags=["Internal"])


# ── Health check ──────────────────────────────────────────────────────
@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check() -> HealthResponse:
    """Liveness probe — used by Cloud Run and load balancers."""
    return HealthResponse(status="ok", version="1.0.0")
