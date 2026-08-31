"""
app/api/routes/internal.py — Internal webhook endpoints.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from app.config import settings
from app.api.schemas.requests import LeadRecord
from app.services.enrichment import process_batch_leads
from app.utils.logging import get_logger

router = APIRouter()
log = get_logger(__name__)

class InternalProcessBatchRequest(BaseModel):
    job_id: str
    leads_batch: list[dict]
    callback_url: str
    auth_key: str
    file_key: str

def validate_internal_token(x_internal_auth: str = Header(...)):
    if x_internal_auth != settings.internal_auth_token:
        raise HTTPException(status_code=401, detail="Invalid internal auth token")
    return True

@router.post(
    "/process-batch",
    summary="Internal worker endpoint to process a batch of leads",
    include_in_schema=False,
)
async def process_batch_worker(
    body: InternalProcessBatchRequest,
    x_internal_auth: str = Header(..., alias="X-Internal-Auth"),
):
    validate_internal_token(x_internal_auth)
    
    lead_records = [LeadRecord(**ld) for ld in body.leads_batch]
    
    await process_batch_leads(
        job_id=body.job_id,
        leads=lead_records,
        callback_url=body.callback_url,
        auth_key=body.auth_key,
        file_key=body.file_key,
    )
    
    return {"status": "ok"}
