"""
app/api/schemas/responses.py — Pydantic response models.
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel


class EnrichResponse(BaseModel):
    """Immediate 200 response sent back to the ERP after job is queued."""

    status: str = "success"
    message: str = "Job queued successfully"
    job_id: str


class JobStatusResponse(BaseModel):
    """Response for GET /api/v1/status/{job_id}."""

    job_id: str
    request_id: str
    status: str  # queued | researching | completed | failed
    total_leads: int
    processed_leads: int
    updated_leads: int
    failed_leads: int
    progress_percent: float
    avg_confidence: Optional[float] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_code: Optional[str] = None
    error_details: Optional[str] = None


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"
