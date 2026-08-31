"""
app/services/callback.py — ERP callback sender.

Sends progress, completion, and failure payloads to the ERP's callback_url
using httpx with a 30-second timeout. Retries once on transient errors.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type

from app.utils.logging import get_logger

log = get_logger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@retry(
    stop=stop_after_attempt(2),
    wait=wait_fixed(5),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
    reraise=False,  # Do not crash the worker if callback fails
)
async def _post_callback(url: str, payload: dict) -> None:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, json=payload)
        log.info(
            "Callback sent",
            url=url,
            action=payload.get("action"),
            status_code=response.status_code,
        )


async def send_progress_callback(
    callback_url: str,
    auth_key: str,
    file_key: str,
    progress: int,
    remarks: str = "",
) -> None:
    """Send a progress update callback (0–100%) to the ERP."""
    payload = {
        "auth_key": auth_key,
        "file_key": file_key,
        "action": "progress_update",
        "status": "researching",
        "progress": progress,
        "remarks": remarks,
    }
    await _post_callback(callback_url, payload)


async def send_completion_callback(
    callback_url: str,
    auth_key: str,
    file_key: str,
    enriched_leads: list[dict],
    stats: dict,
) -> None:
    """
    Send the final completion callback with all enriched lead data.

    stats dict keys: total, updated, failed, avg_confidence
    """
    payload = {
        "auth_key": auth_key,
        "file_key": file_key,
        "data": {"leads": enriched_leads},
        "action": "completed",
        "status": "completed",
        "confidence": stats.get("avg_confidence", 0),
        "remarks": f"Processed {stats.get('total', 0)} leads",
        "processed_rows": stats.get("total", 0),
        "updated_rows": stats.get("updated", 0),
        "failed_rows": stats.get("failed", 0),
        "completed_at": _utcnow_iso(),
    }
    await _post_callback(callback_url, payload)


async def send_failure_callback(
    callback_url: str,
    auth_key: str,
    file_key: str,
    error_code: str,
    error_details: str,
) -> None:
    """Send a failure callback if the enrichment job fails completely."""
    payload = {
        "auth_key": auth_key,
        "file_key": file_key,
        "action": "failed",
        "status": "failed",
        "remarks": error_details,
        "error_code": error_code,
        "error_details": error_details,
        "failed_at": _utcnow_iso(),
    }
    await _post_callback(callback_url, payload)
