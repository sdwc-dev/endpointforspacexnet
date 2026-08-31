"""
app/api/routes/enrich.py — POST /api/v1/enrich

Receives the ERP lead batch, validates it, creates a Firestore job,
and immediately fires the enrichment background task.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends

from app.api.middleware.auth import verify_api_key
from app.api.schemas.requests import EnrichRequest, LeadRecord
from app.api.schemas.responses import EnrichResponse
from app.db.firebase import get_firestore
from app.services.tasks import enqueue_batch_task
from app.utils.logging import get_logger

router = APIRouter()
log = get_logger(__name__)


@router.post(
    "/enrich",
    response_model=EnrichResponse,
    summary="Enrich a batch of market leads",
    description=(
        "Accepts a batch of lead records from the Specxnet ERP, queues "
        "asynchronous enrichment via Perplexity sonar-pro, and returns a "
        "job_id immediately. Progress and completion callbacks are sent to "
        "the provided callback_url."
    ),
)
async def enrich_leads(
    body: EnrichRequest,
    client_info: dict = Depends(verify_api_key),
) -> EnrichResponse:

    # ── 2. Check expiry ───────────────────────────────────────────────
    now_utc = datetime.now(timezone.utc)
    expires_at = body.expires_at
    # Make timezone-aware if naive
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at <= now_utc:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "request_expired",
                "message": f"The request has expired (expires_at={body.expires_at.isoformat()}).",
            },
        )

    # ── 3. Create Firestore job document ─────────────────────────────
    job_id = f"JOB-{uuid.uuid4().hex[:12].upper()}"
    leads = body.data.leads
    db = get_firestore()

    job_doc = {
        "job_id": job_id,
        "request_id": body.request_id,
        "auth_key": body.auth_key,
        "file_key": body.file_key,
        "callback_url": body.callback_url,
        "status": "queued",
        "total_leads": len(leads),
        "processed_leads": 0,
        "updated_leads": 0,
        "failed_leads": 0,
        "avg_confidence": None,
        "expires_at": body.expires_at.isoformat(),
        "created_at": now_utc.isoformat().replace("+00:00", "Z"),
        "completed_at": None,
        "error_code": None,
        "error_details": None,
    }

    await db.collection("enrichment_jobs").document(job_id).set(job_doc)

    log.info(
        "Enrichment job queued",
        job_id=job_id,
        request_id=body.request_id,
        num_leads=len(leads),
    )

    # ── 4. Dispatch Cloud Tasks (Batched) ──────────────────────────────
    batch_size = 100
    for i in range(0, len(leads), batch_size):
        chunk = leads[i : i + batch_size]
        await enqueue_batch_task(
            job_id=job_id,
            leads_batch=[l.model_dump() for l in chunk],
            callback_url=body.callback_url,
            auth_key=body.auth_key,
            file_key=body.file_key,
        )

    # ── 5. Return immediate 200 ───────────────────────────────────────
    return EnrichResponse(
        status="success",
        message="Job queued successfully",
        job_id=job_id,
    )


import pandas as pd
from fastapi import UploadFile, File, Form
from pydantic import ValidationError
import math

@router.post(
    "/enrich/excel",
    response_model=EnrichResponse,
    summary="Enrich a batch of market leads from an Excel file",
)
async def enrich_leads_excel(
    file: UploadFile = File(...),
    callback_url: str = Form(...),
    auth_key: str = Form(...),
    file_key: str = Form(...),
    request_id: str = Form(...),
    expires_at: datetime = Form(...),
    client_info: dict = Depends(verify_api_key),
) -> EnrichResponse:
    
    # ── 1. Check expiry ───────────────────────────────────────────────
    now_utc = datetime.now(timezone.utc)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at <= now_utc:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "request_expired",
                "message": f"The request has expired (expires_at={expires_at.isoformat()}).",
            },
        )
        
    # ── 2. Parse Excel File ───────────────────────────────────────────
    try:
        # We read all columns as strings to prevent issues with ints/floats becoming NaNs/floats
        df = pd.read_excel(file.file, engine="openpyxl", dtype=str)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid Excel file: {str(e)}")
        
    leads = []
    skipped_count = 0
    
    # Map common excel column names to the fields expected by Pydantic (or their aliases)
    column_mapping = {
        "first name": "first_name",
        "last name": "last_name",
        "phone number": "phone_number",
        "company name": "company_name",
        "parent company": "parent_company",
        "company type": "company_type",
        "email": "email",
        "city": "city",
        "country": "country",
        "industry": "industry",
        "source": "source",
        "opportunity type": "opportunity_type",
        "comments": "comments",
        "project type": "project_type",
        "designation": "designation",
        "id": "id",
    }
    
    for index, row in df.iterrows():
        row_dict = row.to_dict()
        
        try:
            # Keep only non-null values that aren't empty strings
            clean_row = {}
            for k, v in row_dict.items():
                if pd.notna(v) and str(v).strip() != "":
                    # Map to known key if possible
                    mapped_key = column_mapping.get(str(k).strip().lower(), k)
                    clean_row[mapped_key] = v
            
            # Generate a dummy ID if none exists (since Excel files often don't have one)
            if "id" not in clean_row:
                clean_row["id"] = f"EXCEL-{index+1}-{uuid.uuid4().hex[:8]}"
                
            lead = LeadRecord(**clean_row)
            leads.append(lead)
        except ValidationError as e:
            # Skip rows missing required fields
            skipped_count += 1
            log.debug(f"Skipping row {index}: Validation failed", errors=e.errors())
            continue
            
    if not leads:
        raise HTTPException(status_code=400, detail="No valid leads found in the Excel file. Ensure 'First Name' and 'Last Name' are provided for at least one row.")

    # ── 3. Create Firestore job document ─────────────────────────────
    job_id = f"JOB-{uuid.uuid4().hex[:12].upper()}"
    db = get_firestore()

    job_doc = {
        "job_id": job_id,
        "request_id": request_id,
        "auth_key": auth_key,
        "file_key": file_key,
        "callback_url": callback_url,
        "status": "queued",
        "total_leads": len(leads),
        "processed_leads": 0,
        "updated_leads": 0,
        "failed_leads": 0,
        "avg_confidence": None,
        "expires_at": expires_at.isoformat(),
        "created_at": now_utc.isoformat().replace("+00:00", "Z"),
        "completed_at": None,
        "error_code": None,
        "error_details": None,
    }

    await db.collection("enrichment_jobs").document(job_id).set(job_doc)

    log.info(
        "Enrichment job queued from Excel",
        job_id=job_id,
        request_id=request_id,
        num_leads=len(leads),
        skipped=skipped_count
    )

    # ── 4. Dispatch Cloud Tasks (Batched) ──────────────────────────────
    batch_size = 100
    for i in range(0, len(leads), batch_size):
        chunk = leads[i : i + batch_size]
        await enqueue_batch_task(
            job_id=job_id,
            leads_batch=[l.model_dump() for l in chunk],
            callback_url=callback_url,
            auth_key=auth_key,
            file_key=file_key,
        )

    # ── 5. Return immediate 200 ───────────────────────────────────────
    msg = "Job queued successfully"
    if skipped_count > 0:
        msg = f"Job queued successfully. Note: {skipped_count} rows were skipped due to missing Name or ID."
        
    return EnrichResponse(
        status="success",
        message=msg,
        job_id=job_id,
    )
