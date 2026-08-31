"""
app/api/routes/status.py — GET /api/v1/status/{job_id}

Returns the current state of an enrichment job from Firestore.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Header, Depends
from typing import Optional

from app.api.middleware.auth import verify_api_key
from app.api.schemas.responses import JobStatusResponse
from app.db.firebase import get_firestore
from app.utils.logging import get_logger

router = APIRouter()
log = get_logger(__name__)


@router.get(
    "/status/{job_id}",
    response_model=JobStatusResponse,
    summary="Get enrichment job status",
    description="Returns the current status and progress of an enrichment job.",
)
async def get_job_status(
    job_id: str,
    client_info: dict = Depends(verify_api_key),
) -> JobStatusResponse:

    # ── Fetch job from Firestore ─────────────────────────────────────
    db = get_firestore()
    doc = await db.collection("enrichment_jobs").document(job_id).get()

    if not doc.exists:
        raise HTTPException(
            status_code=404,
            detail={"error": "job_not_found", "message": f"Job '{job_id}' does not exist."},
        )

    data = doc.to_dict()
    total = data.get("total_leads", 0)
    processed = data.get("processed_leads", 0)
    progress_pct = round((processed / total) * 100, 1) if total > 0 else 0.0

    return JobStatusResponse(
        job_id=job_id,
        request_id=data.get("request_id", ""),
        status=data.get("status", "unknown"),
        total_leads=total,
        processed_leads=processed,
        updated_leads=data.get("updated_leads", 0),
        failed_leads=data.get("failed_leads", 0),
        progress_percent=progress_pct,
        avg_confidence=data.get("avg_confidence"),
        created_at=data.get("created_at"),
        completed_at=data.get("completed_at"),
        error_code=data.get("error_code"),
        error_details=data.get("error_details"),
    )
